"""Failure injection exercises the real planner and durable loop, with no network."""
from contextlib import closing
import io
import json

import pytest
from PIL import Image

from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.command_queue import CommandQueue
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError,WORKSPACE,canonical
from hdrp_agent.orchestrator import Orchestrator
from hdrp_agent.planner import Planner
from hdrp_agent.providers.fake import FakeProvider
from hdrp_agent.store import Store


@pytest.fixture
def scenario(tmp_path):
    settings=Settings(tmp_path,token='fixture');store=Store(settings.db_path);artifacts=ArtifactStore(settings.state/'artifacts',store)
    with store.tx() as c:
        registration=dict(scene_version='before',capabilities=['inspect','snapshot','apply_patch','restore','bake','capture'])
        c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical(registration)))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('scene','project',canonical(registration)))
    runner=Orchestrator(settings,store,CommandQueue(store),artifacts)
    request=dict(project_id='project',scene_id='scene',base_version='before',mode='inspect',brief=dict(json.loads((WORKSPACE/'fixtures/briefs/room.json').read_text()),mutation_scope_id='owned'),inspection=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text()),criteria=[dict(id='performance',kind='performance',target='performance',method='frame_time_regression',minimum=None,maximum=.2,unit='ratio',required=True)],max_attempts=3,session_timeout_seconds=1200,bake_timeout_seconds=600,provider_mode='offline')
    sid=runner.create(request,'create')['id'];version=['before'];commands=[]
    scene=dict(version='before',scope_id='owned',objects=[dict(logical_key='fog',name='Environment',volume=dict(fog=dict(mean_free_path_m=1)))])
    out=io.BytesIO();Image.new('RGB',(32,24),(100,100,100)).save(out,format='PNG');digest=artifacts.put(out.getvalue(),'image/png')
    def packet():
        session=store.get('sessions',sid)
        captures=[dict(artifact_hash=digest,version_id=version[0],inspection_hash=session['inspection_hash'],conditions_hash='b'*64,role=role,camera_key=key,frame_index=0,simulated_time=0,render_ready=True,provenance='offline') for role,keys in [('work',['front','left','right']),('control',['hidden-corner','hidden-low'])] for key in keys]
        return dict(version=version[0],captures=captures,inspection_hash=session['inspection_hash'],conditions_hash='b'*64,capture_details_hash='c'*64,witness_errors={},performance=dict(frame_count=120,median_frame_ms=10,method='editor_wall_frame_time_no_readback',capture_framerate_disabled=True,focused=True,focus_stable=True,v_sync_count=0,target_frame_rate=-1),geometry={},comparable=True)
    def command(sid,kind,body,**kwargs):
        commands.append(kind)
        if kind=='apply_patch':version[0]='after'
        if kind=='restore':version[0]='before'
        runner._update(sid,current_version=version[0]);data=runner.run_data(sid);data['last_manifest']='d'*64;runner.save_run(sid,data)
        return dict(after_version=version[0],snapshot_id='snapshot-'+str(len(commands)),kind=kind,manifest_hash='d'*64)
    runner.command=command;runner.details=lambda result:dict(scene,version=version[0]);runner.bake=lambda sid:None
    runner.capture=lambda sid,**kwargs:packet();runner.witness=lambda a,b:a
    context=Planner(None,artifacts).context(request['brief'],request['criteria'],scene,packet()['captures'])
    evidence=dict(capture_id=context['work_captures'][0]['id'],frame_index=0,bbox_xyxy=None,target_ids=['fog'],description='Room is obscured')
    diagnosis=dict(scene_version='before',inspected_capture_ids=[x['id'] for x in context['work_captures']],observations=[dict(key='obs',category='lighting',claim='Visibility low',evidence=[evidence])],hypotheses=[dict(key='hyp',observation_keys=['obs'],target_ids=['fog'],cause='Local fog may be too dense',evidence=[evidence],uncertainty='Need render comparison',missing_information=[])],unsupported_limits=[])
    proposal=dict(scene_version='before',hypothesis_key='hyp',expected_effect='Improve visibility while retaining fog',operations=[dict(op='set_fog',target_id='fog',property='mean_free_path_m',value=20)],needs_bake=False)
    return runner,sid,commands,diagnosis,proposal,version


def clear_after_audit(runner,sid,version):
    previous=version[0]
    try:
        version[0]='after';packet=runner.capture(sid)
        context=Planner(None,runner.artifacts).context({},[],dict(version='after',objects=[]),packet['captures'])
        return dict(scene_version='after',inspected_capture_ids=[item['id'] for item in context['work_captures']],observations=[],hypotheses=[],unsupported_limits=[])
    finally:version[0]=previous


def test_invalid_model_result_does_not_start_an_attempt(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    diagnosis['scene_version']='stale';provider=FakeProvider([diagnosis]);runner._provider=lambda sid:provider
    runner.run(sid)
    assert runner.store.get('sessions',sid)['attempts_used']==0
    assert 'apply_patch' not in commands
    assert runner.store.get('sessions',sid)['state']=='interrupted'
    # Held-out camera identities and pixels never enter the real serialized model request.
    assert 'hidden-corner' not in canonical(provider.calls)
    assert 'hidden-low' not in canonical(provider.calls)


def test_lost_mutation_receipt_stops_without_restore_or_replay(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    runner._provider=lambda sid:FakeProvider([diagnosis,proposal,clear_after_audit(runner,sid,version)]);original=runner.command
    def lost(sid,kind,body,**kwargs):
        if kind=='apply_patch':commands.append(kind);raise AgentError('RECOVERY_REQUIRED','Injected missing terminal mutation receipt')
        return original(sid,kind,body,**kwargs)
    runner.command=lost;runner.run(sid)
    state=runner.store.get('sessions',sid)
    assert state['attempts_used']==1 and state['state']=='recovery_required'
    assert commands.count('apply_patch')==1 and 'restore' not in commands
    runner.recover_startup()
    assert runner.next_created() is None
    assert runner.store.get('sessions',sid)['attempts_used']==1


def test_incomplete_bake_after_patch_restores_known_snapshot(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    runner._provider=lambda sid:FakeProvider([diagnosis,proposal,clear_after_audit(runner,sid,version)]);calls=[0]
    def bake(sid):
        calls[0]+=1
        if calls[0]>1:raise AgentError('BAKE_INCOMPLETE','Injected cancellation before completion callback')
    runner.bake=bake;runner.run(sid)
    state=runner.store.get('sessions',sid)
    assert state['attempts_used']==1
    assert commands.count('restore')==1 and version[0]=='before'
    assert state['state']=='interrupted' and state['verdict']=='inconclusive'


def test_provider_timeout_during_diagnosis_never_mutates(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    class Timeout:
        def send(self,*args,**kwargs):raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Sent call reservation remains unknown')
    runner._provider=lambda sid:Timeout();runner.run(sid)
    assert runner.store.get('sessions',sid)['attempts_used']==0
    assert 'apply_patch' not in commands
    assert runner.store.get('sessions',sid)['verdict']=='inconclusive'


def test_offline_model_and_fixture_metrics_cannot_claim_a_real_repair(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    runner._provider=lambda sid:FakeProvider([diagnosis,proposal,clear_after_audit(runner,sid,version)])
    runner.evaluator.evaluate=lambda *args,**kwargs:dict(verdict='improved',per_criterion={'fixture':dict(passed=True,reason=None)})
    runner.run(sid)
    state=runner.store.get('sessions',sid)
    assert state['state']=='completed' and state['verdict']=='inconclusive'
    assert state['best_version']=='before' and version[0]=='before'
    attempt=runner.run_data(sid)['attempts'][0]
    assert attempt['candidate_snapshot'].startswith('snapshot-')
    assert attempt['evaluation']['verdict']=='inconclusive'


def test_baseline_cache_requires_exact_version_manifest_renderer_and_live_media(scenario):
    runner,sid,commands,diagnosis,proposal,version=scenario
    data=runner.run_data(sid)
    out=io.BytesIO();Image.new('RGB',(32,24)).save(out,format='PNG');digest=runner.artifacts.put(out.getvalue(),'image/png')
    data['baseline']=dict(version='before',manifest_hash='a'*64,inspection_hash=runner.store.get('sessions',sid)['inspection_hash'],comparable=True,bake_verified=True,captures=[dict(artifact_hash=digest,version_id='before',provenance='live')],capture_details_hash=digest,witness_details_hash=digest,clip_artifact_hash=digest,capture_policy=runner.capture_policy())
    runner.save_run(sid,data);runner._update(sid,state='interrupted')
    second=runner.create(data['request'],'second')['id']
    assert runner.cached_baseline(second,'before','a'*64) is not None
    assert runner.cached_baseline(second,'other','a'*64) is None
    assert runner.cached_baseline(second,'before','b'*64) is None
    data.pop('capture_policy');runner.save_run(sid,data)
    assert runner.cached_baseline(second,'before','a'*64) is None
    data['capture_policy']=runner.capture_policy()
    data['baseline']['capture_policy']={'revision':'one-shot-activation'};runner.save_run(sid,data)
    assert runner.cached_baseline(second,'before','a'*64) is None
    data['baseline']['capture_policy']=runner.capture_policy()
    previous=runner.renderer_profile()
    from unittest.mock import patch
    with patch('hdrp_agent.orchestrator.FOCUS_WATCH_INTERVAL_SECONDS',2.0):
        assert runner.renderer_profile()!=previous
        assert runner.cached_baseline(second,'before','a'*64) is None
    data['render_sources_hash']='0'*64;runner.save_run(sid,data)
    assert runner.cached_baseline(second,'before','a'*64) is None
    data['render_sources_hash']=runner.renderer_profile();data['baseline']['captures'][0]['provenance']='offline';runner.save_run(sid,data)
    assert runner.cached_baseline(second,'before','a'*64) is None


def test_comparison_escapes_model_text_and_labels_offline_evidence(scenario):
    from hdrp_agent.reporting import comparison_html
    runner,sid,commands,diagnosis,proposal,version=scenario
    diagnosis['observations'][0]['claim']='<script>untrusted scene text</script>'
    runner._provider=lambda sid:FakeProvider([diagnosis,proposal,clear_after_audit(runner,sid,version)])
    runner.run(sid)
    html=comparison_html(runner.store,runner.artifacts,sid)
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert 'Offline or test media' in html
    assert 'hidden-corner' in html  # operator report includes controls; planner never does
    assert 'data:image/png;base64,' in html


def test_zero_patch_report_identifies_the_current_failure_without_old_candidate_images(scenario):
    from hdrp_agent.reporting import build,comparison_html
    runner,sid,commands,diagnosis,proposal,version=scenario
    runner._update(sid,state='interrupted',verdict='inconclusive',stop_reason='PROVIDER_OUTCOME_UNKNOWN <script>unsafe</script>')
    html=comparison_html(runner.store,runner.artifacts,sid)
    assert sid in html and 'No candidate to compare' in html and 'PROVIDER_OUTCOME_UNKNOWN' in html
    assert '<img' not in html and 'data:image/png' not in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    report=build(runner.store,runner.artifacts,sid)
    body=json.loads(runner.artifacts.read(report['report_artifact_hash']))
    assert body['automatic_pass']['human_review_required'] is False


def test_pending_artistic_feedback_is_visible_without_approving_a_candidate(scenario):
    from hdrp_agent.reporting import build,comparison_html
    runner,sid,commands,diagnosis,proposal,version=scenario
    runner._provider=lambda sid:FakeProvider([diagnosis,proposal,clear_after_audit(runner,sid,version)]);runner.run(sid)
    feedback=dict(status='artistic_review_pending',decision=None,notes='Corner leak <script>untrusted</script>',affected_views=['front'])
    with runner.store.tx() as c:runner.store.event(c,sid,'operator_artistic_feedback',feedback)
    report=build(runner.store,runner.artifacts,sid)
    data=json.loads(runner.artifacts.read(report['report_artifact_hash']))
    assert data['human_feedback'][0]['body']==feedback
    assert data['repair_validated'] is False
    assert any('Corner leak' in item for item in data['unresolved'])
    html=comparison_html(runner.store,runner.artifacts,sid)
    assert 'Pending artistic review' in html and 'Corner leak' in html
    assert '<script>' not in html and '&lt;script&gt;' in html
    assert runner.store.get('sessions',sid)['verdict']=='inconclusive'
