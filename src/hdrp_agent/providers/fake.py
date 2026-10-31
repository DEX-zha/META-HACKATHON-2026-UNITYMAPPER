from copy import deepcopy

from ..domain import AgentError, payload


class FakeProvider:
    """Offline contract fixtures only. Never produces a real repair verdict."""
    mode='offline'
    def __init__(self, responses): self.responses=iter(responses);self.calls=[]
    def respond(self, request, schema_name):
        self.calls.append({'provider_mode':'offline','request':deepcopy(request),'cost_usd_micro':0,'repair_validated':False})
        try: result=next(self.responses)
        except StopIteration: raise AgentError('OFFLINE_FIXTURE_EXHAUSTED','No fixture response remains')
        return payload(schema_name,deepcopy(result))

    def send(self, request, schema_name=None):
        self.calls.append({'provider_mode':'offline','request':deepcopy(request),'cost_usd_micro':0,'repair_validated':False})
        try: result=deepcopy(next(self.responses))
        except StopIteration:raise AgentError('OFFLINE_FIXTURE_EXHAUSTED','No fixture response remains')
        if schema_name:result=payload(schema_name,result)
        elif not isinstance(result,str):raise AgentError('INVALID_MODEL_OUTPUT','Offline SAM fixture must be terminal grammar text')
        return dict(value=result,response_id='offline-fixture-'+str(len(self.calls)),call_id='offline-call-'+str(len(self.calls)),artifact_hash=None,usage={},usd='0',provider_mode='offline',repair_validated=False)
