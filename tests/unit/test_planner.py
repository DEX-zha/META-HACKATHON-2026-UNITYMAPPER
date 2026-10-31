from copy import deepcopy
import json

import pytest

from hdrp_agent.domain import AgentError
from hdrp_agent.prompts import work_context
from hdrp_agent.planner import Planner


def context():
    capture=dict(artifact_hash='a'*64,version_id='version',inspection_hash='b'*64,conditions_hash='c'*64,role='work',camera_key='front',frame_index=0,simulated_time=0,provenance='live',render_ready=True)
    control=dict(capture,role='control',artifact_hash='d'*64,camera_key='hidden')
    return work_context({'text':'Room'},[],dict(version='version',objects=[dict(logical_key='light',name='Window Light',source_global_object_id='private provenance')],oracle='SECRET_SOLUTION',control_scores={'hidden':0}),[capture,control])


def test_control_images_scores_and_oracles_are_not_in_context():
    data=json.dumps(context())
    for forbidden in ['SECRET_SOLUTION','control_scores','hidden','d'*64,'private provenance']:assert forbidden not in data
    assert len(context()['work_captures'])==1


def test_unknown_evidence_targets_and_stale_diagnosis_are_refused():
    c=context();p=Planner(None,None)
    d=dict(scene_version='version',inspected_capture_ids=[x['id'] for x in c['work_captures']],observations=[],hypotheses=[],unsupported_limits=[])
    p.validate_diagnosis(d,c)
    with pytest.raises(AgentError):p.validate_diagnosis(dict(d,scene_version='old'),c)
    e=dict(capture_id='unseen',frame_index=0,bbox_xyxy=None,target_ids=['light'],description='Claim')
    d['observations']=[dict(key='observation',category='lighting',claim='Dim light',evidence=[e])]
    with pytest.raises(AgentError):p.validate_diagnosis(d,c)


def test_current_admission_bounds_are_supplied_without_a_suggested_correction():
    from hdrp_agent.domain import PROPERTY_BOUNDS
    planner=Planner(None,None)
    source=context();capture=dict(source['work_captures'][0],role='work',render_ready=True)
    result=planner.context({'text':'Inspect'},[],dict(version='version',objects=[],capabilities=['apply_patch']),[capture])
    bounds=result['mutation_rules']['numeric_property_bounds']
    assert bounds['mean_free_path_m']=={'minimum':PROPERTY_BOUNDS['mean_free_path_m'][0],'maximum':PROPERTY_BOUNDS['mean_free_path_m'][1]}
    assert 'suggested_value' not in canonical_json(result['mutation_rules'])


def canonical_json(data):return json.dumps(data,sort_keys=True)


def test_measured_bake_settings_reach_planner_without_private_fields():
    source=context();capture=dict(source['work_captures'][0],role='work',render_ready=True)
    bake=dict(lightmap_resolution_texels_per_unit=12,lightmap_max_size=512,indirect_samples=64,lightmapper='ProgressiveGPU',oracle='SECRET',reference_image='private.png')
    result=Planner(None,None).context({'text':'Inspect'},[],dict(version='version',objects=[],bake=bake),[capture])
    assert result['bake_settings']=={key:bake[key] for key in ['lightmap_resolution_texels_per_unit','lightmap_max_size','indirect_samples','lightmapper']}
    bake['indirect_samples']=999
    assert result['bake_settings']['indirect_samples']==64
    assert 'SECRET' not in canonical_json(result) and 'private.png' not in canonical_json(result)


def test_diagnosis_must_explicitly_inspect_every_supplied_work_frame():
    source=context();sample=dict(source['work_captures'][0],role='work',render_ready=True)
    captures=[dict(sample,camera_key=key) for key in ['front','left','right']]
    data=Planner(None,None).context({'text':'Clean the whole room'},[],dict(version='version',objects=[]),captures)
    ids=[item['id'] for item in data['work_captures']]
    diagnosis=dict(scene_version='version',inspected_capture_ids=ids,observations=[],hypotheses=[],unsupported_limits=[])
    Planner(None,None).validate_diagnosis(diagnosis,data)
    for invalid in [ids[:1],ids+[ids[0]],ids+['capture-unsupplied']]:
        with pytest.raises(AgentError):Planner(None,None).validate_diagnosis(dict(diagnosis,inspected_capture_ids=invalid),data)
