"""Source-checked Contributor USD pricing; no provider inference is used here."""
from dataclasses import asdict
from datetime import date
from decimal import Decimal
import hashlib
import html
import json
import os
from pathlib import Path
import re
import tempfile

import httpx

from .budget import Budget, Pricing
from .domain import AgentError

PRICE_SOURCE = 'https://dev.meta.ai/docs/pricing-rate-limits'
MODEL_SOURCE = 'https://dev.meta.ai/docs/models'


def load_pricing(path):
    if not Path(path).is_file(): return None
    data = json.loads(Path(path).read_text())
    if data.get('currency')!='USD':return None
    return Pricing(**{k: data[k] for k in Pricing.__dataclass_fields__})


def plain(source):
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', source)))


def verify_sources(prices, models):
    p,m=plain(prices),plain(models)
    try:
        spark=p.split('Models:')[1].split('Token pricing notes')[0]
        sam=p.split('segmentation is billed')[1].split('Rate limits')[0]
        for label,standard,contributor in [('Cached input','0.15','0.002'),('Input','1.25','0.10'),('Output','4.25','0.20')]:
            if not re.search(r'\b'+label+r'\s+\$'+re.escape(standard)+r'\s+\$'+re.escape(contributor)+r'\b',spark):raise ValueError()
        if not all(s in sam for s in ['$2.50','$0.20','50']):raise ValueError()
        if '1,048,576-token context window' not in m.split('Muse Spark is Meta')[1] or 'muse-spark-1.3-contributor' not in m:raise ValueError()
    except (ValueError,IndexError) as exc:raise AgentError('COST_BOUND_UNKNOWN','Official Contributor pricing or context no longer matches the reviewed USD profile') from exc


def refresh(path):
    with httpx.Client(timeout=30,follow_redirects=False,transport=httpx.HTTPTransport(retries=0)) as client:
        responses=[client.get(url) for url in [PRICE_SOURCE,MODEL_SOURCE]]
        for response in responses:response.raise_for_status()
    verify_sources(*(response.text for response in responses))
    book=Pricing(date.today().isoformat(),verified=True);book.validate()
    data=dict(asdict(book),selected_model='muse-spark-1.3-contributor',scope='API usage charges in USD against confirmed remaining balance',sources=[dict(url=str(r.url),sha256=hashlib.sha256(r.content).hexdigest()) for r in responses])
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    fd,tmp=tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd,'w') as f:json.dump(data,f,indent=2);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)
    return data


def add_commands(commands):
    budget = commands.add_parser('budget', help='Persistent 150 USD remaining API budget')
    b = budget.add_subparsers(dest='budget_action', required=True)
    b.add_parser('show')
    reconcile = b.add_parser('reconcile', help='Replace cumulative spending outside this ledger')
    reconcile.add_argument('--external-total-usd-micro', type=int, required=True)
    reconcile.add_argument('--source', required=True)
    reconcile.add_argument('--as-of', required=True)
    balance=b.add_parser('confirm-balance',help='Record an explicitly declared initial remaining USD balance once, without refilling it')
    balance.add_argument('--available-usd-micro',type=int,required=True);balance.add_argument('--source',required=True);balance.add_argument('--as-of',required=True)
    pricing = commands.add_parser('pricing', help='Verify current official rates and exchange source')
    p = pricing.add_subparsers(dest='pricing_action', required=True).add_parser('refresh')


def execute(args, settings, store):
    path = settings.state / 'pricing.json'
    if args.command == 'pricing': return refresh(path)
    budget = Budget(store, load_pricing(path))
    if args.budget_action == 'show': return budget.state()
    if args.budget_action=='confirm-balance':return budget.confirm_balance(args.available_usd_micro,args.source,args.as_of)
    return budget.reconcile(args.external_total_usd_micro, args.source, args.as_of)
