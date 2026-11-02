import threading
from copy import deepcopy
import pytest
from hdrp_agent.domain import AgentError,canonical
from hdrp_agent.house_service import HouseService
from test_chat_actions import setup


def house_setup(tmp_path):
    worker,legacy,service,old=setup(tmp_path)
    with worker.store.tx() as c:
        data=__import__('json').loads(c.execute('SELECT body FROM projects').fetchone()[0]);data['capabilities'].append('build_house')
        c.execute('UPDATE projects SET body=?',(canonical(data),))
    houses=HouseService(worker.settings,worker.store,worker.runner.queue,worker.artifacts,threading.Event())
    request=deepcopy(old);request.update(kind='generate_house',artifact_hashes=[])
    request['parameters']=dict(schema_version='house.v1',brief='Create an office',reference_hashes=[],interior_style='B',creative_policy='brief_guided')
    return houses,request


def test_house_admission_without_image_is_idempotent_and_owns_editor(tmp_path):
    h,r=house_setup(tmp_path);a=h.admit(r)
    assert a['state']=='queued' and h.admit(r)['run_id']==a['run_id']
    other=deepcopy(r);other['action_id']='other';other['idempotency_key']='other'
    with pytest.raises(AgentError,match='owns'):h.admit(other)
    assert h.next_ready()==r['action_id'] and h.next_ready() is None
    h.recover_startup();assert h.get(r['action_id'])['state']=='recovery_required'


def test_reference_mode_does_not_silently_invent_missing_reference(tmp_path):
    h,r=house_setup(tmp_path);r['parameters']['creative_policy']='reference_guided'
    with pytest.raises(AgentError,match='reference'):h.admit(r)


def test_inspection_batches_every_capture_and_persists_sam(tmp_path,monkeypatch):
    import io
    from PIL import Image
    h,r=house_setup(tmp_path);action=h.admit(r);row=h.row(r['action_id'])
    image=Image.new('RGB',(16,16));out=io.BytesIO();image.save(out,format='PNG')
    artifact=h.artifacts.put(out.getvalue(),'image/png')
    calls=[];observations=[]
    monkeypatch.setattr(h,'provider_call',lambda *a,**kw:'segmentation')
    monkeypatch.setattr('hdrp_agent.providers.sam_decoder.decode',lambda *a,**kw:[])
    monkeypatch.setattr(h.houses,'context',lambda *a:{})
    monkeypatch.setattr(h.houses,'defect',lambda run,d:observations.append(d))
    def ask(row,key,text,schema,images):
        calls.append(len(images))
        return dict(room_id='office',observations=[dict(severity='warning',kind='composition',message='needs detail')])
    monkeypatch.setattr(h,'ask',ask)
    h.inspect(row,dict(rooms=[dict(id='office')]),[],dict(scene_version='v1',captures=[dict(room_id='office',key=str(i),usable=True,artifact_hash=artifact) for i in range(25)]))
    assert calls==[12,12,1]
    assert len(observations)==3
    assert len(h.progress(r['action_id'])['segmentations'])==25


def test_stopped_queued_house_releases_editor_without_starting(tmp_path):
    h,r=house_setup(tmp_path);h.admit(r)
    h.stop(r['action_id'],dict(reason='User cancelled'))
    assert h.next_ready() is None
    other=deepcopy(r);other.update(action_id='next-house',idempotency_key='next-house')
    assert h.admit(other)['state']=='queued'


def test_failure_before_native_command_does_not_hold_editor(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r)
    def fail(*args,**kwargs):raise AgentError('INVALID_MODEL_OUTPUT','Invalid outline')
    monkeypatch.setattr(h,'ask',fail)
    h.run(r['action_id'])
    assert h.get(r['action_id'])['state']=='failed'
    other=deepcopy(r);other.update(action_id='next-house',idempotency_key='next-house')
    assert h.admit(other)['state']=='queued'


def test_house_run_rebuilds_reinspects_and_persists_selected_candidate(tmp_path,monkeypatch):
    from hdrp_agent.domain import fingerprint
    h,r=house_setup(tmp_path);h.admit(r)
    room=dict(id='office',purpose='office',floor_index=0,width_m=6,depth_m=6,brief='work')
    def ask(row,key,*args):
        if key=='outline':return dict(title='office',rooms=[room],unresolved=[])
        return dict(room_id='office',groups=[dict(id='storage',recipe='storage',priority='mandatory',description='storage')],detail_assets=[],unresolved=[])
    monkeypatch.setattr(h,'ask',ask)
    asset=dict(prefab_guid='a'*32,dependency_hash='b'*32,bounds_center=[0,.5,0],bounds_size=[1,1,1],front_status='qualified',surfaces=[],support_regions=[])
    monkeypatch.setattr(h,'catalogue',lambda:{'Wardrobe':asset})
    builds=[]
    def native(row,manifest):
        builds.append(manifest['exposure_ev']);digest=h.artifacts.put(str(manifest['exposure_ev']).encode())
        receipt=dict(details_artifact_hash=digest,artifact_hashes=[digest])
        proof=dict(manifest_hash=fingerprint(manifest),scene_path='House-'+str(manifest['exposure_ev']),scene_version=digest,source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in manifest['instances']],defects=[],captures=[dict(room_id='office',mean_rgb=.95 if manifest['exposure_ev']==6 else .5)])
        return receipt,proof
    monkeypatch.setattr(h,'native',native);monkeypatch.setattr(h,'inspect',lambda *a,**k:[]);monkeypatch.setattr(h,'enrich',lambda *a:None)
    h.run(r['action_id']);result=h.progress(r['action_id'])
    assert result['state']=='completed' and builds==[6,7]
    assert result['scene_path']=='House-7'
    assert [i['status'] for i in result['iterations']]==['proposed','accepted']
    assert result['house']['requirements'][0]['status']=='satisfied'
    # Gate evidence is not fabricated just because a correction improved exposure.
    assert result['quality_state']=='incomplete' and result['execution_state']=='stalled'


def test_public_activity_preserves_order_and_survives_service_reload(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id'])
    h.save(row,'outline','Planning rooms')
    value=dict(title='Office',rooms=[dict(purpose='Office',width_m=6,depth_m=3,floor_index=0,brief='Keep a clear route')],unresolved=[])
    monkeypatch.setattr(h,'provider_call',lambda *args:value)
    h.ask(row,'outline','test','ModelHouseOutline')
    progress=h.get(r['action_id'])['progress'];events=progress['activity']
    assert [e['kind'] for e in events]==['house.progress','house.progress','house.decision']
    assert 'Keep a clear route' in events[-1]['message']
    assert events[-1]['status']=='proposal_or_observation'
    fresh=HouseService(h.settings,h.store,h.queue,h.artifacts,threading.Event())
    assert fresh.get(r['action_id'])['progress']['activity']==events


def test_recovery_does_not_claim_success_or_replay(tmp_path):
    h,r=house_setup(tmp_path);h.admit(r)
    h.next_ready();h.recover_startup()
    diagnostic=h.get(r['action_id'])['progress']['recovery']
    assert diagnostic['automatic_retry'] is False
    assert diagnostic['cause']=='UNVERIFIED_NATIVE_OUTCOME'
    assert h.next_ready() is None


def test_recovery_diagnosis_requires_matching_native_receipt(tmp_path):
    import json
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id'])
    with h.store.tx() as c:
        project=c.execute('SELECT * FROM projects WHERE id=?',(row['project_id'],)).fetchone()
        c.execute("UPDATE house_actions SET state='recovery_required' WHERE id=?",(row['id'],))
        c.execute('INSERT INTO commands(id,session_id,project_id,epoch,kind,status,body,payload_hash) VALUES(?,?,?,?,?,?,?,?)',('native-test',row['session_id'],row['project_id'],project['epoch'],'build_house','unknown','{}','a'*64))
    root=h.settings.project_path(json.loads(project['body'])['project_root'])
    path=root/'.hdrp-agent/bridge/receipts/native-test.json';path.parent.mkdir(parents=True,exist_ok=True)
    receipt=dict(command_id='native-test',payload_hash='a'*64,bridge_epoch=project['epoch'],result=dict(status='unknown',error=dict(code='DOMAIN_RELOAD')))
    path.write_text(json.dumps(receipt))
    assert h.get(r['action_id'])['progress']['recovery']['cause']=='DOMAIN_RELOAD'
    receipt['payload_hash']='b'*64;path.write_text(json.dumps(receipt))
    assert h.get(r['action_id'])['progress']['recovery']['cause']=='UNVERIFIED_NATIVE_OUTCOME'
    with h.store.connect() as c:assert c.execute("SELECT status,result FROM commands WHERE id='native-test'").fetchone()['status']=='unknown'
