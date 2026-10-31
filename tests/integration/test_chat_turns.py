from contextlib import closing
from types import SimpleNamespace
import pytest
from hdrp_agent.chat_turns import ChatTurns
from hdrp_agent.domain import AgentError
from test_chat_actions import setup


def request(action):
    return dict(schema_version='1.0',turn_id='turn-1',project_id='project',conversation_id='chat',message_id='message',idempotency_key='once',messages=[dict(role='user',text='Bonjour, explique le projet sans action.')],artifact_hashes=action['artifact_hashes'],memory=dict(revision=0,summary='',constraints=[],scene_version='source',parent_run_id=None))


def test_turn_response_is_durable_and_duplicate_never_calls_again(tmp_path):
    worker,legacy,service,action=setup(tmp_path);calls=[]
    class Provider:
        def __init__(self,*args):self.client=SimpleNamespace(close=lambda:None)
        def send(self,*args):calls.append(1);return dict(value=dict(text='Bonjour',tools=[]),call_id='fixture-call')
    turns=ChatTurns(worker.settings,worker.store,worker.artifacts,Provider);data=request(action)
    first=turns.send(data);assert first['state']=='complete'
    assert turns.send(data)==first and calls==[1]
    reopened=ChatTurns(worker.settings,worker.store,worker.artifacts,Provider)
    assert reopened.get('turn-1')==first
    data['messages'][0]['text']='Different'
    with pytest.raises(AgentError):turns.send(data)


def test_unknown_cost_is_kept_and_never_retried(tmp_path):
    worker,legacy,service,action=setup(tmp_path);calls=[]
    class Provider:
        def __init__(self,settings,budget,artifacts):self.budget=budget;self.client=SimpleNamespace(close=lambda:None)
        def send(self,req,*args):
            call=self.budget.reserve(req['model'],req);self.budget.mark_sent(call['id']);self.budget.mark_unknown(call['id']);calls.append(call['id']);raise AgentError('PROVIDER_OUTCOME_UNKNOWN','lost')
    turns=ChatTurns(worker.settings,worker.store,worker.artifacts,Provider);data=request(action)
    first=turns.send(data);assert first['state']=='unknown'
    assert turns.send(data)==first and len(calls)==1
    with closing(worker.store.connect()) as c:assert c.execute('SELECT status FROM calls').fetchone()[0]=='unknown'


def test_attachment_cannot_cross_projects(tmp_path):
    worker,legacy,service,action=setup(tmp_path);turns=ChatTurns(worker.settings,worker.store,worker.artifacts)
    with worker.store.tx() as c:c.execute('DELETE FROM app_artifacts')
    with pytest.raises(AgentError,match='Unowned'):turns.send(request(action))
