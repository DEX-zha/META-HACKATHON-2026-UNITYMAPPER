from copy import deepcopy
from hdrp_agent.reference_memory import new_memory,constrain_proposal,regressions,update_memory,phase_for


def plan():
    return dict(objects=[dict(key='prop',position_m=[0,1,0],rotation_deg=[0,0,0],scale=[1,1,1],asset_id='asset-prop'),dict(key='support_ground',position_m=[0,0,0],rotation_deg=[0,0,0],scale=[1,1,1],asset_id=None)],lights=[],exposure_ev=0,sky_color_rgb=[0,0,0],fog_mean_free_path_m=None,notes=[])


def test_experiments_preserve_other_dimensions_and_previously_seen_ground():
    before=plan();proposed=deepcopy(before);proposed['objects']=proposed['objects'][:1];proposed['objects'][0]['position_m'][0]=.2;proposed['exposure_ev']=2
    pose=constrain_proposal(proposed,before,'placement');lighting=constrain_proposal(proposed,before,'appearance')
    assert pose['objects'][0]['position_m'][0]==.2 and pose['exposure_ev']==0
    assert lighting['objects']==before['objects'] and lighting['exposure_ev']==2
    assert len(pose['objects'])==2 and before==plan()


def test_memory_does_not_leak_between_references_and_keeps_failed_experiments():
    analysis=dict(objects=[dict(key='prop',label='bottle',asset_id='asset-prop',support_key=None)])
    memory=new_memory('a',analysis);attempt=dict(ordinal=1,phase='placement',applied_plan=plan(),metrics=dict(score=.4,priority_score=.5,per_object=dict(prop=dict(priority_rgb_mae=.5))))
    update_memory(memory,attempt,None,False,'job-a')
    assert memory['history'][0]['accepted'] is False and memory['objects']['prop']['status']=='unmeasured'
    assert new_memory('a',analysis,memory)['history']==memory['history']
    assert new_memory('b',analysis,memory)['history']==[]
    assert memory['exact_reconstruction_verified'] is False


def test_average_improvement_cannot_hide_object_or_view_regression():
    before=dict(metrics=dict(score=.4,contacts=dict(passed=True),per_view=dict(top=dict(score=.3)),per_object=dict(prop=dict(priority_rgb_mae=.2))))
    after=dict(metrics=dict(score=.2,contacts=dict(passed=True),per_view=dict(top=dict(score=.34)),per_object=dict(prop=dict(priority_rgb_mae=.3))))
    assert {r['kind'] for r in regressions(after,before)}=={'view','object'}
    assert [phase_for(i) for i in range(6)]==['baseline','placement','placement','appearance','placement','appearance']


def test_prompt_memory_keeps_failures_without_repeating_full_measurement_history():
    import json
    from hdrp_agent.reference_memory import prompt_memory
    analysis=dict(objects=[dict(key='prop',label='bottle',asset_id='asset-prop',support_key=None)])
    memory=new_memory('a',analysis)
    for ordinal in range(18):
        attempt=dict(ordinal=ordinal,phase='placement',applied_plan=plan(),metrics=dict(score=.4,per_object=dict(prop=dict(priority_rgb_mae=.5,pose_fit_before_contact=dict(evaluations=200,all_vertices=[1]*10000)))))
        update_memory(memory,attempt,None,ordinal==0,'job-a')
    compact=prompt_memory(memory)
    assert len(json.dumps(compact))<10000
    assert len(compact['history'])==6 and all(not row['accepted'] for row in compact['history'])
    assert compact['total_archived_experiments']==18 and 'all_vertices' not in json.dumps(compact)


def test_rejected_lighting_values_are_available_to_the_next_proposal():
    from hdrp_agent.reference_memory import prompt_memory
    analysis=dict(objects=[dict(key='prop',label='bottle',asset_id='asset-prop',support_key=None)])
    memory=new_memory('a',analysis)
    proposal=plan();proposal['exposure_ev']=7;proposal['lights']=[dict(intensity=500)]
    attempt=dict(ordinal=1,phase='image_refinement',applied_plan=proposal,metrics=dict(score=.6,per_object={}))
    update_memory(memory,attempt,None,False,'job')
    proposal['lights'][0]['intensity']=8000
    remembered=prompt_memory(memory)['history'][0]
    assert not remembered['accepted']
    assert remembered['appearance_values']['exposure_ev']==7
    assert remembered['appearance_values']['lights'][0]['intensity']==500


def test_correction_keeps_architecture_and_clipped_lighting_evidence():
    from hdrp_agent.reference_memory import prompt_metrics
    metrics=dict(architecture=dict(defect_count=2,defects=[dict(object_key='west',kind='interior_faces_point_away_from_center')]),plan_photometry=dict(reference=dict(bright_fraction=.001),candidate=dict(bright_fraction=.52)))
    result=prompt_metrics(metrics)
    assert result['architecture']==metrics['architecture']
    assert result['plan_photometry']==metrics['plan_photometry']
    result['architecture']['defects'].clear()
    assert metrics['architecture']['defects']
