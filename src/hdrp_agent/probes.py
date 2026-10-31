"""Core provider probes use actual Unity media and the shared cumulative ledger."""
from decimal import Decimal, ROUND_FLOOR
import json
from pathlib import Path

from .artifacts import ArtifactStore
from .budget import Budget
from .budget_cli import load_pricing
from .capture_validation import read_capture
from .domain import AgentError, canonical
from .providers.meta_responses import MetaResponses, spark_request, sam_request
from .providers.sam_decoder import decode


class ScopedBudget:
    def __init__(self,budget,cap):self.budget,self.cap,self.store=budget,cap,budget.store
    def reserve(self,model,request,**kwargs):return self.budget.reserve(model,request,**kwargs,envelope=('core-probes',self.cap))
    def __getattr__(self,name):return getattr(self.budget,name)


class RemoteFiles:
    """Ownership registry for optional native-video uploads, closed until cost is verified."""
    def __init__(self,store):self.store=store
    def record_created(self,file_id,call_id):
        if not file_id.startswith('file-'):raise AgentError('INVALID_PROVIDER_OUTPUT','Invalid owned file ID')
        with self.store.tx() as c:self.store.event(c,file_id,'owned_remote_file_created',dict(call_id=call_id))
    def owned(self,file_id):
        with self.store.tx() as c:return c.execute("SELECT 1 FROM events WHERE subject=? AND kind='owned_remote_file_created'",(file_id,)).fetchone() is not None
    def cleanup(self,file_id,delete_with_financial_admission):
        if not self.owned(file_id):raise AgentError('OUT_OF_SCOPE','Remote file is not owned by this agent')
        try:delete_with_financial_admission(file_id)
        except Exception:
            with self.store.tx() as c:self.store.event(c,file_id,'remote_cleanup_failed',{'retained':True})
            raise AgentError('REMOTE_CLEANUP_FAILED','Owned remote file deletion failed; audit entry retained')
        with self.store.tx() as c:self.store.event(c,file_id,'owned_remote_file_deleted',{})


def core(settings,store,max_usd='5',reuse_spark_call=None,reuse_sam_call=None):
    budget=Budget(store,load_pricing(settings.state/'pricing.json'))
    state=budget.state()
    if state['reconciliation_state']=='required':raise AgentError('PRIOR_SPEND_UNKNOWN','Explicit remaining USD budget must be confirmed before real probes')
    if not state['live_enabled']:raise AgentError('COST_BOUND_UNKNOWN','Fresh verified USD API pricing is required')
    if settings.provider_mode!='live':raise AgentError('OFFLINE_MODE','Real probes require explicit live mode')
    try:
        requested=Decimal(str(max_usd))
        if not requested.is_finite() or requested<=0:raise ValueError()
        cap=min(5_000_000,state['available_usd_micro']//10,state['available_usd_micro'],int((requested*1000000).to_integral_value(rounding=ROUND_FLOOR)))
    except (ValueError,ArithmeticError):raise AgentError('INVALID_INPUT','A positive finite probe limit is required',422)
    j0=json.loads((settings.state/'reports/j0-local-pipeline.json').read_text())
    if j0.get('capture_verified') is not True:raise AgentError('CAPABILITY_MISSING','Measured J0 capture qualification is required')
    capture=read_capture(j0['captures'][0]);front=next(f for f in capture['statics'] if f['role']=='work')
    image=(capture['directory']/front['file']).read_bytes()
    artifacts=ArtifactStore(settings.state/'artifacts',store)
    provider=MetaResponses(settings,ScopedBudget(budget,cap),artifacts)
    report=dict(schema_version='1.0',provider_mode='live',status='incomplete',native_video_verified=False,video_mode='timestamped_original_frames',native_video_limit='Upload/control-plane cost dimension is not established; no native upload is sent',remote_files_created=[],calls=[],repair_validated=False)
    path=settings.state/'reports/j1-meta-probes.json'
    if path.exists():
        from .store import new_id
        path.rename(path.with_name(new_id('j1-meta-probes')+'.json'))
    def save():path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(report,indent=2))
    save()
    try:
        prompt='Return a strict visual diagnosis of this actual Unity image. Scene version: '+capture['request']['version_id']+'. Do not claim any correction. Unknown object identities must be omitted.'
        request=spark_request(prompt,[image],'ModelDiagnosis')
        if reuse_spark_call:
            try:spark=provider.recover_completed(reuse_spark_call,request,'ModelDiagnosis')
            except AgentError as exc:
                if exc.code!='RESPONSE_RECOVERY_REFUSED':raise
                legacy=dict(request);legacy.pop('reasoning')
                spark=provider.recover_completed(reuse_spark_call,legacy,'ModelDiagnosis')
        else:spark=provider.send(request,'ModelDiagnosis')
        report['calls'].append({k:v for k,v in spark.items() if k!='value'});save()
        request=sam_request('table',image)
        sam=provider.recover_completed(reuse_sam_call,request) if reuse_sam_call else provider.send(request)
        report['calls'].append({k:v for k,v in sam.items() if k!='value'})
        regions=decode(sam['value'],1280,720)
        report['sam_decoded_regions']=len(regions)
        report['spark_strict_json_verified']=True;report['sam_decoding_verified']=bool(regions)
        # Native upload remains closed. Temporal evidence can use exact, timestamped source frames.
        indices=[0,48,96]
        frames={f['frame_index']:f for f in capture['clip']}
        if all(i in frames for i in indices):
            temporal=provider.send(spark_request('Observe these ordered original frames at t=0s, 2s, 4s from one Unity clip. Scene version: '+capture['request']['version_id']+'. Report uncertainty; sampling cannot prove absence of flicker.',[(capture['directory']/frames[i]['file']).read_bytes() for i in indices],'ModelDiagnosis'),'ModelDiagnosis')
            report['calls'].append({k:v for k,v in temporal.items() if k!='value'});report['timestamped_frame_transport_verified']=True
        report['status']='verified' if regions else 'inconclusive'
        return report
    except AgentError as exc:
        report['status']='blocked' if exc.code in {'BUDGET_LIMIT','PRIOR_SPEND_UNKNOWN','COST_BOUND_UNKNOWN'} else 'failed';report['error']=exc.as_dict();raise
    finally:
        with store.tx() as c:
            rows=c.execute("SELECT calls.id,calls.model,calls.status,calls.reserved,calls.actual FROM calls JOIN envelope_calls ON envelope_calls.call_id=calls.id WHERE envelope_calls.name='core-probes'").fetchall()
            report['all_probe_calls']=[dict(row) for row in rows]
        report['budget_after']=budget.state();save();provider.client.close()
