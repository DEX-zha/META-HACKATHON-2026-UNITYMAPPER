from datetime import datetime, timedelta, timezone

import pytest

from hdrp_agent.command_queue import CommandQueue
from hdrp_agent.domain import AgentError, canonical, fingerprint
from hdrp_agent.store import Store


@pytest.fixture
def queue(tmp_path):
    store=Store(tmp_path/'queue.db')
    with store.tx() as c:
        c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical({})))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('scene','project',canonical({})))
        c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',('session','project','scene','created',canonical(dict(state='created'))))
    return CommandQueue(store)


def command():
    p={'diagnostic_keys':['lights']}
    return dict(id='command',session_id='session',kind='inspect',expected_version='version',payload_hash=fingerprint(p),payload=p,deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),bridge_epoch='epoch')


def poll(queue): return queue.poll(dict(project_id='project',bridge_epoch='epoch',last_receipt_id=None))


def receipt(cmd):
    return dict(command_id=cmd['id'],bridge_epoch='epoch',payload_hash=cmd['payload_hash'],status='succeeded',before_version='version',after_version='version',artifact_hashes=[],captures=[],snapshot_id=None,manifest_hash='a'*64,bake_status='not_required',details_artifact_hash=None,error=None)


def test_claim_once_and_same_receipt_idempotent(queue):
    cmd=command(); queue.enqueue('project',cmd)
    assert poll(queue)['commands']==[cmd]
    assert poll(queue)['commands']==[]
    assert queue.result('command',receipt(cmd))['accepted']
    assert queue.result('command',receipt(cmd))['accepted']
    other=receipt(cmd);other['manifest_hash']='b'*64
    with pytest.raises(AgentError,match='differs'):queue.result('command',other)


def test_editor_remains_owned_while_model_thinks_and_during_recovery(queue):
    # There is no queued native job during a provider call, but a local J0
    # must still be prevented from replacing the session's scene.
    assert poll(queue)==dict(commands=[],session_active=True)
    with queue.store.tx() as c:c.execute("UPDATE sessions SET state='recovery_required'")
    assert poll(queue)['session_active'] is True
    with queue.store.tx() as c:c.execute("UPDATE sessions SET state='interrupted'")
    assert poll(queue)==dict(commands=[],session_active=False)


def test_restart_never_replays_and_late_heartbeat_cancels(queue):
    queue.enqueue('project',command());poll(queue)
    assert queue.expire(restart=True)==1
    assert poll(queue)['commands']==[]
    control=queue.progress('command',dict(bridge_epoch='epoch',phase='running',progress=.5,message='Delayed native callback'))
    assert control['directive']=='cancel'
    assert queue.store.get('sessions','session')['state']=='recovery_required'


def test_changed_hash_and_old_epoch_rejected(queue):
    cmd=command();queue.enqueue('project',cmd)
    cmd['payload']['diagnostic_keys']=['geometry'];cmd['payload_hash']=fingerprint(cmd['payload'])
    with pytest.raises(AgentError):queue.enqueue('project',cmd)
    poll(queue)
    with queue.store.tx() as c:
        queue.change_epoch(c,'project','next-epoch')
        c.execute("UPDATE projects SET epoch='next-epoch'")
    with pytest.raises(AgentError):poll(queue)
    with pytest.raises(AgentError):queue.result('command',receipt(command()))


def test_stop_received_even_after_native_delay(queue):
    queue.enqueue('project',command());poll(queue)
    with queue.store.tx() as c:c.execute('UPDATE sessions SET stop_requested=1')
    assert queue.progress('command',dict(bridge_epoch='epoch',phase='running',progress=.2,message='baking'))['directive']=='cancel'
