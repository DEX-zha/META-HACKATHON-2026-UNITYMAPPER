"""One request must cover successive defects without intermediate human guidance."""
from copy import deepcopy
from types import SimpleNamespace
import io,json

from PIL import Image
import pytest

from hdrp_agent.planner import Planner
from hdrp_agent.domain import canonical,WORKSPACE
from hdrp_agent.config import Settings
from hdrp_agent.store import Store
from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.command_queue import CommandQueue
from hdrp_agent.orchestrator import Orchestrator


def scenario(tmp_path,monkeypatch,*,persistent=False,reject=None,unknown_performance=False,max_attempts=3,partial_goal=False,needs_diagnostics=False,unresolved_diagnostics=False):
    import hdrp_agent.orchestrator as module
    settings=Settings(tmp_path,token='fixture');store=Store(settings.db_path);artifacts=ArtifactStore(settings.state/'artifacts',store)
    with store.tx() as c:
        registration=dict(scene_version='v0',capabilities=['inspect','snapshot','apply_patch','restore','bake','capture'])
        c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical(registration)))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('scene','project',canonical(registration)))
    runner=Orchestrator(settings,store,CommandQueue(store),artifacts)
    criteria=[dict(id='performance',kind='performance',target='performance',method='frame_time_regression',minimum=None,maximum=.2,unit='ratio',required=True),dict(id='ambiance',kind='artistic',target='ambiance',method='artistic_review',minimum=None,maximum=None,unit='human',required=True)]
    if partial_goal:criteria.append(dict(id='target',kind='geometry',target='work-front',method='support_gap',minimum=0,maximum=.01,unit='m',required=True))
    request=dict(project_id='project',scene_id='scene',base_version='v0',mode='inspect',brief=dict(json.loads((WORKSPACE/'fixtures/briefs/room.json').read_text()),mutation_scope_id='owned'),inspection=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text()),criteria=criteria,max_attempts=max_attempts,session_timeout_seconds=1200,bake_timeout_seconds=600,provider_mode='offline')
    sid=runner.create(request,'one-request')['id'];state=dict(version='v0',patch_count=0);snapshots={};commands=[];contexts=[]
    out=io.BytesIO();Image.new('RGB',(32,24),(100,100,100)).save(out,format='PNG');digest=artifacts.put(out.getvalue(),'image/png')
    def scene():return dict(version=state['version'],scope_id='owned',objects=[dict(logical_key='fog',name='Environment',volume={'fog':{'mean_free_path_m':1 if state['version']=='v0' else 10}}),dict(logical_key='wall',name='Generic surface',renderer={},mesh={'uv_repair_supported':True})],oracle='PRIVATE_REFERENCE')
    def packet():
        captures=[dict(artifact_hash=digest,version_id=state['version'],inspection_hash=store.get('sessions',sid)['inspection_hash'],conditions_hash='c'*64,role=role,camera_key=key,frame_index=0,simulated_time=0,render_ready=True,provenance='offline') for role,keys in [('work',['front','left','right']),('control',['private-corner','private-low'])] for key in keys]
        return dict(version=state['version'],inspection_hash=store.get('sessions',sid)['inspection_hash'],conditions_hash='c'*64,captures=captures,comparable=True,capture_details_hash='d'*64,manifest_hash='a'*64,witness_errors={},geometry={},performance={})
    def command(session,kind,body,**kwargs):
        commands.append(dict(kind=kind,before=state['version'],body=body))
        snapshot_id=None
        if kind=='snapshot':snapshot_id='snapshot-'+str(len(snapshots));snapshots[snapshot_id]=state['version']
        if kind=='apply_patch':state['patch_count']+=1;state['version']='v'+str(state['patch_count'])
        if kind=='restore':state['version']=snapshots[body['snapshot_id']]
        runner._update(sid,current_version=state['version']);data=runner.run_data(sid);data['last_manifest']='a'*64;runner.save_run(sid,data)
        return dict(kind=kind,after_version=state['version'],snapshot_id=snapshot_id,manifest_hash='a'*64)
    runner.command=command;runner.details=lambda result:scene();runner.capture=lambda *args,**kwargs:packet();runner.witness=lambda a,b:a;runner.bake=lambda sid:None
    runner._provider=lambda sid:SimpleNamespace(mode='offline')
    class TestPlanner(Planner):
        def _call(self,instruction,context,name):
            contexts.append(deepcopy(context));version=context['scene_version'];ids=[item['id'] for item in context['work_captures']]
            if name=='ModelDiagnosis':
                remaining=persistent or version not in {'v2','v3'}
                target='fog' if version=='v0' else 'wall'
                evidence=dict(capture_id=ids[0],frame_index=0,bbox_xyxy=None,target_ids=[target],description='Visible technical defect')
                value=dict(scene_version=version,inspected_capture_ids=ids,observations=[dict(key='obs',category='lighting',claim='Residual defect',evidence=[evidence])] if remaining else [],hypotheses=[dict(key='hyp-'+target,observation_keys=['obs'],target_ids=[target],cause='Density or baked surface defect',evidence=[evidence],uncertainty='Requires rendered experiment',missing_information=[])] if remaining else [],unsupported_limits=[])
                if needs_diagnostics and remaining and (unresolved_diagnostics or 'diagnostic_followup' not in context):
                    value['hypotheses'][0]['missing_information']=['Allowed parameter range and measured renderer facts']
            else:
                target='fog' if version=='v0' else 'wall'
                op=dict(op='set_fog',target_id='fog',property='mean_free_path_m',value=10) if target=='fog' else dict(op='set_gi',target_id='wall',property='lightmap_uv_pack_margin',value=.03125)
                value=dict(scene_version=version,hypothesis_key='hyp-'+target,expected_effect='Resolve technical defect',operations=[op],needs_bake=True)
            return dict(value=value,provider_mode='offline')
    monkeypatch.setattr(module,'Planner',TestPlanner)
    def evaluate(frozen,before,after,**kwargs):
        bad=after['version']==reject
        results={'performance':dict(value=None if unknown_performance else .01,passed=None if unknown_performance else not bad,reason='Unqualified' if unknown_performance else 'Regression' if bad else None),'ambiance':dict(value=None,passed=None,reason='Independent human review is missing')}
        incomplete=partial_goal and after['version']=='v1'
        if partial_goal:results['target']=dict(value=.1 if incomplete else .5,passed=not incomplete,reason=None)
        return dict(verdict='rejected' if bad or incomplete else 'inconclusive',per_criterion=results,issues=[],target_progress={'target':True} if partial_goal else {})
    runner.evaluator.evaluate=evaluate
    return runner,sid,state,commands,contexts


def test_one_request_chains_two_defects_and_audits_the_final_scene(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch)
    runner.run(sid);data=runner.run_data(sid);session=runner.store.get('sessions',sid)
    assert session['attempts_used']==2
    assert [context['scene_version'] for context in contexts if 'selected_hypothesis_key' not in context]==['v0','v1','v2']
    assert data['provisional_candidate']['after']['version']=='v2'
    assert data['final_audit']['value']['hypotheses']==[]
    assert session['verdict']=='inconclusive' and session['state']=='completed'
    assert state['version']=='v0' and session['best_version']=='v0'  # no invented human approval
    assert all('audit' in attempt for attempt in data['attempts'])
    encoded=canonical(contexts)
    for forbidden in ['private-corner','private-low','PRIVATE_REFERENCE']:assert forbidden not in encoded
    with runner.store.tx() as c:assert c.execute("SELECT count(*) FROM events WHERE subject=? AND kind='final_candidate_ready'",(sid,)).fetchone()[0]==1


def test_remaining_defects_stop_at_three_with_one_final_partial_report(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,persistent=True)
    runner.run(sid);session=runner.store.get('sessions',sid);data=runner.run_data(sid)
    assert session['attempts_used']==3 and state['patch_count']==3
    assert session['state']=='limit_reached' and session['verdict']=='inconclusive'
    assert data['final_audit']['value']['hypotheses']
    assert data['provisional_candidate']['after']['version']=='v3' and state['version']=='v0'


def test_rejected_hypothesis_is_not_retried_on_the_same_restored_version(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,reject='v1')
    runner.run(sid)
    assert state['patch_count']==1
    assert runner.store.get('sessions',sid)['attempts_used']==1
    assert 'already attempted' in runner.store.get('sessions',sid)['stop_reason']


def test_renaming_a_hypothesis_does_not_replay_an_identical_rejected_patch(tmp_path,monkeypatch):
    import hdrp_agent.orchestrator as module
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,reject='v1')
    original=module.Planner._call;serial=[0]
    def renamed(self,instruction,context,name):
        result=original(self,instruction,context,name)
        if name=='ModelDiagnosis' and result['value']['hypotheses']:
            serial[0]+=1;result['value']['hypotheses'][0]['key']='renamed-'+str(serial[0])
        if name=='ModelProposal':result['value']['hypothesis_key']=context['selected_hypothesis_key']
        return result
    monkeypatch.setattr(module.Planner,'_call',renamed)
    runner.run(sid)
    assert state['patch_count']==1 and runner.store.get('sessions',sid)['attempts_used']==1
    assert 'no replay' in runner.store.get('sessions',sid)['stop_reason']
    with runner.store.tx() as c:assert c.execute("SELECT 1 FROM events WHERE subject=? AND kind='proposal_refused_duplicate'",(sid,)).fetchone()


def test_missing_information_gets_one_fresh_read_without_human_guidance(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,needs_diagnostics=True)
    runner.run(sid)
    assert state['patch_count']==2
    followups=[context for context in contexts if 'diagnostic_followup' in context and 'selected_hypothesis_key' not in context]
    assert len(followups)==2
    assert all(context['diagnostic_followup']['requested_information'] for context in followups)
    assert all(context['diagnostic_followup']['verified_scene_version']==context['scene_version'] for context in followups)


def test_unavailable_diagnostics_stop_after_one_followup_per_version(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,needs_diagnostics=True,unresolved_diagnostics=True)
    runner.run(sid)
    assert state['patch_count']==0
    assert len(contexts)==2
    assert runner.store.get('sessions',sid)['state']=='completed'


def test_focus_loss_gets_one_new_measured_capture_and_keeps_original_evidence(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch)
    packet=runner.capture(sid);calls=[]
    runner.capture=Orchestrator.capture.__get__(runner)
    runner.focus_editor=lambda session:calls.append('focus')
    def once(session,cleanup=False):
        count=calls.count('capture');calls.append('capture')
        return dict(deepcopy(packet),capture_details_hash=str(count)*64,performance=dict(focused=count>0,focus_stable=count>0))
    runner._capture_once=once
    result=runner.capture(sid)
    assert result['performance']['focused'] is True
    assert calls==['focus','capture','focus','capture']
    with runner.store.tx() as c:
        original=c.execute("SELECT body FROM events WHERE subject=? AND kind='capture_focus_unqualified'",(sid,)).fetchone()
    assert json.loads(original[0])['capture_details_hash']=='0'*64


def test_focus_requalification_never_loops_or_hides_a_second_failed_measurement(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch)
    packet=runner.capture(sid);calls=[]
    runner.capture=Orchestrator.capture.__get__(runner);runner.focus_editor=lambda session:None
    def once(session,cleanup=False):
        calls.append('capture');return dict(deepcopy(packet),performance=dict(focused=False,focus_stable=False))
    runner._capture_once=once
    assert runner.capture(sid)['performance']['focused'] is False
    assert len(calls)==2
    assert runner.capture(sid)['performance']['focused'] is False
    assert len(calls)==3  # At most one extra capture for this version.


def test_activation_targets_the_registered_editor_pid_and_checks_process_name(tmp_path,monkeypatch):
    import hdrp_agent.orchestrator as module
    runner,sid,*_=scenario(tmp_path,monkeypatch)
    actual_run=module.subprocess.run;actual_platform=module.sys.platform
    monkeypatch.setattr(module.sys,'platform','darwin');sent=[]
    monkeypatch.setattr(module.subprocess,'run',lambda args,**kwargs:sent.append(args) or SimpleNamespace(returncode=0))
    (runner.settings.state/'unity-editor.pid').write_text('12345')
    runner.focus_editor(sid)
    assert len(sent)==1 and sent[0][:2]==['/usr/bin/osascript','-e']
    assert 'unix id is 12345' in sent[0][2] and 'name is not "Unity"' in sent[0][2]
    if actual_platform=='darwin':
        compiled=actual_run(['/usr/bin/osacompile','-o',str(tmp_path/'focus.scpt'),'-'],input=sent[0][2],text=True,capture_output=True,timeout=10)
        assert compiled.returncode==0,compiled.stderr


def test_invalid_or_absent_editor_identity_never_activates_an_ambiguous_unity_process(tmp_path,monkeypatch):
    import hdrp_agent.orchestrator as module
    runner,sid,*_=scenario(tmp_path,monkeypatch)
    monkeypatch.setattr(module.sys,'platform','darwin')
    monkeypatch.setattr(module.subprocess,'run',lambda *args,**kwargs:pytest.fail('No OS activation without a valid editor identity'))
    runner.focus_editor(sid)
    for invalid in ['0','2147483648','123\nerror "injection"','１２３']:
        (runner.settings.state/'unity-editor.pid').write_text(invalid);runner.focus_editor(sid)


def test_focus_ownership_is_maintained_only_until_capture_finishes(tmp_path,monkeypatch):
    import threading,time
    import hdrp_agent.orchestrator as module
    runner,sid,*_=scenario(tmp_path,monkeypatch);calls=[];renewed=threading.Event()
    monkeypatch.setattr(module,'FOCUS_WATCH_INTERVAL_SECONDS',.01)
    def focus(session):
        calls.append(1)
        if len(calls)>=2:renewed.set()
        return True
    runner.focus_editor=focus
    def capture(session,cleanup=False):
        assert renewed.wait(1)
        return {'actual_capture':'fixture'}
    runner._capture_once=capture
    assert runner._capture_with_focus(sid)=={'actual_capture':'fixture'}
    finished=len(calls);time.sleep(.04)
    assert len(calls)==finished and finished>=2


def test_capture_failure_releases_focus_ownership(tmp_path,monkeypatch):
    import time
    import hdrp_agent.orchestrator as module
    runner,sid,*_=scenario(tmp_path,monkeypatch);calls=[]
    monkeypatch.setattr(module,'FOCUS_WATCH_INTERVAL_SECONDS',.01)
    runner.focus_editor=lambda session:calls.append(1) or True
    def fail(session,cleanup=False):raise RuntimeError('Native capture failed')
    runner._capture_once=fail
    with pytest.raises(RuntimeError):runner._capture_with_focus(sid)
    finished=len(calls);time.sleep(.04)
    assert len(calls)==finished


def test_rejected_later_patch_preserves_the_earlier_provisional_candidate(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,reject='v2',max_attempts=2)
    runner.run(sid);data=runner.run_data(sid)
    assert data['provisional_candidate']['after']['version']=='v1'
    assert any(command['kind']=='restore' and command['before']=='v2' for command in commands)
    assert state['version']=='v0'
    from hdrp_agent.reporting import build,comparison_html
    report=build(runner.store,runner.artifacts,sid)
    body=json.loads(runner.artifacts.read(report['report_artifact_hash']))
    assert body['automatic_pass']['candidate_version']=='v1'
    assert body['automatic_pass']['human_review_required'] is True
    assert any('Residual defect' in item for item in body['unresolved'])
    assert 'Candidate v1' in comparison_html(runner.store,runner.artifacts,sid)


def test_unknown_technical_evidence_stops_without_chaining_candidates(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,unknown_performance=True)
    runner.run(sid)
    assert runner.store.get('sessions',sid)['attempts_used']==1
    assert runner.run_data(sid).get('provisional_candidate') is None
    assert state['version']=='v0'


def test_failed_objective_does_not_hide_missing_required_performance(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,unknown_performance=True,reject='v1')
    runner.run(sid)
    assert runner.store.get('sessions',sid)['attempts_used']==1
    assert state['version']=='v0'


def test_partial_objective_progress_can_continue_without_relaxing_final_criteria(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch,partial_goal=True)
    runner.run(sid);data=runner.run_data(sid)
    assert runner.store.get('sessions',sid)['attempts_used']==2
    assert data['attempts'][0]['evaluation']['per_criterion']['target']['passed'] is False
    assert data['provisional_candidate']['after']['version']=='v2'
    assert runner.store.get('sessions',sid)['verdict']=='inconclusive'


def test_global_context_includes_timestamped_clip_frames_and_hides_controls(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch)
    packet=runner.capture(sid)
    packet['planner_frames']=[dict(packet['captures'][0],camera_key='room-orbit',frame_index=index,simulated_time=index/24) for index in [0,48,96]]
    context=runner.planning_context(sid,Planner(None,runner.artifacts),dict(version='v0',objects=[]),packet)
    assert len(context['work_captures'])==6
    assert [frame['simulated_time'] for frame in context['work_captures'] if frame['camera_key']=='room-orbit']==[0,2,4]
    assert 'private-corner' not in canonical(context) and 'private-low' not in canonical(context)


def test_live_preflight_requires_qualified_baseline_before_any_model_call(tmp_path,monkeypatch):
    runner,sid,state,commands,contexts=scenario(tmp_path,monkeypatch)
    data=runner.run_data(sid);data['request']['provider_mode']='live';runner.save_run(sid,data)
    runner.run(sid)
    assert contexts==[] and state['patch_count']==0
    assert runner.store.get('sessions',sid)['attempts_used']==0
    assert 'Baseline performance is unqualified' in runner.store.get('sessions',sid)['stop_reason']
