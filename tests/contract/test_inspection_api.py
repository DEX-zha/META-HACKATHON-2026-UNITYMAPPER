"""US1 acceptance contracts, activated when session routes are installed (T042)."""
import json
from pathlib import Path

from hdrp_agent.domain import payload, validator, CONTRACTS


def test_diagnosis_and_proposal_are_closed():
    import pytest
    from pydantic import ValidationError
    for name in ['ModelDiagnosis','ModelProposal']:
        with pytest.raises(ValidationError):payload(name,{'summary':'unproved repair','execute_csharp':'arbitrary'})
        assert validator(name).is_valid({}) is False


def test_session_and_stop_contracts_cannot_replace_frozen_criteria():
    import pytest
    from pydantic import ValidationError
    from hdrp_agent.domain import WORKSPACE
    criteria=[dict(id='visibility',kind='visibility',target='wall',method='luminance_range',minimum=.1,maximum=.9,unit='normalized',required=True)]
    request=dict(project_id='project',scene_id='scene',base_version='version',mode='inspect',brief=json.loads((WORKSPACE/'fixtures/briefs/room.json').read_text()),inspection=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text()),criteria=criteria,max_attempts=3,session_timeout_seconds=1200,bake_timeout_seconds=600,provider_mode='offline')
    assert payload('SessionCreate',request)==request
    with pytest.raises(ValidationError):payload('SessionCreate',dict(request,max_attempts=4))
    assert payload('StopRequest',{'reason':'operator'})=={'reason':'operator'}
    with pytest.raises(ValidationError):payload('StopRequest',{'reason':'operator','criteria':[]})


def test_creation_route_and_partial_report_are_durable(tmp_path):
    from fastapi.testclient import TestClient
    from hdrp_agent.api import create_app
    from hdrp_agent.config import Settings
    from hdrp_agent.domain import canonical,WORKSPACE
    app=create_app(Settings(tmp_path,token='fixture'))
    # Keep this a transport test: execution is separately exercised through the loop.
    app.state.orchestrator.run=lambda sid:None
    with app.state.store.tx() as c:
        registration=dict(scene_version='version',capabilities=['inspect','snapshot','apply_patch','restore','bake','capture'])
        c.execute('INSERT INTO projects VALUES(?,?,?)',('project','epoch',canonical(registration)))
        c.execute('INSERT INTO scenes VALUES(?,?,?)',('scene','project',canonical(registration)))
    req=dict(project_id='project',scene_id='scene',base_version='version',mode='inspect',brief=json.loads((WORKSPACE/'fixtures/briefs/room.json').read_text()),inspection=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text()),criteria=[dict(id='performance',kind='performance',target='performance',method='frame_time_regression',minimum=None,maximum=.2,unit='ratio',required=True)],max_attempts=3,session_timeout_seconds=1200,bake_timeout_seconds=600,provider_mode='offline')
    headers={'Authorization':'Bearer fixture','Idempotency-Key':'create'}
    with TestClient(app) as client:
        result=client.post('/v1/sessions',json=req,headers=headers)
        assert result.status_code==202,result.text
        session=result.json();sid=session['id']
        assert client.post('/v1/sessions',json=req,headers=headers).json()==session
        report=client.get('/v1/sessions/'+sid+'/report',headers=headers)
        assert report.status_code==200
        validator('Report').validate(report.json())
        data=client.get('/v1/artifacts/'+report.json()['report_artifact_hash'],headers=headers).json()
        assert data['repair_validated'] is False
        assert data['session']['criteria_hash']==session['criteria_hash']
        assert client.post('/v1/sessions',json=req,headers=dict(headers,**{'Idempotency-Key':'other'})).status_code==409
