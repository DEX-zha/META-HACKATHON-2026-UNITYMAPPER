from copy import deepcopy
import json
import pytest
from hdrp_agent.domain import payload,fingerprint,AgentError
from hdrp_agent.reference_schedule import default_policy,assess
from hdrp_agent.reference_metrics import bind_measurements
from hdrp_agent.reference_memory import new_memory,prompt_metrics,prompt_memory


def test_policy_and_proposal_contracts_reject_unknown_fields_and_unbounded_limits():
    p=default_policy();assert payload('FidelityPolicy',p)==p
    for field,value in [('max_candidates',7),('max_local_seconds',121),('max_images',13),('source_pose',[0,1,0])]:
        bad=deepcopy(p);bad[field]=value
        with pytest.raises((ValueError,AgentError)):payload('FidelityPolicy',bad)
    proposal=dict(schema_version='1.0',proposal_id='p',origin='local',phase='anchoring',parent_version='v',policy_hash=fingerprint(p),proposed_plan_hash='a'*64,evidence_hashes=['b'*64])
    assert payload('PoseProposal',proposal)==proposal
    proposal['source_transform']='EVALUATOR_ONLY_SENTINEL'
    with pytest.raises((ValueError,AgentError)):payload('PoseProposal',proposal)


def test_policy_change_invalidates_decisions_but_not_original_evidence():
    analysis=dict(objects=[dict(key='prop',label='bottle',asset_id='asset',support_key=None)])
    a=new_memory('same-images',analysis,policy_hash='p1',solver_version='v1');a['history']=[dict(accepted=False)]
    assert new_memory('same-images',analysis,a,policy_hash='p1',solver_version='v1')['history']
    assert not new_memory('same-images',analysis,a,policy_hash='p2',solver_version='v1')['history']
    assert not new_memory('same-images',analysis,a,policy_hash='p1',solver_version='v2')['history']


def test_evaluator_fields_cannot_enter_compacted_model_context():
    sentinel='PRIVATE_EVALUATOR_SENTINEL'
    metrics=dict(score=.3,source_pose=sentinel,per_object=dict(prop=dict(priority_rgb_mae=.2,expected_position=sentinel,geometry=dict(source_pose=sentinel))))
    assert sentinel not in json.dumps(prompt_metrics(metrics))
    analysis=dict(objects=[dict(key='prop',label='bottle',asset_id='asset',support_key=None)])
    memory=new_memory('a',analysis);memory['ground_truth']=sentinel;memory['objects']['prop']['source_pose']=sentinel
    assert sentinel not in json.dumps(prompt_memory(memory))


def test_native_metric_binding_rejects_receipt_from_other_candidate():
    m=bind_measurements(dict(objects=[]),'v1',dict(per_object={}))
    with pytest.raises(AgentError):bind_measurements(dict(objects=[]),'v2',m,expected_version='v2')


def test_native_metric_binding_rejects_changed_pose_and_prediction():
    original=dict(objects=[dict(key='a',position_m=[0,0,0])])
    measured=bind_measurements(original,'v1',dict(per_object={}))
    changed=deepcopy(original);changed['objects'][0]['position_m'][1]=.1
    with pytest.raises(AgentError):bind_measurements(changed,'v1',measured)
    measured['stage']='proposal_prediction'
    with pytest.raises(AgentError):bind_measurements(original,'v1',measured)


def test_global_interruption_propagates_before_local_evaluation():
    from hdrp_agent.reference_schedule import SearchBudget
    calls=[]
    def stopped():
        calls.append('checked')
        raise AgentError('STOP_REQUESTED','Native interruption; no replay')
    budget=SearchBudget(default_policy(),stopped)
    with pytest.raises(AgentError) as failure:budget.charge()
    assert failure.value.code=='STOP_REQUESTED' and budget.evaluations==0 and calls==['checked']


def test_experiment_identity_ignores_rewording_but_requires_same_evidence_and_policy():
    from hdrp_agent.reference_memory import experiment_identity
    plan=dict(objects=[dict(key='a',position_m=[0,1,0])],notes=['first explanation'])
    same=deepcopy(plan);same['notes']=['rewritten explanation']
    assert experiment_identity(plan,'images','policy')==experiment_identity(same,'images','policy')
    assert experiment_identity(plan,'new-masks','policy')!=experiment_identity(plan,'images','policy')
    assert experiment_identity(plan,'images','new-policy')!=experiment_identity(plan,'images','policy')
    same['objects'][0]['position_m'][1]=1.1
    assert experiment_identity(plan,'images','policy')!=experiment_identity(same,'images','policy')


def test_all_frozen_fixture_configurations_separate_observations_from_expected_poses():
    import runpy
    import numpy as np
    from pathlib import Path
    root=Path(__file__).parents[1]/'fixtures/reference_fidelity'
    generate=runpy.run_path(str(root/'generate.py'))['generate']
    cases=json.loads((root/'cases.json').read_text())
    for case in cases['development']+cases['reserved']:
        fixture=generate(case);inputs=fixture['inputs'];expected=fixture['expected']
        assert 'reference' not in inputs and 'configuration' not in inputs
        assert len(inputs['observations'])==3
        if case['id']=='appearance-only':
            assert inputs['candidate']['objects']==expected['reference']['objects']
            assert inputs['candidate']['lights']!=expected['reference']['lights']
            assert all(np.array_equal(o['reference_ids'],o['candidate_ids']) for o in inputs['observations'])
        else:assert inputs['candidate']['objects']!=expected['reference']['objects']
