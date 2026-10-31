from datetime import date
from decimal import Decimal

import pytest

from hdrp_agent.budget import Budget,Pricing
from hdrp_agent.config import Settings
from hdrp_agent.domain import AgentError
from hdrp_agent.probes import ScopedBudget,RemoteFiles,core
from hdrp_agent.store import Store


def test_probe_envelope_survives_restart_and_global_state_is_not_reset(tmp_path):
    store=Store(tmp_path/'ledger.db');book=Pricing(date.today().isoformat(),verified=True)
    budget=Budget(store,book);budget.reconcile(12_000_000,'fixture','2026-10-28T10:00:00Z')
    probe=ScopedBudget(budget,2500);call=probe.reserve('sam-3.1',{});probe.mark_sent(call['id']);probe.mark_unknown(call['id'])
    again=ScopedBudget(Budget(Store(store.path),book),2500)
    with pytest.raises(AgentError,match='envelope'):again.reserve('sam-3.1',{})
    assert again.state()['settled_usd_micro']==12_000_000


def test_unknown_prior_expenditure_blocks_probe_before_transport(tmp_path):
    settings=Settings(tmp_path,provider_mode='live',api_key='fixture',token='fixture-token')
    with pytest.raises(AgentError) as failure:core(settings,Store(settings.db_path))
    assert failure.value.code=='PRIOR_SPEND_UNKNOWN'


def test_remote_cleanup_refuses_unowned_ids_and_preserves_failure(tmp_path):
    store=Store(tmp_path/'ledger.db');files=RemoteFiles(store);deleted=[]
    with pytest.raises(AgentError):files.cleanup('file-outside',deleted.append)
    assert deleted==[]
    files.record_created('file-owned','call-fixture')
    def fail(_):raise TimeoutError()
    with pytest.raises(AgentError):files.cleanup('file-owned',fail)
    assert files.owned('file-owned')
