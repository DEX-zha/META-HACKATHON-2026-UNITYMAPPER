from datetime import date,datetime,timezone
from pathlib import Path
from types import SimpleNamespace
import io,json

from PIL import Image
import pytest

from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.budget import Budget,Pricing
from hdrp_agent.command_queue import CommandQueue
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError,canonical
from hdrp_agent.orchestrator import Orchestrator
from hdrp_agent.providers.fake import FakeProvider
from hdrp_agent.reference_worker import ReferenceWorker,score_pairs,inspection_for
from hdrp_agent.store import Store


def engine(tmp_path):
    settings=Settings(tmp_path,provider_mode='live',api_key='fixture-secret',token='fixture-local-token');store=Store(settings.db_path)
    (settings.state/'pricing.json').write_text(json.dumps(dict(verified_on=date.today().isoformat(),verified=True,currency='USD')))
    budget=Budget(store,Pricing(date.today().isoformat(),True));budget.confirm_balance(150000000,'offline unit fixture',datetime.now(timezone.utc).isoformat())
    with store.tx() as c:c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical(dict(scene_version='source',capabilities=[]))))
    artifacts=ArtifactStore(settings.state/'artifacts',store);runner=Orchestrator(settings,store,CommandQueue(store),artifacts)
    worker=ReferenceWorker(settings,store,artifacts,runner);root=worker.root/('a'*32);root.mkdir()
    Image.new('RGB',(1280,720),(140,)*3).save(root/'input.png')
    catalogue=[dict(asset_id='asset-chair',name='Chair',bounds_center_m=[0,.5,0],bounds_size_m=[1,1,1])]
    (root/'catalogue.json').write_text(canonical(catalogue))
    bundle=dict(schema_version='1.0',id=root.name,kind='external',brief='Reproduce the chair and light',provider_mode='live',max_iterations=3,session_timeout_seconds=1200,project_id='project',catalogue_file='catalogue.json',media_files=['input.png'])
    (root/'bundle.json').write_text(canonical(bundle))
    return worker,root,budget


def proposals():
    analysis=dict(summary='A chair',inspected_view_keys=['reference-0'],objects=[dict(key='chair',label='chair',asset_id='asset-chair',primitive=None,view_boxes=[dict(view_key='reference-0',bbox_xyxy=[.2,.2,.7,.8])],support_key=None)],limits=['Depth estimated from one image'])
    plan=dict(objects=[dict(key='chair',asset_id='asset-chair',primitive=None,position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1],base_color_rgba=None)],lights=[],estimated_views=[dict(key='reference-0',position_m=[0,1,-4],rotation_deg=[0,0,0],fov_deg=50)],exposure_ev=0,sky_color_rgb=[.1,.1,.1],fog_mean_free_path_m=None,notes=['Hidden geometry unverified'])
    return analysis,plan


@pytest.mark.parametrize('fidelity_mode',[None,'1.0'])
def test_reference_job_owns_global_session_and_restart_never_replays(tmp_path,fidelity_mode):
    worker,root,budget=engine(tmp_path)
    if fidelity_mode:
        path=root/'bundle.json';bundle=json.loads(path.read_text());bundle['fidelity_mode']=fidelity_mode;path.write_text(canonical(bundle))
    job=worker.claim(root/'bundle.json')
    with pytest.raises(AgentError):worker.claim(root/'bundle.json')
    assert worker.next_ready() is None
    worker.recover_startup()
    assert worker.store.get('sessions',job['session_id'])['state']=='interrupted'
    assert json.loads((root/'status.json').read_text())['state']=='interrupted'
    assert budget.state()['settled_usd_micro']==0


def test_three_real_handoffs_maximum_and_best_previous_render_retained(tmp_path,monkeypatch):
    import hdrp_agent.reference_worker as module
    worker,root,budget=engine(tmp_path);analysis,plan=proposals()
    variants=[dict(json.loads(canonical(plan)),exposure_ev=i*.1) for i in range(3)]
    fake=FakeProvider([analysis,'']+variants);fake.client=SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(module,'MetaResponses',lambda *args:fake)
    rendered=[];fitted=[]
    original_fit=module.fit_initial_positions
    def fit(*args):fitted.append(1);return original_fit(*args)
    monkeypatch.setattr(module,'fit_initial_positions',fit)
    def render(job,ordinal):
        rendered.append(ordinal);command=json.loads((root/f'plan-{ordinal}.json').read_text());assert command['ordinal']==ordinal
        directory=root/f'offline-render-{ordinal}';directory.mkdir();Image.new('RGB',(1280,720),((100,130,70)[ordinal],)*3).save(directory/'frame.png')
        native=dict(ordinal=ordinal,capture_directory=str(directory),scene_path=f"Assets/AgentWorkspace/Runs/repro-{job['id']}-{ordinal}/Reconstruction.unity",version=f'fixture-version-{ordinal}',applied_plan=command['plan'],contacts=dict(passed=True,checks=[]))
        return native,dict(directory=directory,statics=[dict(camera_key='reference-0',file='frame.png')],result=dict(performance={}))
    worker.wait_render=render;worker.run(root/'bundle.json')
    status=json.loads((root/'status.json').read_text());report=json.loads((root/'report.json').read_text())
    assert rendered==[0,1,2] and status['best_ordinal']==1
    assert fitted==[1], 'Image-centre initialization must not overwrite later corrections'
    assert status['fidelity_verified'] is False and report['fidelity_verified'] is False
    assert worker.store.get('sessions',report['job']['session_id'])['attempts_used']==3
    assert not (root/'plan-3.json').exists() and worker.next_ready() is None
    assert budget.state()['settled_usd_micro']==0
    assert 'Reference' in (root/'comparison.html').read_text()


@pytest.mark.parametrize('fidelity_mode',[None,'1.0'])
def test_unknown_provider_outcome_stops_before_construction_without_retry(tmp_path,monkeypatch,fidelity_mode):
    import hdrp_agent.reference_worker as module
    worker,root,budget=engine(tmp_path);calls=[]
    if fidelity_mode:
        path=root/'bundle.json';bundle=json.loads(path.read_text());bundle['fidelity_mode']=fidelity_mode;path.write_text(canonical(bundle))
    def send(*args):calls.append(1);raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Unknown financial outcome; reservation retained')
    provider=SimpleNamespace(send=send,client=SimpleNamespace(close=lambda:None))
    monkeypatch.setattr(module,'MetaResponses',lambda *args:provider)
    worker.run(root/'bundle.json')
    assert len(calls)==1 and not (root/'plan-0.json').exists()
    assert json.loads((root/'status.json').read_text())['state']=='interrupted'
    assert worker.next_ready() is None


def test_missing_candidate_frame_cannot_get_a_similarity_score(tmp_path):
    worker,root,budget=engine(tmp_path);analysis,plan=proposals()
    with pytest.raises(AgentError):score_pairs(worker.artifacts,[dict(key='reference-0')],[],analysis)


def test_detail_report_keeps_object_link_and_selected_preview(tmp_path):
    worker,root,budget=engine(tmp_path);job=worker.claim(root/'bundle.json');analysis,_=proposals()
    digest=worker.artifacts.put((root/'input.png').read_bytes(),'image/png')
    job.update(detail_frames=[dict(key='detail-000',object_key='chair',artifact_hash=digest,angle='front',acquisition='native_camera_closeup')],effective_analysis=analysis)
    Image.new('RGB',(1280,640),'white').save(root/'preview.png')
    (root/'preview-result.json').write_text(canonical([dict(asset_id='asset-chair',file='preview.png')]))
    worker.export(job)
    html=(root/'details.html').read_text()
    assert '<h2>chair</h2>' in html and 'front' in html and 'Retained variant: Chair' in html
    assert 'details.html' in (root/'comparison.html').read_text()
    assert json.loads((root/'report.json').read_text())['fidelity_verified'] is False


def test_reused_closeups_require_same_preserved_source_and_verified_analysis(tmp_path,monkeypatch):
    import hdrp_agent.reference_worker as module
    worker,root,budget=engine(tmp_path);job=worker.claim(root/'bundle.json');analysis,_=proposals()
    checkpoint='b'*32;previous=worker.root/checkpoint;previous.mkdir()
    job['bundle'].update(detail_checkpoint_job_id=checkpoint,analysis_checkpoint_job_id=checkpoint)
    job['analysis_reused_from']=checkpoint
    capture=worker.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures/capture-source';capture.mkdir(parents=True)
    (previous/'source-private.json').write_text(canonical(dict(source_scene_sha256='original-source')))
    (root/'source-private.json').write_text(canonical(dict(source_scene_sha256='different-source')))
    (previous/'bundle.json').write_text(canonical(dict(capture_directory=str(capture))))
    (previous/'detail-result.json').write_text(canonical(dict(captures=[],limits=[])))
    monkeypatch.setattr(module,'read_capture',lambda root:dict(request=dict(version_id='source-v1')))
    seen=[]
    def verify(*args):seen.append(args[3]);return [dict(key='detail-000',object_key='chair',acquisition='native_camera_closeup')]
    monkeypatch.setattr(module,'native_details',verify)
    with pytest.raises(AgentError):worker.acquire_details(job,analysis,[])
    assert seen==[]
    (root/'source-private.json').write_text(canonical(dict(source_scene_sha256='original-source')))
    assert worker.acquire_details(job,analysis,[])[0]['object_key']=='chair'
    assert seen==['source-v1'] and job['details_reused_from']==checkpoint and budget.state()['settled_usd_micro']==0


def test_preconstruction_continuation_reuses_exact_paid_analysis_without_transmission(tmp_path):
    import hashlib,httpx
    from hdrp_agent.providers.meta_responses import MetaResponses,spark_request
    from hdrp_agent.reference_media import ingest
    worker,root,budget=engine(tmp_path);job=worker.claim(root/'bundle.json');analysis,plan=proposals();transmitted=[]
    envelope=dict(id='paid-analysis-fixture',status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(analysis))])],usage=dict(input_tokens=100,output_tokens=20,input_tokens_details=dict(cached_tokens=0)))
    def transport(request):transmitted.append(1);return httpx.Response(200,json=envelope)
    provider=MetaResponses(worker.settings,budget,worker.artifacts,client=httpx.Client(transport=httpx.MockTransport(transport)))
    job.update(frames=ingest(job['bundle'],root,worker.artifacts),catalogue_sha256=hashlib.sha256((root/'catalogue.json').read_bytes()).hexdigest(),analysis_response=provider.send(spark_request('Offline transport fixture',[],'ModelReferenceAnalysis'),'ModelReferenceAnalysis'),state='interrupted')
    worker.save(job)
    with worker.store.tx() as c:worker.store.update_session(c,job['session_id'],state='interrupted',verdict='inconclusive')
    (root/'resume-request.json').write_text(canonical(dict(cached_sam_only=True,new_layout_only=True)))
    resumed=worker.resume_claim(root/'bundle.json')
    assert resumed['resume_count']==1 and len(transmitted)==1
    assert resumed['analysis_response']==job['analysis_response'] and budget.state()['settled_usd_micro']==14
    with pytest.raises(AgentError):worker.resume_claim(root/'bundle.json')


def test_construction_receipt_prevents_checkpoint_replay(tmp_path):
    worker,root,budget=engine(tmp_path);job=worker.claim(root/'bundle.json');job['state']='interrupted';worker.save(job)
    with worker.store.tx() as c:worker.store.update_session(c,job['session_id'],state='interrupted',verdict='inconclusive')
    (root/'resume-request.json').write_text(canonical(dict(cached_sam_only=True,new_layout_only=True)));(root/'receipt-0.json').write_text('{"status":"started"}')
    with pytest.raises(AgentError):worker.resume_claim(root/'bundle.json')
    assert worker.store.get('sessions',job['session_id'])['state']=='interrupted'


def test_physical_contacts_outrank_better_pixel_score():
    from hdrp_agent.reference_worker import candidate_rank
    floating=dict(metrics=dict(score=.01,contacts=dict(passed=False,checks=[dict(status='unresolved')])))
    grounded=dict(metrics=dict(score=.2,contacts=dict(passed=True,checks=[dict(status='contact')])))
    assert candidate_rank(grounded)<candidate_rank(floating)


def test_native_receipt_cannot_hide_pose_changes_or_missing_contacts():
    from copy import deepcopy
    from hdrp_agent.reference_worker import validate_native_placement
    analysis,plan=proposals();frames=[dict(key='reference-0',calibration=None)];catalogue=[dict(asset_id='asset-chair',name='Chair',bounds_center_m=[0,.5,0],bounds_size_m=[1,1,1])]
    native=dict(applied_plan=deepcopy(plan),contacts=dict(passed=True,checks=[]))
    assert validate_native_placement(native,plan,analysis,frames,catalogue)==plan
    native['applied_plan']['objects'][0]['position_m'][0]=.1
    with pytest.raises(AgentError,match='differs'):validate_native_placement(native,plan,analysis,frames,catalogue)
    native['applied_plan']=deepcopy(plan);del native['contacts']
    with pytest.raises(AgentError,match='required'):validate_native_placement(native,plan,analysis,frames,catalogue)


def test_six_autonomous_candidates_continue_after_rejection_and_remember_best(tmp_path,monkeypatch):
    import hdrp_agent.reference_worker as module
    worker,root,budget=engine(tmp_path);analysis,plan=proposals()
    bundle=json.loads((root/'bundle.json').read_text());bundle.update(max_iterations=6,session_timeout_seconds=2400,autonomous_refinement=True);(root/'bundle.json').write_text(canonical(bundle))
    variants=[dict(json.loads(canonical(plan)),exposure_ev=i*.1) for i in range(6)]
    fake=FakeProvider([analysis,'']+variants);fake.client=SimpleNamespace(close=lambda:None);monkeypatch.setattr(module,'MetaResponses',lambda *args:fake)
    def render(job,ordinal):
        command=json.loads((root/f'plan-{ordinal}.json').read_text());directory=root/f'render-{ordinal}';directory.mkdir();Image.new('RGB',(1280,720),((130,100,135,137,110,138)[ordinal],)*3).save(directory/'frame.png')
        return dict(ordinal=ordinal,scene_path=f"Assets/AgentWorkspace/Runs/repro-{job['id']}-{ordinal}/Reconstruction.unity",version=f'v-{ordinal}',applied_plan=command['plan'],contacts=dict(passed=True,checks=[])),dict(directory=directory,statics=[dict(camera_key='reference-0',file='frame.png')],result=dict(performance={}))
    worker.wait_render=render;worker.run(root/'bundle.json');report=json.loads((root/'report.json').read_text());job=report['job']
    assert len(job['attempts'])==6 and job['best_ordinal']==5
    assert [a['retained'] for a in job['attempts']]==[True,False,True,True,False,True]
    assert len(job['memory']['history'])==6 and not job['memory']['exact_reconstruction_verified']
    calls=[call for call in fake.calls if call.get('schema_name')=='ModelReconstructionPlan']
    # Inspect the actual provider request history, independent of fake metadata.
    layouts=[call['request'] for call in fake.calls if 'previous_plan' in str(call['request'])]
    third=json.loads(layouts[2]['input'][0]['content'][0]['text'].split('Untrusted observations:\n')[1])
    assert third['previous_metrics']['score']==job['attempts'][0]['metrics']['score']
    assert third['correction_memory']['history'][-1]['accepted'] is False
    assert not (root/'plan-6.json').exists()


def test_continuation_uses_settled_asset_matches_without_new_requests(tmp_path):
    from copy import deepcopy
    import httpx
    from hdrp_agent.providers.meta_responses import MetaResponses,spark_request
    worker,root,budget=engine(tmp_path);job=worker.claim(root/'bundle.json');analysis,_=proposals();other=deepcopy(analysis['objects'][0]);other['key']='other-chair';analysis['objects'].append(other)
    value=dict(matches=[dict(object_key='chair',asset_id='asset-chair')],limits=[])
    envelope=dict(id='settled-match',status='completed',output=[dict(type='message',content=[dict(type='output_text',text=json.dumps(value))])],usage=dict(input_tokens=100,output_tokens=20,input_tokens_details=dict(cached_tokens=0)))
    sent=[]
    def transport(request):sent.append(1);return httpx.Response(200,json=envelope)
    provider=MetaResponses(worker.settings,budget,worker.artifacts,client=httpx.Client(transport=httpx.MockTransport(transport)))
    response=provider.send(spark_request('Fixture asset selection',[],'ModelReferenceAssetSelection'),'ModelReferenceAssetSelection')
    job.update(resume_count=1,object_asset_matches=[response]);frames=[dict(key='reference-0')];catalogue=[dict(asset_id='asset-chair')]
    effective=worker.visual_asset_match(job,analysis,frames,catalogue,None,[])
    assert effective==analysis and len(sent)==1 and job['provisional_asset_keys']==['other-chair']
    assert job['asset_match_response']['mode']=='settled_checkpoint_only'
    with worker.store.tx() as c:c.execute("UPDATE calls SET status='unknown' WHERE id=?",(response['call_id'],))
    with pytest.raises(AgentError):worker.visual_asset_match(job,analysis,frames,catalogue,None,[])
    assert len(sent)==1


def test_external_duplicate_plan_stops_before_a_second_native_render(tmp_path,monkeypatch):
    import hdrp_agent.reference_worker as module
    worker,root,_=engine(tmp_path);analysis,plan=proposals()
    fake=FakeProvider([analysis,'',plan,plan]);fake.client=SimpleNamespace(close=lambda:None)
    monkeypatch.setattr(module,'MetaResponses',lambda *args:fake)
    rendered=[]
    def render(job,ordinal):
        rendered.append(ordinal);command=json.loads((root/f'plan-{ordinal}.json').read_text())
        directory=root/f'render-{ordinal}';directory.mkdir();Image.new('RGB',(1280,720),(130,)*3).save(directory/'frame.png')
        native=dict(ordinal=ordinal,scene_path=f"Assets/AgentWorkspace/Runs/repro-{job['id']}-{ordinal}/Reconstruction.unity",version=f'v-{ordinal}',applied_plan=command['plan'],contacts=dict(passed=True,checks=[]))
        return native,dict(directory=directory,statics=[dict(camera_key='reference-0',file='frame.png')],result=dict(performance={}))
    worker.wait_render=render;worker.run(root/'bundle.json')
    job=json.loads((root/'report.json').read_text())['job']
    assert rendered==[0] and not (root/'plan-1.json').exists()
    assert job['decisions'][-1]['reason']=='duplicate_experiment_without_new_evidence'
