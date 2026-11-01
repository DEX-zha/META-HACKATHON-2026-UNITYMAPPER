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
        proof=dict(manifest_hash=fingerprint(manifest),scene_path='House-'+str(manifest['exposure_ev']),scene_version=digest,source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in manifest['instances']],defects=[],captures=[dict(mean_rgb=.95 if manifest['exposure_ev']==6 else .5)])
        return receipt,proof
    monkeypatch.setattr(h,'native',native);monkeypatch.setattr(h,'inspect',lambda *a,**k:[]);monkeypatch.setattr(h,'enrich',lambda *a:None)
    h.run(r['action_id']);result=h.progress(r['action_id'])
    assert result['state']=='completed' and builds==[6,7]
    assert result['scene_path']=='House-7'
    assert [i['status'] for i in result['iterations']]==['proposed','accepted']
    assert result['house']['requirements'][0]['status']=='satisfied'
    # Gate evidence is not fabricated just because a correction improved exposure.
    assert result['quality_state']=='incomplete' and result['execution_state']=='stalled'
