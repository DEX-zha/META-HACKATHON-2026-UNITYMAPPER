from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal

import pytest

from hdrp_agent.budget import Budget, Pricing
from hdrp_agent.domain import AgentError
from hdrp_agent.store import Store


@pytest.fixture
def book():
    return Pricing(verified_on=date.today().isoformat(), verified=True)


def test_prior_spend_is_never_assumed_zero(tmp_path, book):
    budget = Budget(Store(tmp_path / "ledger.db"), book)
    assert budget.state()["reconciliation_state"] == "required"
    with pytest.raises(AgentError, match="Prior"):
        budget.reserve("sam-3.1", {"image": "x"})


def test_context_bound_and_minimum_video_frames(book):
    assert book.bound_usd("muse-spark-1.3") == Decimal("1.328128")
    assert book.bound_usd("sam-3.1", frames=1) == Decimal("0.01")
    assert book.bound_usd("sam-3.1", frames=15000) == Decimal("3")
    assert book.bound_usd('muse-spark-1.3-contributor',max_output_tokens=8192)==Decimal('.106496')
    with pytest.raises(AgentError):book.bound_usd('muse-spark-1.3-contributor',max_output_tokens=8193)


def test_timeout_survives_restart_and_is_not_double_counted(tmp_path, book):
    path = tmp_path / "ledger.db"
    budget = Budget(Store(path), book)
    budget.reconcile(10_000_000, "invoice", "2026-10-28T10:00:00Z")
    call = budget.reserve("sam-3.1", {"image": "x"})
    budget.mark_sent(call["id"])
    budget.mark_unknown(call["id"])
    after = Budget(Store(path), book).state()
    assert after["settled_usd_micro"] == 10_000_000
    assert after["active_reserved_usd_micro"] == 2500
    assert after["unknown_reserved_usd_micro"] == 2500
    assert after["available_usd_micro"] == 139_997_500
    with pytest.raises(AgentError): budget.mark_sent(call["id"])


def test_atomic_admission(tmp_path, book):
    budget = Budget(Store(tmp_path / "ledger.db"), book)
    budget.reconcile(149_997_500, "invoice", "2026-10-28T10:00:00Z")
    def attempt(i):
        try: return budget.reserve("sam-3.1", {"image": str(i)})["id"]
        except AgentError as e: return e.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, [1, 2]))
    assert results.count("BUDGET_LIMIT") == 1
    assert budget.state()["available_usd_micro"] == 0


def test_settlement_replaces_reservation_and_external_is_cumulative(tmp_path, book):
    budget = Budget(Store(tmp_path / "ledger.db"), book)
    for _ in range(2): budget.reconcile(10_000_000, "same invoice", "2026-10-28T10:00:00Z")
    call = budget.reserve("muse-spark-1.3", {"image": "x"})
    budget.mark_sent(call["id"])
    budget.settle(call["id"], Decimal("0.01"), "response-1")
    state = budget.state()
    assert state["active_reserved_usd_micro"] == 0
    assert state["settled_usd_micro"] == 10_010_000
    budget.settle(call["id"], Decimal("0.01"), "response-1")
    assert budget.state() == state


def test_unknown_or_unverified_cost_is_blocked(tmp_path):
    budget = Budget(Store(tmp_path / "ledger.db"), None)
    budget.reconcile(0, "explicit fixture", "2026-10-28T10:00:00Z")
    with pytest.raises(AgentError) as e: budget.reserve("sam-3.1", {})
    assert e.value.code == "COST_BOUND_UNKNOWN"


def test_over_reservation_invoice_records_truth_and_disables_live(tmp_path, book):
    budget = Budget(Store(tmp_path / "ledger.db"), book)
    budget.reconcile(0, "explicit fixture", "2026-10-28T10:00:00Z")
    call = budget.reserve("sam-3.1", {})
    budget.mark_sent(call["id"])
    budget.settle(call["id"], Decimal("0.1"), "invoice")
    assert budget.state()["settled_usd_micro"] == 100000
    assert budget.state()["reconciliation_state"] == "violation"


def test_round_up_not_float(book):
    assert book.usd_micro(Decimal("0.00000001")) == 1


def test_confirmed_remaining_balance_is_recorded_once_and_never_refills(tmp_path,book):
    store=Store(tmp_path/'ledger.db');budget=Budget(store,book)
    budget.confirm_balance(150_000_000,'user: 150 USD still available','2026-10-28T18:00:00Z')
    call=budget.reserve('muse-spark-1.3-contributor',{});budget.mark_sent(call['id']);budget.settle(call['id'],Decimal('.01'),'fixture usage')
    budget.confirm_balance(150_000_000,'same user confirmation repeated','2026-10-28T19:00:00Z')
    assert budget.state()['available_usd_micro']==149_990_000
    assert budget.state()['currency']=='USD'
    assert book.bound_usd('muse-spark-1.3-contributor')==Decimal('.1056768')
