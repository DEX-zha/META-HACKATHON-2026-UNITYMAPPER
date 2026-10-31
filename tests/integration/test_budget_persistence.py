from datetime import date
from decimal import Decimal
import json

from fastapi.testclient import TestClient

from hdrp_agent.api import create_app
from hdrp_agent.budget import Budget, Pricing
from hdrp_agent.config import Settings
from hdrp_agent.domain import validator
from hdrp_agent.store import Store


def test_api_auth_reconciliation_retries_and_restart(tmp_path):
    settings=Settings(tmp_path,token='test-local-token')
    app=create_app(settings)
    auth={'Authorization':'Bearer '+settings.token,'Idempotency-Key':'invoice'}
    data=dict(external_total_usd_micro=1230000,source_reference='outside-ledger invoice',as_of_utc='2026-10-28T10:00:00Z')
    with TestClient(app) as client:
        assert client.get('/health').status_code==401
        assert client.get('/health',headers=auth).json()['provider_mode']=='offline'
        first=client.post('/v1/budget/reconcile',headers=auth,json=data)
        assert first.status_code==200
        validator('Budget').validate(first.json())
        assert client.post('/v1/budget/reconcile',headers=auth,json=data).json()==first.json()
        assert client.post('/v1/budget/reconcile',headers=auth,json=dict(data,external_total_usd_micro=0)).status_code==409
        assert client.get('/v1/budget',headers=auth).json()['settled_usd_micro']==1230000
    with TestClient(create_app(settings)) as client:
        assert client.get('/v1/budget',headers=auth).json()['settled_usd_micro']==1230000
        assert not client.get('/v1/budget',headers=auth).json()['live_enabled']


def test_invoice_uses_admitted_usd_snapshot_even_after_config_change(tmp_path):
    store=Store(tmp_path/'ledger.db')
    book=Pricing(date.today().isoformat(),verified=True)
    ledger=Budget(store,book);ledger.reconcile(0,'fixture','2026-10-28T10:00:00Z')
    call=ledger.reserve('muse-spark-1.3',{'invalid_json_response_still_billed':True});ledger.mark_sent(call['id'])
    ledger.pricing=None
    ledger.settle(call['id'],Decimal('.1'),'known usage on invalid JSON')
    assert ledger.state()['settled_usd_micro']==100000
    assert ledger.state()['active_reserved_usd_micro']==0


def test_service_restart_preserves_transmitted_unknown(tmp_path):
    settings=Settings(tmp_path,token='local-token')
    store=Store(settings.db_path)
    ledger=Budget(store,Pricing(date.today().isoformat(),verified=True))
    ledger.reconcile(0,'fixture','2026-10-28T10:00:00Z')
    call=ledger.reserve('sam-3.1',{});ledger.mark_sent(call['id'])
    with TestClient(create_app(settings)) as client:
        data=client.get('/v1/budget',headers={'Authorization':'Bearer '+settings.token}).json()
        assert data['unknown_reserved_usd_micro']==2500
        assert data['active_reserved_usd_micro']==2500
