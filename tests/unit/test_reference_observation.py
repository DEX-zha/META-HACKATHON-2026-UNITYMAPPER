import io
from types import SimpleNamespace
from PIL import Image
import pytest
from hdrp_agent.artifacts import ArtifactStore
from hdrp_agent.store import Store
from hdrp_agent.domain import AgentError,fingerprint
from hdrp_agent.reference_observation import acquire_observations


def fixture(tmp_path):
    store=Store(tmp_path/'ledger.db');artifacts=ArtifactStore(tmp_path/'artifacts',store);out=io.BytesIO();Image.new('RGB',(32,32),'white').save(out,format='PNG');digest=artifacts.put(out.getvalue(),'image/png')
    frames=[dict(key=k,artifact_hash=digest,calibration=dict(position_m=[0,1,-3],rotation_deg=[0,0,0],fov_deg=45)) for k in ['front','back','control-private-sentinel']]
    analysis=dict(objects=[dict(key='floor',label='broken wooden floor',view_boxes=[dict(view_key='front',bbox_xyxy=[.1,.1,.9,.9])])]);geometry=dict(per_object={'floor':dict(covered=False,missing_reasons=['no_masks'])})
    return store,artifacts,frames,analysis,geometry


def test_followup_is_bounded_unique_and_never_sends_control_images(tmp_path,monkeypatch):
    import hdrp_agent.reference_observation as module
    store,artifacts,frames,analysis,geometry=fixture(tmp_path);requests=[];sam=[];checkpoints=[]
    value=dict(requests=[dict(object_key='floor',concept='wooden floor',view_keys=['front','back']),dict(object_key='floor',concept='wooden floor',view_keys=['front'])],reason='Visible broad surface in separate views')
    def send(request,schema):requests.append(request);return dict(value=value,call_id='fixture')
    class Segment:
        def __init__(self,*args):pass
        def segment(self,frame,concept):sam.append((frame['key'],concept));return dict(source='fixture',regions=[dict(bbox_xyxy=[.1,.1,.9,.9],confidence=.9)])
    monkeypatch.setattr(module,'Segmenter',Segment)
    result,proof=acquire_observations(SimpleNamespace(send=send),artifacts,analysis,frames,[],[],geometry,lambda:None,lambda a,b:checkpoints.append(len(a)))
    assert len(requests)==1 and len(sam)==2 and len(result)==2 and len(checkpoints)==3
    assert 'private-sentinel' not in str(requests) and not proof['source_transforms_used']


def test_unknown_observation_call_is_never_retransmitted_or_released(tmp_path):
    store,artifacts,frames,analysis,geometry=fixture(tmp_path);sent=[]
    def send(request,schema):
        sent.append(1)
        with store.tx() as c:c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)',('unknown-call',request['model'],fingerprint(request),'unknown',1000,None,'{}','fixture'))
        raise AgentError('PROVIDER_OUTCOME_UNKNOWN','Unknown; reserved amount retained')
    provider=SimpleNamespace(send=send)
    for _ in range(2):
        with pytest.raises(AgentError):acquire_observations(provider,artifacts,analysis,frames,[],[],geometry,lambda:None)
    assert sent==[1]
    with store.tx() as c:assert c.execute('SELECT reserved FROM calls WHERE id=?',('unknown-call',)).fetchone()[0]==1000


def test_provider_schema_uses_supported_dialect_but_local_uniqueness_stays_strict():
    from hdrp_agent.providers.meta_responses import strict_schema
    from hdrp_agent.domain import payload
    schema=strict_schema('ModelReferenceObservationPlan')
    assert 'uniqueItems' not in schema['properties']['requests']['items']['properties']['view_keys']
    with pytest.raises((ValueError,AgentError)):
        payload('ModelReferenceObservationPlan',dict(requests=[dict(object_key='floor',concept='floor',view_keys=['front','front'])],reason='duplicate'))
