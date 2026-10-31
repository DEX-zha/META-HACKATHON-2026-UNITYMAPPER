"""Durability and limits are checked without spending API credits."""
import json
from datetime import datetime,timedelta,timezone

import pytest
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError,canonical,payload
from hdrp_agent.store import Store


def engine(tmp_path):
    from hdrp_agent.orchestrator import Orchestrator
    from hdrp_agent.artifacts import ArtifactStore
    from hdrp_agent.command_queue import CommandQueue
    settings=Settings(tmp_path,token='test');store=Store(settings.db_path)
    with store.tx() as c:
        c.execute('INSERT INTO projects VALUES(?,?,?)',('p','epoch',canonical(dict(scene_version='v',capabilities=['inspect','snapshot','apply_patch','restore','bake','capture']))))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('s','p',canonical(dict(scene_version='v'))))
    return Orchestrator(settings,store,CommandQueue(store),ArtifactStore(settings.state/'artifacts',store))


def request():
    from hdrp_agent.domain import WORKSPACE
    return dict(project_id='p',scene_id='s',base_version='v',mode='inspect',brief=json.loads((WORKSPACE/'fixtures/briefs/room.json').read_text()),inspection=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text()),criteria=[dict(id='performance',kind='performance',target='performance',method='frame_time_regression',minimum=None,maximum=.2,unit='ratio',required=True)],max_attempts=3,session_timeout_seconds=1200,bake_timeout_seconds=600,provider_mode='offline')


def test_create_is_atomic_freezes_and_enforces_single_session(tmp_path):
    runner=engine(tmp_path);req=request();first=runner.create(req,'create')
    assert runner.create(req,'create')==first
    req['criteria'][0]['maximum']=.9
    assert runner.run_data(first['id'])['request']['criteria'][0]['maximum']==.2
    with pytest.raises(AgentError) as exc:runner.create(req,'other')
    assert exc.value.code=='SESSION_ACTIVE'


def test_attempt_is_consumed_before_snapshot_and_fourth_refused_after_restart(tmp_path):
    runner=engine(tmp_path);session=runner.create(request(),'create');sid=session['id']
    for ordinal in range(1,4):
        patch={'id':f'patch-{ordinal}','expected_version':'v'}
        assert runner.accept_attempt(sid,patch)==ordinal
    runner=engine_reload(runner)
    assert runner.store.get('sessions',sid)['attempts_used']==3
    with pytest.raises(AgentError) as exc:runner.accept_attempt(sid,{'id':'patch-4','expected_version':'v'})
    assert exc.value.code=='ATTEMPT_LIMIT'


def engine_reload(runner):
    from hdrp_agent.orchestrator import Orchestrator
    return Orchestrator(runner.settings,runner.store,runner.queue,runner.artifacts)


def test_restart_never_resends_inference_or_mutation(tmp_path):
    runner=engine(tmp_path);session=runner.create(request(),'create');sid=session['id']
    with runner.store.tx() as c:runner.store.update_session(c,sid,state='diagnosing')
    runner.recover_startup()
    assert runner.store.get('sessions',sid)['state']=='interrupted'
    assert runner.next_created() is None


def test_stale_patch_and_elapsed_deadline_do_not_consume_attempt(tmp_path):
    runner=engine(tmp_path);sid=runner.create(request(),'create')['id']
    with pytest.raises(AgentError):runner.accept_attempt(sid,{'id':'patch','expected_version':'old'})
    assert runner.store.get('sessions',sid)['attempts_used']==0
    data=runner.run_data(sid);data['deadline_utc']=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat();runner.save_run(sid,data)
    with pytest.raises(AgentError) as exc:runner.accept_attempt(sid,{'id':'patch','expected_version':'v'})
    assert exc.value.code=='SESSION_DEADLINE'


def test_rejected_candidates_are_restored_and_all_three_ordinals_retained(tmp_path,monkeypatch):
    import hdrp_agent.orchestrator as module
    runner=engine(tmp_path);req=request();req['brief']['mutation_scope_id']='owned'
    req['criteria'].append(dict(id='control',kind='visibility',target='control-corner',method='luminance_range',minimum=.01,maximum=.9,unit='normalized',required=True))
    sid=runner.create(req,'create')['id'];commands=[];version=['v'];serial=[0]
    scene=dict(version='v',scope_id='owned',objects=[])
    def command(sid,kind,body,**kwargs):
        commands.append(kind)
        if kind=='apply_patch':version[0]='changed'
        if kind=='restore':version[0]='v'
        runner._update(sid,current_version=version[0])
        data=runner.run_data(sid);data['last_manifest']='a'*64;runner.save_run(sid,data)
        if kind=='snapshot':serial[0]+=1
        return dict(after_version=version[0],snapshot_id='snapshot-'+str(serial[0]),kind=kind,manifest_hash='a'*64)
    runner.command=command
    runner.details=lambda result:dict(scene,version=version[0])
    runner.capture=lambda sid,**kwargs:dict(version=version[0],captures=[],capture_details_hash='b'*64)
    runner.witness=lambda a,b:dict(a,witness_errors={})
    runner.bake=lambda sid:None
    runner._provider=lambda sid=None:object()
    class PlannerStub:
        def __init__(self,*args):pass
        def context(self,*args):return dict(objects=[])
        def diagnose(self,context):return dict(value=dict(hypotheses=[dict(key='hyp-'+str(serial[0]),target_ids=['light'],missing_information=[])]),provider_mode='offline')
        def propose(self,context,diagnosis,key,sid):return dict(patch=dict(id='patch-'+str(serial[0]),expected_version='v',hypothesis_id=key,operations=[dict(op='set_fog',target_id='light',property='mean_free_path_m',value=serial[0]+2)]),response=dict(provider_mode='offline'))
    monkeypatch.setattr(module,'Planner',PlannerStub)
    runner.evaluator.evaluate=lambda *args,**kwargs:dict(verdict='rejected',per_criterion={'control':dict(passed=False,reason='Private view regressed'),'performance':dict(passed=True,value=0,reason=None)})
    runner.run(sid)
    state=runner.store.get('sessions',sid)
    assert state['attempts_used']==3
    assert commands.count('apply_patch')==3 and commands.count('restore')==3
    assert state['current_version']==state['best_version']=='v'
    assert state['state']=='limit_reached'
    assert len(runner.run_data(sid)['attempts'])==3


def test_stop_after_reservation_releases_only_unsent_call(tmp_path):
    from datetime import date
    from hdrp_agent.orchestrator import SessionBudget
    from hdrp_agent.budget import Budget,Pricing
    runner=engine(tmp_path);sid=runner.create(request(),'create')['id']
    budget=Budget(runner.store,Pricing(date.today().isoformat(),True))
    budget.confirm_balance(150000000,'unit fixture, not real balance',datetime.now(timezone.utc).isoformat())
    scoped=SessionBudget(runner,sid,budget)
    call=scoped.reserve('muse-spark-1.3-contributor',{'fixture':'no transmission'})
    with runner.store.tx() as c:c.execute('UPDATE sessions SET stop_requested=1 WHERE id=?',(sid,))
    with pytest.raises(AgentError) as exc:scoped.mark_sent(call['id'])
    assert exc.value.code=='STOP_REQUESTED'
    assert budget.state()['active_reserved_usd_micro']==0
    with runner.store.tx() as c:assert c.execute('SELECT status FROM calls').fetchone()[0]=='released'


@pytest.mark.parametrize('fault',['missing_callback','cancelled','missing_resources','wrong_version'])
def test_complete_label_does_not_replace_current_job_bake_proof(tmp_path,fault):
    runner=engine(tmp_path);sid=runner.create(request(),'create')['id']
    result=dict(bake_status='complete',before_version='v',after_version='baked')
    journal=dict(status='complete',job_id='bake-test',resources_verified=True,before_version='v',after_version='baked',events=[dict(phase=p) for p in ['bakeStarted','bakeCompleted','stopped']])
    if fault=='missing_callback':journal['events']=[dict(phase='stopped')]
    if fault=='cancelled':journal['events'].insert(1,dict(phase='cancel_requested'))
    if fault=='missing_resources':journal['resources_verified']=False
    if fault=='wrong_version':journal['after_version']='old'
    runner.command=lambda *args,**kwargs:result;runner.details=lambda value:journal
    with pytest.raises(AgentError) as exc:runner.bake(sid)
    assert exc.value.code=='BAKE_INCOMPLETE'
