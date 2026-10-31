"""Offline native handoff receipts. No model response or Unity success is simulated as live."""
from contextlib import closing
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest
from hdrp_agent.domain import AgentError,canonical
from hdrp_agent.reference_commands import ReferenceCommands
from test_reference_workflow import engine


def setup(tmp_path):
    worker,legacy,budget=engine(tmp_path);store=worker.store
    project=tmp_path/'project';project.mkdir()
    with store.tx() as c:
        c.execute('UPDATE projects SET body=?',(canonical(dict(project_root=str(project),scene_version='source',capabilities=['prepare_reference_run'])),))
    service=ReferenceCommands(worker.settings,store,worker.runner.queue,worker.artifacts)
    h=worker.artifacts.put((legacy/'input.png').read_bytes(),'image/png')
    with store.tx() as c:c.execute('INSERT INTO app_artifacts VALUES(?,?)',('project',h))
    request=dict(schema_version='1.0',action_id='action',project_id='project',conversation_id='chat',message_id='message',kind='reconstruct_reference',expected_scene_version='source',artifact_hashes=[h],parameters=dict(brief='Murs B et plafond, conserver le cadrage.',reference_hashes=[h],building_policy='atmospheric-house',interior_style='B',ceiling_prefab='Ceiling_3x3'),idempotency_key='once')
    return worker,legacy,service,request


def prepared(worker,legacy,service,request):
    state=service.admit(request);directory=worker.root/state['run_id'];directory.mkdir()
    bundle=json.loads((legacy/'bundle.json').read_text());bundle.update(id=state['run_id'],operation_id=state['operation_id'],session_id=state['session_id'],brief=request['parameters']['brief'],interior_style='B',ceiling_prefab='Ceiling_3x3',building_policy='atmospheric-house')
    path=directory/'bundle.json';path.write_text(canonical(bundle));(directory/'catalogue.json').write_text('[]')
    receipt_hash=worker.artifacts.put(canonical(dict(operation_id=state['operation_id'],session_id=state['session_id'],run_id=state['run_id'],bundle_sha256=hashlib.sha256(path.read_bytes()).hexdigest())).encode(),'application/json')
    # Persist an acknowledged native receipt; command queue correctness has its own tests.
    with worker.store.tx() as c:c.execute("UPDATE commands SET status='succeeded',result=?",(canonical(dict(details_artifact_hash=receipt_hash)),))
    return state,path


def test_duplicate_action_adopts_exactly_one_session(tmp_path):
    worker,legacy,service,request=setup(tmp_path)
    state,path=prepared(worker,legacy,service,request)
    assert service.admit(request)==state
    changed=deepcopy(request);changed['parameters']['brief']='different'
    with pytest.raises(AgentError,match='different content'):service.admit(changed)
    job=worker.claim(path)
    assert job['session_id']==state['session_id']
    with closing(worker.store.connect()) as c:
        assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM commands').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM reference_runs').fetchone()[0]==1
    with pytest.raises(AgentError):worker.claim(path)
    assert service.get('action')['state']=='running'


def test_lost_preparation_and_restart_are_not_replayed(tmp_path):
    worker,legacy,service,request=setup(tmp_path);state=service.admit(request)
    with worker.store.tx() as c:c.execute("UPDATE commands SET status='unknown'")
    service.recover_startup()
    assert service.get('action')['state']=='recovery_required'
    assert service.admit(request)['run_id']==state['run_id']
    with closing(worker.store.connect()) as c:assert c.execute('SELECT count(*) FROM commands').fetchone()[0]==1


@pytest.mark.parametrize('fault',['brief','receipt','epoch','stop'])
def test_adoption_requires_same_brief_receipt_epoch_and_live_session(tmp_path,fault):
    worker,legacy,service,request=setup(tmp_path);state,path=prepared(worker,legacy,service,request)
    if fault=='brief':
        bundle=json.loads(path.read_text());bundle['brief']='lost user intent';path.write_text(canonical(bundle))
    with worker.store.tx() as c:
        if fault=='receipt':c.execute("UPDATE commands SET status='unknown'")
        if fault=='epoch':c.execute("UPDATE projects SET epoch='new'")
        if fault=='stop':c.execute('UPDATE sessions SET stop_requested=1')
    with pytest.raises(AgentError):worker.claim(path)
    with closing(worker.store.connect()) as c:assert c.execute('SELECT count(*) FROM reference_runs').fetchone()[0]==0


def test_unowned_artifact_and_stale_version_refused_before_reservation(tmp_path):
    worker,legacy,service,request=setup(tmp_path)
    bad=deepcopy(request);bad['expected_scene_version']='old'
    with pytest.raises(AgentError,match='version'):service.admit(bad)
    with worker.store.tx() as c:c.execute('DELETE FROM app_artifacts')
    with pytest.raises(AgentError,match='attached'):service.admit(request)
    with closing(worker.store.connect()) as c:assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0


def test_unclaimed_expired_preparation_releases_session_without_replay(tmp_path):
    worker,legacy,service,request=setup(tmp_path);state=service.admit(request)
    with worker.store.tx() as c:
        row=c.execute('SELECT id,body FROM commands').fetchone();command=json.loads(row['body']);command['deadline_utc']='2000-01-01T00:00:00+00:00'
        c.execute('UPDATE commands SET body=? WHERE id=?',(canonical(command),row['id']))
    service.reconcile()
    assert service.get('action')['state']=='interrupted'
    assert service.admit(request)['run_id']==state['run_id']
    with closing(worker.store.connect()) as c:assert c.execute('SELECT count(*) FROM commands').fetchone()[0]==1


def test_http_action_admission_does_not_start_a_second_session(tmp_path):
    from fastapi.testclient import TestClient
    from hdrp_agent.api import create_app
    worker,legacy,service,request=setup(tmp_path)
    # No lifespan: exercise HTTP admission without a worker or provider call.
    client=TestClient(create_app(worker.settings));headers={'Authorization':'Bearer '+worker.settings.token}
    first=client.post('/v1/app/actions',json=request,headers=headers)
    assert first.status_code==202,first.text
    assert client.post('/v1/app/actions',json=request,headers=headers).json()==first.json()
    assert client.get('/v1/app/actions/action',headers=headers).json()==first.json()
    invalid={**request,'code':'forbidden'}
    assert client.post('/v1/app/actions',json=invalid,headers=headers).status_code==422
    with closing(worker.store.connect()) as c:
        assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM calls').fetchone()[0]==0
    client.close()


def test_refused_adoption_requires_reconciliation_not_endless_wait(tmp_path):
    worker,legacy,service,request=setup(tmp_path);state,path=prepared(worker,legacy,service,request)
    bundle=json.loads(path.read_text());bundle['brief']='changed';path.write_text(canonical(bundle))
    worker.run(path)
    assert service.get('action')['state']=='recovery_required'
    assert (path.parent/'native-stop.json').exists()
