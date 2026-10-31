import hashlib

from fastapi.testclient import TestClient

from hdrp_agent.api import create_app
from hdrp_agent.config import Settings
from hdrp_agent.domain import validator


def test_registration_closed_paths_and_immutable_artifact(tmp_path):
    settings=Settings(tmp_path,token='fixture-local-token')
    root=tmp_path/'project';(root/'Assets').mkdir(parents=True)
    (root/'Assets/Test.unity').write_text('fixture, not a render')
    data=dict(project_id='project',scene_id='scene',project_root=str(root),working_scene_path='Assets/Test.unity',editor_version='6000.3.23f1',hdrp_version='17.3.0',graphics_api='Metal',scene_version='version',capabilities=['bridge-v1'],bridge_epoch='epoch')
    auth={'Authorization':'Bearer '+settings.token,'Idempotency-Key':'registration'}
    with TestClient(create_app(settings)) as client:
        first=client.post('/v1/projects/register',json=data,headers=auth)
        assert first.status_code==200,first.text
        validator('ProjectRegistered').validate(first.json())
        assert client.post('/v1/projects/register',json=data,headers=auth).json()==first.json()
        assert client.post('/v1/projects/register',json=dict(data,secret='bad'),headers=auth).status_code==422
        assert client.post('/v1/projects/register',json=dict(data,working_scene_path='../outside.unity'),headers=auth).status_code==422
        assert client.post('/v1/bridge/poll',json=dict(project_id='project',bridge_epoch='epoch',last_receipt_id=None),headers=auth).json()=={'commands':[], 'session_active':False}
        content=b'{"evidence":"offline"}';digest=hashlib.sha256(content).hexdigest()
        assert client.put('/v1/artifacts/'+digest,content=content,headers=auth).status_code==201
        assert client.get('/v1/artifacts/'+digest,headers=auth).content==content
        assert client.put('/v1/artifacts/'+digest,content=b'changed',headers=auth).status_code==422
        assert client.put('/v1/artifacts/'+'a'*64,content=b'x'*10000001,headers=dict(auth,**{'Content-Type':'image/png'})).status_code==413
