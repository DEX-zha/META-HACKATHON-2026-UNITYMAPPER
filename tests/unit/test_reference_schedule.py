from copy import deepcopy
from hdrp_agent.reference_schedule import default_policy,next_action,assess


def attempt(phase='baseline',iou=.7,rgb=.5):
    g=dict(score=1-iou,coverage_complete=True,per_object=dict(prop=dict(views=dict(front=dict(visible_iou=iou)),view_count=2,mean_iou=iou,contour_error_px=4)))
    return dict(phase=phase,metrics=dict(geometry=g,contacts=dict(passed=True),score=rgb,per_view=dict(front=dict(score=rgb))),applied_plan=dict(objects=[]),retained=True)


def test_better_geometry_is_not_rejected_for_worse_rgb():
    before=attempt();after=attempt('anchoring',.8,.8)
    assert assess(after,before,default_policy())==(True,[])
    assert not assess(attempt('anchoring',.6,.1),before,default_policy())[0]


def test_missing_measurement_and_limits_are_not_convergence():
    p=default_policy();a=attempt();assert next_action([],None,p)['action']=='baseline'
    assert next_action([a],a,p)['action']=='anchoring'
    assert next_action([a]*6,a,p)==dict(action='stop',reason='candidate_limit')
    a['metrics']['geometry']['score']=None;assert next_action([a],a,p)['reason']=='insufficient_observations'


def test_appearance_cannot_change_pose_or_start_before_geometry_gate():
    p=default_policy();a=attempt();after=attempt('appearance',.7,.2);after['applied_plan']['objects']=[{'key':'new'}]
    assert not assess(after,a,p)[0]
    attempts=[attempt(s) for s in ['baseline','anchoring','arranging','placement']]
    assert next_action(attempts,a,p)['action']!='appearance'


def test_search_checks_local_deadline_and_throttles_external_state(monkeypatch):
    import pytest
    import hdrp_agent.reference_schedule as schedule
    current=[10.];monkeypatch.setattr(schedule.time,'monotonic',lambda:current[0])
    checks=[];budget=schedule.SearchBudget(default_policy(),lambda:checks.append(current[0]))
    for _ in range(100):budget.check()
    assert checks==[10.]
    current[0]+=.26;budget.check();assert len(checks)==2
    current[0]+=121
    with pytest.raises(schedule.LocalLimit):budget.check()
    assert budget.reason=='local_time_limit'


def test_rejected_anchor_can_seed_joint_trial_without_becoming_best():
    from hdrp_agent.reference_schedule import proposal_base
    best=attempt();anchor=attempt('anchoring',.8);anchor.update(state='rendered',retained=False)
    assert proposal_base([best,anchor],best,'arranging') is anchor
    assert proposal_base([best,anchor],best,'placement') is best
    assert best['phase']=='baseline' and anchor['retained'] is False
    anchor['metrics']['contacts']['passed']=False
    assert proposal_base([best,anchor],best,'arranging') is best


def test_geometry_gate_requires_qualified_appearance_and_stagnation_stops():
    policy=default_policy();best=attempt(iou=.99);best['metrics']['geometry']['per_object']['prop']['contour_error_px']=1
    history=[attempt(s) for s in ['baseline','anchoring','arranging','placement']]
    assert next_action(history,best,policy)['reason']=='appearance_capture_unqualified'
    policy['noise_baseline_hash']='a'*64;best['metrics']['appearance']=dict(protocol_qualified=True)
    assert next_action(history,best,policy)['action']=='appearance'
    history.append(attempt('appearance'));history[-1]['retained']=False
    assert next_action(history,best,policy)['reason']=='no_admissible_progress'
    best=attempt();history=history[:4]
    for a in history[-2:]:a['retained']=False
    assert next_action(history,best,policy)['reason']=='no_admissible_progress'
    best['metrics']['geometry']['coverage_complete']=False
    assert next_action(history,best,policy)['reason']=='insufficient_observations'


def test_scale_is_a_separate_opt_in_phase():
    p=default_policy();history=[attempt(s) for s in ['baseline','anchoring','arranging']]
    assert next_action(history,history[0],p)['action']=='placement'
    p['scale_mode']='evidenced'
    assert next_action(history,history[0],p)['action']=='scaling'
