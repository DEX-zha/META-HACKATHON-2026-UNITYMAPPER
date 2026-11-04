from copy import deepcopy
from hdrp_agent.house_convergence import converge


def proof(manifest,defects=()):
    return dict(scene_path='generated',scene_version=str(manifest.get('exposure_ev',6)),source_scene_unchanged=True,instances=[dict(i,connected=True,native_scale=True,support_passed=True) for i in manifest['instances']],defects=list(defects),captures=[dict(mean_rgb=.98 if manifest.get('exposure_ev',6)<14 else .5)])


def test_convergence_continues_beyond_six_passes_without_quota():
    m=dict(instances=[],exposure_ev=6);events=[]
    def build(m):return {},proof(m)
    # Actual decreasing evidence, eight passes to reach the usable range.
    def render(m):
        p=proof(m);p['captures'][0]['mean_rgb']=.98-(m['exposure_ev']-6)*.025
        return {},p
    output=converge(m,{},proof(m),[],build=render,inspect=lambda *a:[],enrich=lambda *a:None,record=lambda n,s,*a:events.append((n,s)),guard=lambda:None)
    assert output[0]['exposure_ev']==14
    assert len([s for _,s in events if s=='accepted'])==8


def test_regression_preserves_selected_scene_and_does_not_retry_same_pose():
    m=dict(instances=[],exposure_ev=6);original=proof(m);events=[]
    def build(candidate):return {},proof(candidate,[dict(kind='support',instance_id='a')])
    result=converge(m,{},original,[],build=build,inspect=lambda *a:(_ for _ in ()).throw(AssertionError('Do not review native regression')),enrich=lambda *a:None,record=lambda n,s,*a:events.append(s),guard=lambda:None)
    assert result[0]==m and result[2]==original
    assert events==['proposed','rejected']


def test_enrichment_is_reinspected_and_preserves_previous_equipment():
    m=dict(instances=[dict(id='desk')],exposure_ev=14);events=[]
    def enrich(m,*args):
        if len(m['instances'])>1:return None
        n=deepcopy(m);n['instances'].append(dict(id='books'));return n,dict(kind='enrich_room')
    result=converge(m,{},proof(m),[],build=lambda m:({},proof(m)),inspect=lambda *a:[],enrich=enrich,record=lambda n,s,*a:events.append(s),guard=lambda:None)
    assert [i['id'] for i in result[0]['instances']]==['desk','books']
    assert events==['proposed','accepted']


def test_unusable_views_cannot_erase_visual_defects():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='desk')],exposure_ev=14))
    after=deepcopy(before);after['captures'][0]['usable']=False
    defect=dict(room_id='house',instance_id='desk',kind='composition',severity='blocking')
    passed,_=acceptable(before,after,[defect],[],dict(kind='transform_group'))
    assert not passed


def test_measured_native_repair_counts_only_without_other_regressions():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='desk')],exposure_ev=14),[dict(kind='support',instance_id='desk')])
    after=deepcopy(before);after['defects']=[]
    assert acceptable(before,after,[],[],dict(kind='transform_group'))==(True,'Native defect resolved')
    after['instances']=[]
    assert not acceptable(before,after,[],[],dict(kind='transform_group'))[0]
    after=deepcopy(before);after['defects']=[]
    new=[dict(room_id='house',instance_id='desk',kind='collision',severity='blocking')]
    assert not acceptable(before,after,[],new,dict(kind='transform_group'))[0]


def test_enrichment_cannot_upgrade_warning_to_blocking():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='desk')],exposure_ev=14));after=deepcopy(before);after['instances'].append(dict(id='book',connected=True,native_scale=True,support_passed=True))
    warning=dict(room_id='house',instance_id='desk',kind='passage',severity='warning')
    assert not acceptable(before,after,[warning],[dict(warning,severity='blocking')],dict(kind='enrich_room'))[0]


def test_rejected_candidate_triggers_fresh_reasoning_once_per_rejection():
    m=dict(instances=[],exposure_ev=6);reviews=[]
    def build(candidate):return {},proof(candidate,[dict(kind='support')])
    result=converge(m,{},proof(m),[],build=build,inspect=lambda *a:[],enrich=lambda *a:None,record=lambda *a:None,guard=lambda:None,reconsider=lambda *a:reviews.append('rethink') or [])
    assert reviews==['rethink'] and result[0]==m


def test_unactionable_initial_defect_replans_without_any_prior_rejection():
    m=dict(instances=[],exposure_ev=14);reviews=[]
    defect=dict(room_id='house',instance_id='',kind='lighting',severity='blocking',suggested_action='none')
    result=converge(m,{},proof(m),[defect],build=lambda m:({},proof(m)),inspect=lambda *a:[defect],enrich=lambda *a:None,record=lambda *a:None,guard=lambda:None,reconsider=lambda *a:reviews.append('repair') or [])
    assert reviews==['repair']
    assert result[3]==[defect]  # Planning cannot erase evidence.


def test_replanning_never_becomes_visual_acceptance_baseline(monkeypatch):
    import hdrp_agent.house_convergence as loop
    m=dict(instances=[dict(id='desk')],exposure_ev=14)
    defect=dict(room_id='house',instance_id='wall',kind='missing',severity='blocking',message='No curtains')
    planning=dict(defect,instance_id='invented-target',message='Proposed move')
    def move(manifest,observations,attempted):
        if observations!=[planning] or len(manifest['instances'])>1:return None
        candidate=deepcopy(manifest);candidate['instances'].append(dict(id='book'))
        return candidate,dict(kind='enrich_room')
    monkeypatch.setattr(loop,'propose',move)
    result=converge(m,{},proof(m),[defect],build=lambda c:({},proof(c)),inspect=lambda *a:[defect],enrich=lambda *a:None,record=lambda *a:None,guard=lambda:None,reconsider=lambda *a:[planning])
    assert len(result[0]['instances'])==2
    assert result[3]==[defect]


def test_absence_relabeling_does_not_create_regression_but_new_collision_does():
    from hdrp_agent.house_convergence import acceptable
    before=proof(dict(instances=[dict(id='wardrobe')],exposure_ev=14));after=deepcopy(before)
    after['instances'].append(dict(id='books',connected=True,native_scale=True,support_passed=True))
    old=[dict(room_id='house',instance_id='wardrobe',kind='composition',severity='blocking',message='Wardrobe is empty; no clothes inside.'),dict(room_id='house',instance_id='shelf',kind='missing',severity='blocking',message='No posters or curtains on the bare walls.')]
    new=[dict(old[0],kind='missing'),dict(old[1],instance_id='wall-decor')]
    assert acceptable(before,after,old,new,dict(kind='enrich_room'))[0]
    new.append(dict(room_id='house',instance_id='books',kind='collision',severity='blocking',message='Books intersect the wardrobe.'))
    assert not acceptable(before,after,old,new,dict(kind='enrich_room'))[0]


def test_calibrated_exposure_is_locked_for_future_trials_without_rewriting_evidence():
    from hdrp_agent.house_convergence import observed_controls,exposure_proposal
    m=dict(instances=[],exposure_ev=6,calibrate_exposure=True)
    p=dict(exposure_calibration=dict(fixed_readback_verified=True,locked_ev100=2.5),captures=[dict(mean_rgb=.02,render_request_state=dict(status='observed',exposure_mode='Fixed',exposure_ev=2.5))])
    locked=observed_controls(m,p)
    candidate,patch=exposure_proposal(locked,p,set())
    assert candidate['exposure_ev']==1.5 and candidate['calibrate_exposure'] is False
    assert patch['before']==2.5
    assert m['exposure_ev']==6 and m['calibrate_exposure'] is True


def test_calibration_cannot_be_used_with_different_capture_exposure():
    import pytest
    from hdrp_agent.domain import AgentError
    from hdrp_agent.house_convergence import observed_controls
    m=dict(instances=[],exposure_ev=6,calibrate_exposure=True)
    p=dict(exposure_calibration=dict(fixed_readback_verified=True,locked_ev100=2.5),captures=[dict(render_request_state=dict(status='observed',exposure_mode='Fixed',exposure_ev=6))])
    with pytest.raises(AgentError,match='Capture exposure'):observed_controls(m,p)


def test_newly_reported_old_absence_requires_actual_baseline_review():
    m=dict(instances=[dict(id='shelf',position=[0,0,0],yaw=0)],exposure_ev=14)
    defect=dict(room_id='house',instance_id='shelf',kind='missing',severity='blocking',message='Shelf still sparse',suggested_action='none')
    for baseline_has_defect in (True,False):
        reviews=[];events=[]
        def enrich(current,*args):
            if len(current['instances'])>1 or events:return None
            candidate=deepcopy(current);candidate['instances'].append(dict(id='book'))
            return candidate,dict(kind='enrich_room')
        def inspect(current,evidence):
            reviews.append(len(current['instances']))
            return [defect] if len(current['instances'])>1 or baseline_has_defect else []
        result=converge(m,{},proof(m),[],build=lambda c:({},proof(c)),inspect=inspect,enrich=enrich,record=lambda n,s,p,*a:events.append((s,p)) if s!='proposed' else None,guard=lambda:None)
        assert reviews==[2,1]
        assert len(result[0]['instances'])==(2 if baseline_has_defect else 1)
        if baseline_has_defect:
            assert result[3]==[defect]
            assert events[0][1]['existing_defects_verified']==[defect]


def test_counterfactual_never_excuses_moved_new_or_physical_targets():
    from hdrp_agent.house_convergence import counterfactual_candidates
    before=dict(instances=[dict(id='shelf',position=[0,0,0])]);after=deepcopy(before)
    defect=dict(room_id='house',instance_id='shelf',kind='missing',severity='blocking')
    assert counterfactual_candidates(before,after,[],[defect])==[defect]
    after['instances'][0]['position']=[1,0,0]
    assert counterfactual_candidates(before,after,[],[defect])==[]
    assert counterfactual_candidates(before,before,[],[dict(defect,kind='collision')])==[]
    assert counterfactual_candidates(before,before,[],[dict(defect,kind='lighting')])==[]
    assert counterfactual_candidates(before,before,[],[dict(defect,instance_id='new')])==[]
