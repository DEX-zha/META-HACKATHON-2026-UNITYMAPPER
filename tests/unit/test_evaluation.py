"""Private acceptance evidence must not be replaced by the model's opinion."""
import io
from copy import deepcopy

import pytest
from PIL import Image

from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.domain import AgentError, fingerprint
from hdrp_agent.store import Store


def setup(tmp_path):
    from hdrp_agent.evaluation import Evaluator
    store=Store(tmp_path/'state.sqlite3');artifacts=ArtifactStore(tmp_path/'artifacts',store)
    def image(value):
        out=io.BytesIO();Image.new('RGB',(32,24),(value,)*3).save(out,format='PNG')
        return artifacts.put(out.getvalue(),'image/png')
    def packet(version,value):
        captures=[dict(camera_key=key,role=role,artifact_hash=image(value),version_id=version,render_ready=True,provenance='live') for role,keys in [('work',['front','left','right']),('control',['corner','low'])] for key in keys]
        return dict(version=version,inspection_hash='i',conditions_hash='c',captures=captures,comparable=True,performance=dict(frame_count=120,median_frame_ms=10,method='editor_wall_frame_time_no_readback',capture_framerate_disabled=True,focused=True,focus_stable=True,v_sync_count=0,target_frame_rate=-1),geometry={})
    targets={'defect':dict(camera_key='front',roi=[0,0,1,1],reference_artifact_hash=image(140)),'control':dict(camera_key='corner',roi=[0,0,1,1],reference_artifact_hash=image(140)),'performance':{}}
    criteria=[dict(id='defect',kind='artifact',target='defect',method='luminance_error',minimum=.25,maximum=None,unit='relative_reduction',required=True),dict(id='control',kind='visibility',target='control',method='luminance_error',minimum=None,maximum=.01,unit='regression',required=True),dict(id='performance',kind='performance',target='performance',method='frame_time_regression',minimum=None,maximum=.2,unit='ratio',required=True)]
    return Evaluator(artifacts,tmp_path/'reviews'),criteria,targets,packet('before',60),packet('after',130)


def test_target_reduction_and_private_control(tmp_path):
    evaluator,criteria,targets,before,after=setup(tmp_path)
    frozen=evaluator.freeze(criteria,targets)
    assert evaluator.evaluate(frozen,before,after,session_id='session')['verdict']=='improved'
    bad=deepcopy(after)
    bad['captures'][3]['artifact_hash']=before['captures'][0]['artifact_hash']
    # Control is now at the original defect, still not regressed. Make it worse.
    bad['captures'][3]['artifact_hash']=evaluator.artifacts.put(_black(),'image/png')
    result=evaluator.evaluate(frozen,before,bad,session_id='session')
    assert result['verdict']=='rejected'
    assert result['per_criterion']['control']['passed'] is False


def _black():
    out=io.BytesIO();Image.new('RGB',(32,24)).save(out,format='PNG');return out.getvalue()


def test_missing_human_is_provisional_and_reviews_bound_to_versions(tmp_path):
    import json
    from hdrp_agent.store import utc_now
    evaluator,criteria,targets,before,after=setup(tmp_path)
    criteria.append(dict(id='mood',kind='artistic',target='mood',method='artistic_review',minimum=None,maximum=None,unit='human',required=True));targets['mood']={}
    frozen=evaluator.freeze(criteria,targets)
    assert evaluator.evaluate(frozen,before,after,session_id='session')['verdict']=='inconclusive'
    evaluator.reviews.mkdir()
    review=dict(session_id='session',before_version='before',after_version='after',criteria_hash=frozen['criteria_hash'],criterion_id='mood',reviewer_id='human-1',decision=True,notes='Beam and table remain readable',created_at=utc_now())
    (evaluator.reviews/'review.json').write_text(json.dumps(review))
    assert evaluator.evaluate(frozen,before,after,session_id='session')['verdict']=='improved'
    review['after_version']='stale';(evaluator.reviews/'review.json').write_text(json.dumps(review))
    assert evaluator.evaluate(frozen,before,after,session_id='session')['verdict']=='inconclusive'


def test_unknown_method_and_mutated_frozen_threshold_refused(tmp_path):
    evaluator,criteria,targets,before,after=setup(tmp_path)
    with pytest.raises(AgentError):evaluator.freeze([dict(criteria[0],method='model_vote')],targets)
    frozen=evaluator.freeze(criteria,targets);frozen['criteria'][0]['minimum']=0
    with pytest.raises(AgentError,match='frozen'):evaluator.evaluate(frozen,before,after,session_id='session')


@pytest.mark.parametrize('fault',['old_image','conditions','missing_control','performance','offline','missing_geometry'])
def test_missing_or_untrusted_evidence_never_improved(tmp_path,fault):
    evaluator,criteria,targets,before,after=setup(tmp_path)
    if fault=='old_image':after['captures'][0]['version_id']='old'
    if fault=='conditions':after['conditions_hash']='different'
    if fault=='missing_control':after['captures']=after['captures'][:3]
    if fault=='performance':after['performance']['median_frame_ms']=12.01
    if fault=='offline':after['captures'][0]['provenance']='offline'
    if fault=='missing_geometry':
        targets['table']={};criteria.append(dict(id='gap',kind='geometry',target='table',method='support_gap',minimum=0,maximum=.02,unit='m',required=True))
    result=evaluator.evaluate(evaluator.freeze(criteria,targets),before,after,session_id='session')
    assert result['verdict']!='improved'


@pytest.mark.parametrize('fault',['missing_focus','background','focus_changed','v_sync','frame_cap'])
def test_performance_requires_stable_foreground_and_no_frame_caps(tmp_path,fault):
    evaluator,criteria,targets,before,after=setup(tmp_path)
    for packet in [before,after]:packet['performance'].update(focused=True,focus_stable=True,v_sync_count=0,target_frame_rate=-1)
    sample=after['performance']
    if fault=='missing_focus':sample.pop('focused')
    if fault=='background':sample['focused']=False
    if fault=='focus_changed':sample['focus_stable']=False
    if fault=='v_sync':sample['v_sync_count']=1
    if fault=='frame_cap':sample['target_frame_rate']=30
    result=evaluator.evaluate(evaluator.freeze(criteria,targets),before,after,session_id='session')
    assert result['verdict']=='inconclusive'
    assert result['per_criterion']['performance']['passed'] is None


@pytest.mark.parametrize('legacy',[False,True])
def test_performance_cannot_compare_measurements_from_different_focus_policies(tmp_path,legacy):
    evaluator,criteria,targets,before,after=setup(tmp_path)
    after['capture_policy']={'revision':'foreground-ownership-v1'}
    if not legacy:before['capture_policy']={'revision':'one-shot-activation'}
    before['performance']['median_frame_ms']=100
    after['performance']['median_frame_ms']=9
    result=evaluator.evaluate(evaluator.freeze(criteria,targets),before,after,session_id='session')
    assert result['per_criterion']['performance']['passed'] is None
    assert result['per_criterion']['performance']['value'] is None
    assert result['verdict']=='inconclusive'
