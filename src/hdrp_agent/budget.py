"""Global admission ledger; unknown outcomes keep their full reservation."""
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import Decimal, ROUND_CEILING, InvalidOperation
import json

from .domain import AgentError, canonical, fingerprint
from .store import new_id, utc_now


@dataclass(frozen=True)
class Pricing:
    verified_on: str
    verified: bool = False
    currency: str = 'USD'

    def validate(self):
        try:
            age = (date.today() - date.fromisoformat(self.verified_on)).days
            valid = self.verified and 0 <= age <= 7 and self.currency=='USD'
        except (ValueError, TypeError, InvalidOperation):
            valid = False
        if not valid: raise AgentError('COST_BOUND_UNKNOWN', 'Fresh verified USD API pricing is required')

    def bound_usd(self, model, *, frames=None, images=1, max_output_tokens=4096):
        self.validate()
        # No client cap: reserve conservatively against the full model context,
        # without sending this accounting bound to the provider.
        if max_output_tokens is None:max_output_tokens=1048576
        if type(max_output_tokens) is not int or max_output_tokens not in {4096,8192,1048576}:raise AgentError('COST_BOUND_UNKNOWN','Unreviewed output token bound')
        if model == 'muse-spark-1.3':
            return Decimal(1048576) * Decimal('1.25') / 1000000 + Decimal(max_output_tokens) * Decimal('4.25') / 1000000
        if model == 'muse-spark-1.3-contributor':
            return Decimal(1048576) * Decimal('.10') / 1000000 + Decimal(max_output_tokens) * Decimal('.20') / 1000000
        if model == 'sam-3.1':
            if frames is not None:
                if type(frames) is not int or not 1 <= frames <= 15000: raise AgentError('COST_BOUND_UNKNOWN', 'Unknown video frame bound')
                return Decimal(max(50, frames)) * Decimal('.0002')
            if type(images) is not int or not 1 <= images <= 12: raise AgentError('COST_BOUND_UNKNOWN', 'Unknown image bound')
            return Decimal(images) * Decimal('.0025')
        raise AgentError('COST_BOUND_UNKNOWN', 'Unsupported pricing model')

    def usd_micro(self, usd, *, admission=True):
        if admission: self.validate()
        value = Decimal(usd)
        if not value.is_finite() or value < 0: raise AgentError('COST_BOUND_UNKNOWN', 'Invalid measured cost')
        return int((value * 1000000).to_integral_value(rounding=ROUND_CEILING))


class Budget:
    def __init__(self, store, pricing=None):
        self.store, self.pricing = store, pricing

    def state(self, conn=None):
        with self.store.tx(conn) as c:
            meta = dict(c.execute('SELECT key,value FROM meta').fetchall())
            costs = c.execute("SELECT COALESCE(SUM(CASE WHEN status='settled' THEN actual ELSE 0 END),0), COALESCE(SUM(CASE WHEN status IN ('reserved','sent','unknown') THEN reserved ELSE 0 END),0), COALESCE(SUM(CASE WHEN status='unknown' THEN reserved ELSE 0 END),0) FROM calls").fetchone()
            settled = int(meta['external_total']) + costs[0]
            available = int(meta['cap_usd_micro']) - settled - costs[1]
            try:
                if self.pricing is None: raise AgentError('COST_BOUND_UNKNOWN', 'No pricing')
                self.pricing.validate()
                priced = True
            except AgentError: priced = False
            return dict(currency='USD', cap_usd_micro=int(meta['cap_usd_micro']), settled_usd_micro=settled,
                active_reserved_usd_micro=costs[1], unknown_reserved_usd_micro=costs[2],
                available_usd_micro=available, reconciliation_state=meta['reconciliation_state'],
                live_enabled=priced and meta['reconciliation_state']=='reconciled' and available > 0)

    def confirm_balance(self, available_usd_micro, source_reference, as_of_utc):
        if type(available_usd_micro) is not int or available_usd_micro!=150_000_000 or not source_reference.strip():
            raise AgentError('INVALID_RECONCILIATION','Explicit initial remaining API balance must match the 150 USD ceiling',422)
        try:
            stamp=datetime.fromisoformat(as_of_utc.replace('Z','+00:00'))
            if stamp.tzinfo is None:raise ValueError()
        except (TypeError,ValueError):raise AgentError('INVALID_RECONCILIATION','Timezone-aware balance date required',422)
        with self.store.tx() as c:
            existing=c.execute("SELECT value FROM meta WHERE key='remaining_balance_confirmation'").fetchone()
            if existing:return self.state(c)  # Confirmation never refills an existing budget.
            if c.execute('SELECT 1 FROM calls LIMIT 1').fetchone() or c.execute('SELECT 1 FROM budget_entries LIMIT 1').fetchone():
                raise AgentError('RECONCILIATION_REQUIRED','Existing financial history must be reconciled, not reset')
            record=dict(available_usd_micro=available_usd_micro,source_reference=source_reference,as_of_utc=as_of_utc,scope='API usage charges from confirmed remaining balance; historical spend is not asserted')
            c.execute('INSERT INTO meta VALUES(?,?)',('remaining_balance_confirmation',canonical(record)))
            c.execute("UPDATE meta SET value='reconciled' WHERE key='reconciliation_state'")
            c.execute('INSERT INTO budget_entries VALUES(?,?,?,?,?,?)',(new_id('entry'),None,'remaining_balance_confirmation',available_usd_micro,canonical(record),utc_now()))
            return self.state(c)

    def reconcile(self, external_total_usd_micro, source_reference, as_of_utc, conn=None):
        if type(external_total_usd_micro) is not int or external_total_usd_micro < 0 or not source_reference.strip():
            raise AgentError('INVALID_RECONCILIATION', 'A cumulative nonnegative total and source are required', 422)
        try:
            stamp = datetime.fromisoformat(as_of_utc.replace('Z', '+00:00'))
            if stamp.tzinfo is None: raise ValueError()
        except (TypeError, ValueError): raise AgentError('INVALID_RECONCILIATION', 'A timezone-aware statement date is required', 422)
        with self.store.tx(conn) as c:
            previous = int(c.execute("SELECT value FROM meta WHERE key='external_total'").fetchone()[0])
            c.execute("UPDATE meta SET value=? WHERE key='external_total'", (str(external_total_usd_micro),))
            # An exceeded bound requires explicit resolution of its cause, not a routine reconciliation.
            c.execute("UPDATE meta SET value='reconciled' WHERE key='reconciliation_state' AND value!='violation'")
            c.execute('INSERT INTO budget_entries VALUES(?,?,?,?,?,?)', (new_id('entry'), None, 'external_adjustment', external_total_usd_micro-previous, canonical(dict(source_reference=source_reference, as_of_utc=as_of_utc, cumulative_total=external_total_usd_micro)), utc_now()))
            return self.state(c)

    def reserve(self, model, request, *, frames=None, images=1, envelope=None):
        with self.store.tx() as c:
            state = self.state(c)
            if state['reconciliation_state'] == 'required': raise AgentError('PRIOR_SPEND_UNKNOWN', 'Prior expenditure must be reconciled')
            if state['reconciliation_state'] != 'reconciled': raise AgentError('BUDGET_FROZEN', 'A financial violation requires resolution')
            if self.pricing is None: raise AgentError('COST_BOUND_UNKNOWN', 'Verified pricing is required')
            amount = self.pricing.usd_micro(self.pricing.bound_usd(model, frames=frames, images=images,max_output_tokens=request.get('max_output_tokens') if model.startswith('muse-') else 4096))
            if amount > state['available_usd_micro']: raise AgentError('BUDGET_LIMIT', 'Conservative reservation exceeds available funds', 429)
            if envelope is not None:
                name,cap = envelope
                if type(cap) is not int or not 0<=cap<=5_000_000: raise AgentError('BUDGET_LIMIT','Invalid probe phase cap',422)
                c.execute('INSERT OR IGNORE INTO budget_envelopes VALUES(?,?)',(name,cap))
                old=c.execute('SELECT cap FROM budget_envelopes WHERE name=?',(name,)).fetchone()[0]
                cap=min(cap,old)
                c.execute('UPDATE budget_envelopes SET cap=? WHERE name=?',(cap,name))
                used=c.execute("SELECT COALESCE(SUM(CASE WHEN calls.status='settled' THEN calls.actual WHEN calls.status IN ('reserved','sent','unknown') THEN calls.reserved ELSE 0 END),0) FROM calls JOIN envelope_calls ON envelope_calls.call_id=calls.id WHERE envelope_calls.name=?",(name,)).fetchone()[0]
                if used+amount>cap: raise AgentError('BUDGET_LIMIT','Persistent probe envelope is exhausted',429)
            call = dict(id=new_id('call'), model=model, payload_hash=fingerprint(request), reserved=amount)
            c.execute('INSERT INTO calls VALUES(?,?,?,?,?,?,?,?)', (call['id'], model, call['payload_hash'], 'reserved', amount, None, canonical(asdict(self.pricing)), utc_now()))
            if envelope is not None:c.execute('INSERT INTO envelope_calls VALUES(?,?)',(name,call['id']))
            self.store.event(c, call['id'], 'reserved', call)
            return call

    def _transition(self, call_id, allowed, target):
        with self.store.tx() as c:
            row = c.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
            if not row: raise AgentError('NOT_FOUND', 'Call not found', 404)
            if row['status'] not in allowed: raise AgentError('CALL_STATE_CONFLICT', 'Call cannot be transmitted or released again')
            c.execute('UPDATE calls SET status=? WHERE id=?', (target, call_id))
            self.store.event(c, call_id, target, {})

    def mark_sent(self, call_id): self._transition(call_id, {'reserved'}, 'sent')
    def mark_unknown(self, call_id): self._transition(call_id, {'sent', 'unknown'}, 'unknown')
    def release_unsent(self, call_id): self._transition(call_id, {'reserved'}, 'released')

    def settle(self, call_id, usd, source):
        if not source: raise AgentError('COST_BOUND_UNKNOWN', 'Settlement source is required')
        with self.store.tx() as c:
            row = c.execute('SELECT * FROM calls WHERE id=?', (call_id,)).fetchone()
            if not row: raise AgentError('NOT_FOUND', 'Call not found', 404)
            # Use the admitted USD pricing snapshot even if today's configuration changed.
            book = Pricing(**json.loads(row['pricing']))
            actual = book.usd_micro(Decimal(usd), admission=False)
            if row['status']=='settled':
                if row['actual'] != actual: raise AgentError('SETTLEMENT_CONFLICT', 'Conflicting settlement')
                return
            if row['status'] not in {'sent','unknown'}: raise AgentError('CALL_STATE_CONFLICT', 'Cannot settle an untransmitted call')
            c.execute("UPDATE calls SET status='settled',actual=? WHERE id=?", (actual, call_id))
            c.execute('INSERT INTO budget_entries VALUES(?,?,?,?,?,?)', (new_id('entry'), call_id, 'settlement', actual, canonical(dict(usd=str(usd), source=source)), utc_now()))
            if actual > row['reserved'] or self.state(c)['available_usd_micro'] < 0:
                c.execute("UPDATE meta SET value='violation' WHERE key='reconciliation_state'")
