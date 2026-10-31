"""Acceptance scenarios are defined before the session implementation."""
from fastapi.testclient import TestClient

from hdrp_agent.api import create_app
from hdrp_agent.config import Settings


def test_unknown_session_and_stop_have_structured_error(tmp_path):
    settings=Settings(tmp_path,token='fixture-token')
    with TestClient(create_app(settings)) as client:
        headers={'Authorization':'Bearer '+settings.token,'Idempotency-Key':'stop'}
        response=client.get('/v1/sessions/missing',headers=headers)
        assert response.status_code==404
        assert response.json()['code']=='NOT_FOUND'


def test_session_read_stop_and_frozen_criteria(tmp_path):
    from hdrp_agent.domain import canonical,fingerprint,payload
    settings=Settings(tmp_path,token='fixture-token');app=create_app(settings);store=app.state.store
    criteria=[dict(id='visibility',kind='visibility',target='wall',method='luminance_range',minimum=.1,maximum=.9,unit='normalized',required=True)]
    frozen=fingerprint(criteria)
    session=payload('Session',dict(id='session',state='baseline',verdict='pending',best_version='version',current_version='version',attempts_used=0,max_attempts=3,criteria_hash=frozen,inspection_hash='a'*64,stop_reason=None,provider_mode='offline'))
    with store.tx() as c:
        c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical({})))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('scene','project',canonical({})))
        c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',('session','project','scene','baseline',canonical(session)))
    headers={'Authorization':'Bearer '+settings.token,'Idempotency-Key':'stop'}
    with TestClient(app) as client:
        assert client.get('/v1/sessions/session',headers=headers).json()==session
        denied=client.patch('/v1/sessions/session',headers=headers,json={'criteria':[]})
        assert denied.status_code==405
        assert store.get('sessions','session')['criteria_hash']==frozen
        assert client.post('/v1/sessions/session/stop',headers=headers,json={'reason':'operator','criteria':[]}).status_code==422
        first=client.post('/v1/sessions/session/stop',headers=headers,json={'reason':'operator'})
        assert first.status_code==202
        assert first.json()['state']=='baseline'  # 202 acknowledges a request, not native cancellation.
        assert client.post('/v1/sessions/session/stop',headers=headers,json={'reason':'operator'}).json()==first.json()
        assert client.post('/v1/sessions/session/stop',headers=headers,json={'reason':'changed'}).status_code==409
        with store.tx() as c:assert c.execute('SELECT stop_requested FROM sessions').fetchone()[0]==1


def test_wrong_sam_mask_falls_back_to_engine_selection_without_claiming_cause(tmp_path):
    import io
    from PIL import Image
    from hdrp_agent.artifacts import ArtifactStore
    from hdrp_agent.store import Store
    from hdrp_agent.domain import WORKSPACE
    from hdrp_agent.providers.fake import FakeProvider
    from hdrp_agent.segmentation import Segmenter
    store=Store(tmp_path/'state.sqlite3');artifacts=ArtifactStore(tmp_path/'artifacts',store)
    out=io.BytesIO();Image.new('RGB',(32,24)).save(out,format='PNG');digest=artifacts.put(out.getvalue(),'image/png')
    provider=FakeProvider([(WORKSPACE/'fixtures/provider-replies/wrong-mask.txt').read_text()])
    engine=[dict(target_id='owned-table',bbox_xyxy=[.1,.1,.9,.9])]
    selected=Segmenter(provider,artifacts).segment(dict(role='work',artifact_hash=digest),'table',engine)
    assert selected['source']=='engine_fallback' and selected['regions']==engine
    assert selected['association']=='uncertain' and 'no causal diagnosis' in selected['reason']
    assert provider.calls[0]['provider_mode']=='offline'
