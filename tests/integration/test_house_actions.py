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


@pytest.mark.parametrize('lighting_mode',['reference_daylight_bake','warm_interior'])
def test_house_run_rebuilds_reinspects_and_persists_selected_candidate(tmp_path,monkeypatch,lighting_mode):
    from hdrp_agent.domain import fingerprint
    h,r=house_setup(tmp_path);h.admit(r)
    room=dict(id='office',purpose='office',floor_index=0,width_m=6,depth_m=6,brief='work')
    def ask(row,key,*args):
        if key=='outline':return dict(title='office',rooms=[room],unresolved=[])
        if key=='lighting-intent':return dict(mode=lighting_mode,reason='Requested mood',unresolved=[])
        return dict(room_id='office',groups=[dict(id='storage',recipe='storage',priority='mandatory',description='storage')],detail_assets=[],unresolved=[])
    monkeypatch.setattr(h,'ask',ask)
    asset=dict(prefab_guid='a'*32,dependency_hash='b'*32,bounds_center=[0,.5,0],bounds_size=[1,1,1],front_status='qualified',surfaces=[],support_regions=[])
    monkeypatch.setattr(h,'catalogue',lambda:{'Wardrobe':asset})
    builds=[]
    def native(row,manifest):
        assert manifest['lighting']==lighting_mode
        builds.append(manifest['exposure_ev']);digest=h.artifacts.put(str(manifest['exposure_ev']).encode())
        receipt=dict(details_artifact_hash=digest,artifact_hashes=[digest])
        proof=dict(manifest_hash=fingerprint(manifest),scene_path='House-'+str(manifest['exposure_ev']),scene_version=digest,source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in manifest['instances']],defects=[],captures=[dict(room_id='office',mean_rgb=.95 if manifest['exposure_ev']==6 else .5)])
        if manifest.get('calibrate_exposure'):
            proof['exposure_calibration']=dict(fixed_readback_verified=True,locked_ev100=manifest['exposure_ev'])
            proof['captures'][0]['render_request_state']=dict(status='observed',exposure_mode='Fixed',exposure_ev=manifest['exposure_ev'])
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


def interrupted_build(tmp_path):
    import json
    from hdrp_agent.domain import fingerprint
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id'])
    with h.store.tx() as c:
        project=c.execute('SELECT * FROM projects WHERE id=?',(row['project_id'],)).fetchone()
        epoch=project['epoch'];body=dict(payload=dict(run_id=row['run_id']))
        digest=fingerprint(body['payload'])
        c.execute("UPDATE house_actions SET state='recovery_required' WHERE id=?",(row['id'],))
        h.store.update_session(c,row['session_id'],state='recovery_required')
        c.execute('INSERT INTO commands(id,session_id,project_id,epoch,kind,status,body,payload_hash) VALUES(?,?,?,?,?,?,?,?)',('interrupted-build',row['session_id'],row['project_id'],epoch,'build_house','unknown',canonical(body),digest))
        c.execute("UPDATE projects SET epoch='new-editor' WHERE id=?",(row['project_id'],));h.queue.touch(c,row['project_id'],'new-editor')
    result=dict(command_id='interrupted-build',payload_hash=digest,bridge_epoch=epoch,status='unknown',before_version='source',after_version='source',artifact_hashes=[],captures=[],snapshot_id=None,manifest_hash='0'*64,bake_status='not_required',details_artifact_hash=None,error=dict(code='DOMAIN_RELOAD',message='Editor reloaded',retryable=False,command_id='interrupted-build'))
    receipt=dict(command_id=result['command_id'],payload_hash=digest,bridge_epoch=epoch,status='unknown',result=result)
    root=h.settings.project_path(json.loads(project['body'])['project_root'])
    path=root/'.hdrp-agent/bridge/receipts/interrupted-build.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(canonical(receipt))
    return h,r,row,path


def test_close_reloaded_build_preserves_unknown_evidence_and_releases_lease(tmp_path):
    h,r,row,path=interrupted_build(tmp_path);original=path.read_bytes()
    other=deepcopy(r);other.update(action_id='new-house',idempotency_key='new-house')
    with pytest.raises(AgentError) as error:h.admit(other)
    assert error.value.code=='EDITOR_RECOVERY_REQUIRED'
    result=h.stop(row['id'],dict(reason='Close interrupted build'))
    assert result['state']=='failed' and result['execution_state']=='interrupted'
    assert path.read_bytes()==original
    with h.store.connect() as c:
        command=c.execute("SELECT * FROM commands WHERE id='interrupted-build'").fetchone()
        assert command['status']=='unknown' and command['result'] is None
        assert c.execute('SELECT state FROM sessions WHERE id=?',(row['session_id'],)).fetchone()[0]=='interrupted'
        assert c.execute("SELECT count(*) FROM events WHERE kind='house.recovery_closed'").fetchone()[0]==1
    assert h.stop(row['id'],dict(reason='Close again'))['state']=='failed'
    assert h.admit(other)['state']=='queued'


@pytest.mark.parametrize('problem',['missing_receipt','mismatched_result','same_epoch','running_command','stale_presence','non_house'])
def test_close_reloaded_build_refuses_unverified_or_active_execution(tmp_path,problem):
    import json
    h,r,row,path=interrupted_build(tmp_path)
    with h.store.tx() as c:
        if problem=='same_epoch':c.execute("UPDATE projects SET epoch=(SELECT epoch FROM commands WHERE id='interrupted-build')");h.queue.touch(c,row['project_id'],c.execute('SELECT epoch FROM projects').fetchone()[0])
        if problem=='running_command':c.execute("UPDATE commands SET status='running'")
        if problem=='stale_presence':c.execute("UPDATE project_presence SET last_seen='2000-01-01T00:00:00+00:00'")
        if problem=='non_house':c.execute("UPDATE commands SET kind='apply_patch'")
    if problem=='missing_receipt':path.unlink()
    if problem=='mismatched_result':
        receipt=json.loads(path.read_text());receipt['result']['payload_hash']='b'*64;path.write_text(canonical(receipt))
    with pytest.raises(AgentError):h.stop(row['id'],dict(reason='Close'))
    assert h.get(row['id'])['state']=='recovery_required'
    assert h.store.get('sessions',row['session_id'])['state']=='recovery_required'


def test_late_native_cancellation_releases_stopped_run_but_unknown_does_not(tmp_path):
    h,r,row,path=interrupted_build(tmp_path)
    with h.store.tx() as c:
        c.execute('UPDATE sessions SET stop_requested=1 WHERE id=?',(row['session_id'],))
    assert not h.close_cancelled_build(row)
    with h.store.tx() as c:
        c.execute("UPDATE commands SET status='cancelled',result=? WHERE session_id=?",(canonical(dict(status='cancelled')),row['session_id']))
    assert h.close_cancelled_build(row)
    assert h.get(row['id'])['state']=='failed'
    assert h.store.get('sessions',row['session_id'])['state']=='interrupted'


def test_outline_index_error_is_returned_to_model_before_furnishing(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r)
    calls=[]
    def ask(row,key,text,*args):
        calls.append(key)
        if key in {'outline','outline-repair-1'}:
            return dict(title='Bedroom',rooms=[dict(id='bedroom',purpose='bedroom',floor_index=1 if key=='outline' else 0,width_m=6,depth_m=6,brief='Child bedroom')],unresolved=[])
        return dict(room_id='bedroom',groups=[],detail_assets=[],unresolved=[])
    monkeypatch.setattr(h,'ask',ask);monkeypatch.setattr(h,'catalogue',lambda:{})
    h.run(r['action_id'])
    assert calls==['outline','outline-repair-1','room-bedroom']
    assert h.get(r['action_id'])['error_code']=='PROGRAM_INCOMPLETE'


def test_repeated_invalid_outline_stops_instead_of_replaying_forever(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);calls=[]
    def ask(row,key,*args):
        calls.append(key)
        return dict(title='Bedroom',rooms=[dict(id='bedroom',purpose='bedroom',floor_index=1,width_m=6,depth_m=6,brief='Child bedroom')],unresolved=[])
    monkeypatch.setattr(h,'ask',ask)
    h.run(r['action_id'])
    assert calls==['outline','outline-repair-1']
    assert h.get(r['action_id'])['error_code']=='VERTICAL_ACCESS_UNQUALIFIED'


def test_independent_sam_concepts_run_concurrently_and_keep_evidence_order(tmp_path,monkeypatch):
    import io
    from PIL import Image
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id'])
    stream=io.BytesIO();Image.new('RGB',(16,16)).save(stream,format='PNG')
    artifact=h.artifacts.put(stream.getvalue(),'image/png')
    names=['bed','chair','desk','lamp'];barrier=threading.Barrier(4);decoded=[]
    monkeypatch.setattr('hdrp_agent.house_service.segmentation_concepts',lambda *args:names)
    def provider(row,key,request,*args):
        barrier.wait(timeout=5)
        return request['input'][0]['content'][0]['text']
    monkeypatch.setattr(h,'provider_call',provider)
    def decode(text,*args):decoded.append(text);return []
    monkeypatch.setattr('hdrp_agent.providers.sam_decoder.decode',decode)
    monkeypatch.setattr(h.houses,'context',lambda *args:{})
    monkeypatch.setattr(h,'ask',lambda *args:dict(room_id='bedroom',observations=[]))
    h.inspect(row,dict(rooms=[dict(id='bedroom')]),[],dict(scene_version='v1',captures=[dict(room_id='bedroom',key='front',usable=True,artifact_hash=artifact)]))
    assert decoded==names
    assert [s['concept'] for s in h.progress(r['action_id'])['segmentations']]==names


def test_reviewed_supports_trigger_layout_revision_and_new_assets_are_reviewed(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id']);room=dict(id='bedroom')
    first=dict(room_id='bedroom',groups=[],detail_assets=[],unresolved=['Bedside support unavailable'])
    revised=dict(room_id='bedroom',groups=[],detail_assets=['Lamp_table'],unresolved=[])
    reviewed=[]
    def review(row,room,design,assets):
        reviewed.append(design)
        return len(reviewed)==1
    monkeypatch.setattr(h,'review_selected_assets',review);monkeypatch.setattr(h,'ask',lambda *args:revised)
    result=h.refine_reviewed_design(row,room,first,{},dict(rooms=[room],portals=[]),'Bedroom with bedside lamp')
    assert result==revised and reviewed==[first,revised]


def test_layout_revision_does_not_repeat_identical_design_forever(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id']);room=dict(id='bedroom')
    design=dict(room_id='bedroom',groups=[],detail_assets=[],unresolved=[]);reviews=[]
    monkeypatch.setattr(h,'review_selected_assets',lambda *args:reviews.append(True) or True)
    monkeypatch.setattr(h,'ask',lambda *args:design)
    assert h.refine_reviewed_design(row,room,design,{},dict(rooms=[room],portals=[]),'Bedroom')==design
    assert len(reviews)==1


def test_layout_repair_cannot_win_by_dropping_mandatory_furniture(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id']);room=dict(id='bedroom')
    design=dict(room_id='bedroom',groups=[dict(id='clothes',priority='mandatory',items=[dict(asset='Wardrobe')])],detail_assets=[],unresolved=[])
    empty=dict(room_id='bedroom',groups=[],detail_assets=[],unresolved=[])
    monkeypatch.setattr(h,'refine_reviewed_design',lambda row,room,design,*args:design)
    def place(building,design,assets):
        return dict(instances=[],requirements=[],missing=[dict(id='wardrobe',priority='mandatory',reason='Needs placement')] if design['groups'] else [])
    monkeypatch.setattr('hdrp_agent.house_service.place_groups',place)
    monkeypatch.setattr('hdrp_agent.house_service.layout_feedback',lambda *args:{})
    monkeypatch.setattr(h,'ask',lambda *args:empty)
    selected,placed=h.place_reviewed_design(row,room,design,{},dict(rooms=[room],portals=[]),'Bedroom with wardrobe')
    assert selected==design and placed['missing']


def test_optional_accessory_can_remain_unresolved_without_becoming_retained_mandatory_asset(tmp_path,monkeypatch):
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id']);room=dict(id='bedroom')
    bed=dict(asset='Bed',priority='mandatory');pillow=dict(asset='Pillow',priority='optional')
    design=dict(room_id='bedroom',groups=[dict(id='sleep',priority='mandatory',items=[bed,pillow])],detail_assets=[],unresolved=[])
    revised=dict(design,groups=[dict(id='sleep',priority='mandatory',items=[bed])],unresolved=['Optional pillow needs an appropriate support'])
    monkeypatch.setattr(h,'refine_reviewed_design',lambda row,room,design,*args:design)
    def place(building,design,assets):
        missing=[dict(id='pillow',priority='optional',reason='No qualified support')] if len(design['groups'][0]['items'])==2 else []
        return dict(instances=[],requirements=[],missing=missing)
    monkeypatch.setattr('hdrp_agent.house_service.place_groups',place)
    monkeypatch.setattr('hdrp_agent.house_service.layout_feedback',lambda *args:{})
    monkeypatch.setattr(h,'ask',lambda *args:revised)
    selected,placed=h.place_reviewed_design(row,room,design,{},dict(rooms=[room],portals=[]),'Bedroom')
    assert selected==revised and not placed['missing'] and selected['unresolved']


@pytest.mark.parametrize('status,validated,expected',[('settled',True,'recover'),('unknown',True,'send'),('settled',False,'send')])
def test_exact_response_reuse_requires_settlement_and_validated_house_value(tmp_path,monkeypatch,status,validated,expected):
    from types import SimpleNamespace
    from hdrp_agent.domain import fingerprint
    h,r=house_setup(tmp_path);h.admit(r);row=h.row(r['action_id']);request={'model':'test','input':'same'}
    digest=fingerprint(request);calls=[]
    with h.store.tx() as c:
        c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',('old-call','test',digest,status,10,5 if status=='settled' else None,'{}','2026-01-01'))
        c.execute('INSERT INTO house_calls VALUES(?,?,?,?,?)',('old-run','old-key',digest,'old-call','{"answer":1}' if validated else None))
    class Provider:
        client=SimpleNamespace(close=lambda:None)
        def __init__(self,*args):pass
        def recover_completed(self,*args):calls.append('recover');return {'value':{'answer':1}}
        def send(self,*args):calls.append('send');return {'value':{'answer':2}}
    monkeypatch.setattr('hdrp_agent.house_service.HouseCallBudget',lambda *args:None)
    h.provider_factory=Provider
    h.provider_call(row,'new-key',request)
    assert calls==[expected]
    with h.store.connect() as c:
        assert c.execute('SELECT status,reserved FROM calls WHERE id=?',('old-call',)).fetchone()[:]==(status,10)


def test_provider_resume_preserves_run_and_unknown_billing(tmp_path):
    import json
    h,r=house_setup(tmp_path);action=h.admit(r);run=action['run_id']
    frozen=h.artifacts.put(canonical(dict(manifest=dict(run_id=run),outline={},requirements=[],missing=[])).encode(),'application/json')
    with h.store.tx() as c:
        cp=json.loads(c.execute('SELECT checkpoint FROM house_actions WHERE id=?',(r['action_id'],)).fetchone()[0]);cp.update(planned_run_hash=frozen,error_code='PROVIDER_OUTCOME_UNKNOWN')
        c.execute("UPDATE house_actions SET state='failed',checkpoint=? WHERE id=?",(canonical(cp),r['action_id']))
        h.store.update_session(c,action['session_id'],state='interrupted')
        c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',('unknown-call','sam-3.1','x','unknown',2500,None,'{}','2026-01-01'))
        c.execute('INSERT INTO house_calls VALUES(?,?,?,?,?)',(run,'sam-x','x','unknown-call',None))
    resumed=h.resume(r['action_id'],dict(reason='Continue exact frozen plan'))
    assert resumed['state']=='queued' and resumed['run_id']==run
    with h.store.connect() as c:
        assert c.execute('SELECT status,reserved FROM calls WHERE id=?',('unknown-call',)).fetchone()[:]==('unknown',2500)
    assert h.planned_run(h.row(r['action_id']),{})['manifest']['run_id']==run


def test_resume_rejects_missing_plan_or_changed_editor(tmp_path):
    import json
    h,r=house_setup(tmp_path);action=h.admit(r)
    with h.store.tx() as c:
        cp=json.loads(c.execute('SELECT checkpoint FROM house_actions WHERE id=?',(r['action_id'],)).fetchone()[0]);cp.update(error_code='PROVIDER_OUTCOME_UNKNOWN')
        c.execute("UPDATE house_actions SET state='failed',checkpoint=? WHERE id=?",(canonical(cp),r['action_id']))
        h.store.update_session(c,action['session_id'],state='interrupted')
    with pytest.raises(AgentError,match='frozen plan'):h.resume(r['action_id'],dict(reason='Resume'))
    cp.update(planned_run_hash='f'*64,epoch='different')
    with h.store.tx() as c:c.execute('UPDATE house_actions SET checkpoint=? WHERE id=?',(canonical(cp),r['action_id']))
    with pytest.raises(AgentError,match='epoch changed'):h.resume(r['action_id'],dict(reason='Resume'))


@pytest.mark.parametrize('message,allowed', [('Enrichment changed requirement identity',True),('House run already has a different program',False)])
def test_resume_only_known_enrichment_identity_conflict(tmp_path,message,allowed):
    import json
    h,r=house_setup(tmp_path);action=h.admit(r)
    with h.store.tx() as c:
        cp=json.loads(c.execute('SELECT checkpoint FROM house_actions WHERE id=?',(r['action_id'],)).fetchone()[0])
        cp.update(planned_run_hash='a'*64,error_code='IDEMPOTENCY_CONFLICT',message=message)
        c.execute("UPDATE house_actions SET state='failed',checkpoint=? WHERE id=?",(canonical(cp),r['action_id']))
        h.store.update_session(c,action['session_id'],state='interrupted')
    if allowed:assert h.resume(r['action_id'],dict(reason='Continue after identity fix'))['state']=='queued'
    else:
        with pytest.raises(AgentError):h.resume(r['action_id'],dict(reason='Resume'))


def test_saved_correction_candidate_rejects_changed_or_foreign_scene(tmp_path):
    import hashlib
    h,r=house_setup(tmp_path);state=h.admit(r);row=h.row(r['action_id'])
    relative='Assets/AgentWorkspace/HouseRuns/'+state['run_id']+'/House.unity'
    path=tmp_path/'project'/relative;path.parent.mkdir(parents=True);path.write_bytes(b'candidate')
    proof=dict(run_id=state['run_id'],scene_path=relative,scene_version=hashlib.sha256(b'candidate').hexdigest(),source_scene_unchanged=True)
    h.verify_saved_candidate(row,proof)
    with pytest.raises(AgentError,match='changed'):h.verify_saved_candidate(row,dict(proof,run_id='other'))
    path.write_bytes(b'edited')
    with pytest.raises(AgentError,match='changed'):h.verify_saved_candidate(row,proof)
