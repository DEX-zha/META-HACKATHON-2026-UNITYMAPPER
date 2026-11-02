"""House v1 admission and durable execution, separate from the legacy reconstructor."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import time
import uuid
from copy import deepcopy
from pathlib import Path
from .house_convergence import converge, signature
from .house_media import inspection_batches
from .house_memory import HouseMemory
from .house_activity import model_summary
from PIL import Image
from .domain import AgentError, canonical, fingerprint, payload
from .store import utc_now
from .house_store import HouseStore
from .house_planning import building_from_outline, place_groups
from .house_briefing import room_prompt, RENDER_REFERENCE_POLICY
from .house_lighting_reference import load_reference
from .house_zones import assemble as assemble_zones
from .house_vision import concepts as segmentation_concepts, overlay as segmentation_overlay
from .budget import Budget
from .budget_cli import load_pricing
from .providers.meta_responses import MetaResponses, spark_request, sam_request


class HouseCallBudget:
    def __init__(self, service, run, key):
        self.service,self.run,self.key=service,run,key
        self.budget=Budget(service.store,load_pricing(service.settings.state/'pricing.json'))
    def __getattr__(self,name):return getattr(self.budget,name)
    def reserve(self,*args,**kwargs):
        call=self.budget.reserve(*args,**kwargs)
        with self.service.store.tx() as c:
            c.execute('UPDATE house_calls SET call_id=? WHERE run_id=? AND key=?',(call['id'],self.run,self.key))
        return call


class HouseService:
    def __init__(self,settings,store,queue,artifacts,shutdown,provider_factory=MetaResponses):
        self.settings,self.store,self.queue,self.artifacts,self.shutdown=settings,store,queue,artifacts,shutdown
        self.houses=HouseStore(store);self.provider_factory=provider_factory
        with store.tx() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS house_actions(id TEXT PRIMARY KEY,run_id TEXT UNIQUE NOT NULL,session_id TEXT UNIQUE NOT NULL,project_id TEXT NOT NULL,idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL,request TEXT NOT NULL,state TEXT NOT NULL,checkpoint TEXT NOT NULL,UNIQUE(project_id,idempotency_key))''')
            c.execute('''CREATE TABLE IF NOT EXISTS house_calls(run_id TEXT NOT NULL,key TEXT NOT NULL,request_hash TEXT NOT NULL,call_id TEXT,value TEXT,PRIMARY KEY(run_id,key))''')
    def owns(self,action):
        with closing(self.store.connect()) as c:return c.execute('SELECT 1 FROM house_actions WHERE id=?',(action,)).fetchone() is not None
    def row(self,action):
        with closing(self.store.connect()) as c:row=c.execute('SELECT * FROM house_actions WHERE id=?',(action,)).fetchone()
        if not row:raise AgentError('NOT_FOUND','House action not found',404)
        return dict(row)
    def save(self,row,stage,message,**updates):
        checkpoint=json.loads(row['checkpoint']);checkpoint.update(updates,stage=stage,message=message,updated_at=utc_now());row['checkpoint']=canonical(checkpoint)
        with self.store.tx() as c:
            c.execute('UPDATE house_actions SET checkpoint=? WHERE id=?',(row['checkpoint'],row['id']))
            self.store.event(c,row['id'],'house.progress',dict(run_id=row['run_id'],stage=stage,message=message))
        HouseMemory(self.settings.state,row['run_id']).state(checkpoint)
        return checkpoint
    def activity(self, row):
        with closing(self.store.connect()) as c:
            events=c.execute("SELECT id,kind,body,created_at FROM events WHERE subject=? AND kind IN ('house.progress','house.decision') ORDER BY id",(row['id'],)).fetchall()
        return [dict(id=e['id'],kind=e['kind'],timestamp=e['created_at'],**json.loads(e['body'])) for e in events]

    def recovery(self, row):
        if row['state']!='recovery_required':return None
        with closing(self.store.connect()) as c:
            command=c.execute("SELECT * FROM commands WHERE session_id=? AND status='unknown' ORDER BY rowid DESC LIMIT 1",(row['session_id'],)).fetchone()
            project=c.execute('SELECT body FROM projects WHERE id=?',(row['project_id'],)).fetchone()
        detail=dict(cause='UNVERIFIED_NATIVE_OUTCOME',message='Unity command outcome is unverified. Execution is paused; no command has been replayed.',next_step='Inspect the native receipt and generated scene before reconciliation.',automatic_retry=False)
        if not command:return detail
        detail['command_id']=command['id']
        # Read only a matching local receipt. An unknown receipt never proves completion.
        try:
            root=self.settings.project_path(json.loads(project['body'])['project_root'])
            path=root/'.hdrp-agent'/'bridge'/'receipts'/(command['id']+'.json')
            if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink() or path.stat().st_size>1000000:return detail
            receipt=json.loads(path.read_text());result=receipt.get('result') or {}
            if all(receipt.get(k)==v for k,v in [('command_id',command['id']),('payload_hash',command['payload_hash']),('bridge_epoch',command['epoch'])]) and result.get('status')=='unknown' and result.get('error',{}).get('code')=='DOMAIN_RELOAD':
                detail.update(cause='DOMAIN_RELOAD',message='Unity reloaded its scripts during construction. The partial scene has not been verified.',next_step='Inspect the partial generated scene and reconcile the interrupted command before starting another run.')
        except (OSError,ValueError,KeyError,AgentError):pass
        return detail

    def admit(self,request):
        request=payload('AppActionRequest',request)
        if request['kind']!='generate_house':raise AgentError('INVALID_INPUT','Expected generate_house')
        digest=fingerprint(request)
        with self.store.tx() as c:
            old=c.execute('SELECT * FROM house_actions WHERE id=? OR (project_id=? AND idempotency_key=?)',(request['action_id'],request['project_id'],request['idempotency_key'])).fetchall()
            if old:
                if len(old)!=1 or old[0]['request_hash']!=digest:raise AgentError('IDEMPOTENCY_CONFLICT','House action content changed')
                action=old[0]['id']
            else:
                if c.execute('SELECT 1 FROM app_actions WHERE id=?',(request['action_id'],)).fetchone():raise AgentError('IDEMPOTENCY_CONFLICT','Action ID is already owned by legacy mode')
                project=c.execute('SELECT * FROM projects WHERE id=?',(request['project_id'],)).fetchone()
                if not project:raise AgentError('NOT_FOUND','Project not registered',404)
                data=json.loads(project['body']);self.settings.project_path(data['project_root'])
                if 'build_house' not in data.get('capabilities',[]):raise AgentError('CAPABILITY_MISSING','Unity House v1 builder is not connected')
                if request['expected_scene_version']!=data['scene_version']:raise AgentError('STALE_VERSION','Unity scene changed')
                presence=c.execute('SELECT * FROM project_presence WHERE project_id=?',(request['project_id'],)).fetchone()
                if not presence or presence['epoch']!=project['epoch'] or datetime.fromisoformat(presence['last_seen'].replace('Z','+00:00'))<datetime.now(timezone.utc)-timedelta(seconds=15):raise AgentError('EDITOR_UNAVAILABLE','Unity is not connected')
                if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached')").fetchone():raise AgentError('SESSION_ACTIVE','Another run owns the editor')
                refs=request['parameters']['reference_hashes']
                if len(refs)!=len(set(refs)) or set(refs)!=set(request['artifact_hashes']):raise AgentError('INVALID_INPUT','Reference hashes differ')
                if request['parameters']['creative_policy']=='reference_guided' and not refs:raise AgentError('INVALID_INPUT','Reference-guided mode needs a reference')
                for h in refs:
                    if not c.execute('SELECT 1 FROM app_artifacts WHERE project_id=? AND artifact_hash=?',(request['project_id'],h)).fetchone():raise AgentError('PROJECT_MISMATCH','Unowned reference')
                budget=Budget(self.store,load_pricing(self.settings.state/'pricing.json'))
                if self.settings.provider_mode!='live' or not self.settings.api_key or not budget.state(c)['live_enabled']:raise AgentError('COST_BOUND_UNKNOWN','Reconciled live budget required')
                run=uuid.uuid4().hex;sid='house-'+run;scene='house-scene-'+run
                session=payload('Session',dict(id=sid,state='preflight',verdict='pending',best_version=request['expected_scene_version'],current_version=request['expected_scene_version'],attempts_used=0,max_attempts=6,criteria_hash=fingerprint(request['parameters']),inspection_hash=fingerprint({}),stop_reason=None,provider_mode='live'))
                c.execute('INSERT INTO scenes VALUES(?,?,?)',(scene,request['project_id'],canonical(dict(kind='house_v1'))))
                c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',(sid,request['project_id'],scene,'preflight',canonical(session)))
                checkpoint=dict(stage='queued',message='House program queued',epoch=project['epoch'],source_version=data['scene_version'],quality_state='pending',updated_at=utc_now())
                c.execute('INSERT INTO house_actions VALUES(?,?,?,?,?,?,?,?,?)',(request['action_id'],run,sid,request['project_id'],request['idempotency_key'],digest,canonical(request),'queued',canonical(checkpoint)))
                action=request['action_id']
        return self.get(action)
    def get(self,action):
        row=self.row(action);r=json.loads(row['request']);cp=json.loads(row['checkpoint'])
        with closing(self.store.connect()) as c:stopped=bool(c.execute('SELECT stop_requested FROM sessions WHERE id=?',(row['session_id'],)).fetchone()[0])
        progress=dict(phase=cp['stage'],message=cp['message'],last_evidence_at=cp.get('last_evidence_at',cp['updated_at']),preview_images=0,render_receipts=len(cp.get('captures',[])),source='house_v1',correction_round=max([i['iteration'] for i in cp.get('iterations',[])]+[0]))
        progress['activity']=self.activity(row)
        progress['recovery']=self.recovery(row)
        native=self.settings.state/'house'/'runs'/row['run_id']/cp.get('manifest_hash','')[:12]/'progress.json'
        if cp['stage']=='building' and native.is_file() and not native.is_symlink() and native.resolve().is_relative_to(self.settings.state.resolve()) and native.stat().st_size<1000000:
            observed=json.loads(native.read_text())
            if observed.get('run_id')==row['run_id']:progress.update(message=observed['message'],render_receipts=observed['captured'],last_evidence_at=observed['updated_at'])
        return dict(progress=progress,action_id=action,project_id=row['project_id'],conversation_id=r['conversation_id'],message_id=r['message_id'],operation_id='house-operation-'+row['run_id'],session_id=row['session_id'],run_id=row['run_id'],state=row['state'],stop_requested=stopped,evidence_hashes=cp.get('evidence_hashes',[]),error_code=cp.get('error_code'),execution_state=cp.get('execution_state',row['state']),quality_state=cp.get('quality_state','pending'),stage=cp['stage'],message=cp['message'])
    def progress(self,action):
        row=self.row(action);cp=json.loads(row['checkpoint']);out=self.get(action)
        try:out['house']=self.houses.snapshot(row['run_id'])
        except AgentError:out['house']=None
        out.update(current_scope=cp.get('current_scope'),scene_path=cp.get('scene_path'),scene_version=cp.get('scene_version'),last_evidence_at=cp.get('last_evidence_at'),unresolved=cp.get('unresolved',[]),captures=cp.get('captures',[]),iterations=cp.get('iterations',[]),stop_reason=cp.get('stop_reason'),correction_blockers=cp.get('correction_blockers',[]),zone_history=cp.get('zone_history',[]),segmentations=cp.get('segmentations',[]),updated_at=cp['updated_at'])
        return out
    def guard(self,row):
        if self.shutdown.is_set():raise AgentError('SERVICE_STOPPING','House service is stopping')
        with closing(self.store.connect()) as c:
            session=c.execute('SELECT state,stop_requested FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
            project=c.execute('SELECT epoch FROM projects WHERE id=?',(row['project_id'],)).fetchone()
        if session['stop_requested']:raise AgentError('STOP_REQUESTED','House generation stopped by user')
        if session['state']=='recovery_required' or project['epoch']!=json.loads(row['checkpoint'])['epoch']:raise AgentError('RECOVERY_REQUIRED','Unity epoch or native receipt needs reconciliation')
    def next_ready(self):
        with self.store.tx() as c:
            row=c.execute("SELECT * FROM house_actions WHERE state='queued' ORDER BY rowid LIMIT 1").fetchone()
            if not row:return None
            c.execute("UPDATE house_actions SET state='running' WHERE id=?",(row['id'],));return row['id']
    def ask(self,row,key,text,schema,images=()):
        self.save(row,json.loads(row['checkpoint'])['stage'],'Muse is reviewing '+key)
        value=self.provider_call(row,key,spark_request(text,list(images),schema),schema)
        summary=model_summary(schema,value)
        if summary:
            with self.store.tx() as c:
                self.store.event(c,row['id'],'house.decision',dict(stage=key,message=summary,source='structured_model_output',status='proposal_or_observation'))
        HouseMemory(self.settings.state,row['run_id']).note(key,value)
        return value
    def provider_call(self,row,key,request,schema=None):
        self.guard(row);digest=fingerprint(request)
        with self.store.tx() as c:
            prior=c.execute('SELECT * FROM house_calls WHERE run_id=? AND key=?',(row['run_id'],key)).fetchone()
            if prior and prior['request_hash']!=digest:raise AgentError('STALE_EVIDENCE','Provider job input changed')
            if prior and prior['value']:return json.loads(prior['value'])
            if not prior:c.execute('INSERT INTO house_calls VALUES(?,?,?,NULL,NULL)',(row['run_id'],key,digest))
        provider=self.provider_factory(self.settings,HouseCallBudget(self,row['run_id'],key),self.artifacts)
        try:
            if prior and prior['call_id']:
                response=provider.recover_completed(prior['call_id'],request,schema)
            else:response=provider.send(request,schema)
            with self.store.tx() as c:c.execute('UPDATE house_calls SET value=? WHERE run_id=? AND key=?',(canonical(response['value']),row['run_id'],key))
            return response['value']
        finally:provider.client.close()
    def reference_context(self,row):
        with closing(self.store.connect()) as c:
            project=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(row['project_id'],)).fetchone()[0])
        return load_reference(self.settings.state,self.settings.project_path(project['project_root']))

    def catalogue(self):
        with closing(self.store.connect()) as c:rows=c.execute('SELECT body FROM asset_semantics').fetchall()
        assets={}
        for r in rows:
            a=json.loads(r[0])
            if a['prefab_path'].startswith(('Assets/AtmosphericHouse/Prefabs/','Assets/HouseProps/Prefabs/')):
                name=a['prefab_path'].rsplit('/',1)[-1].removesuffix('.prefab')
                if a['prefab_path'].startswith('Assets/HouseProps/'):name='HouseProps/'+name
                if name in assets and assets[name]['dependency_hash']!=a['dependency_hash']:raise AgentError('SEMANTICS_UNQUALIFIED','Multiple catalogue versions need remeasurement: '+name)
                assets[name]=a
        return assets
    def native(self,row,manifest):
        self.guard(row);cp=json.loads(row['checkpoint']);h=self.artifacts.put(canonical(manifest).encode(),'application/json')
        command_id='house-build-'+row['run_id']+'-'+h[:12]
        with self.store.tx() as c:
            old=c.execute('SELECT * FROM commands WHERE id=?',(command_id,)).fetchone()
            if not old:
                body=dict(run_id=row['run_id'],manifest_hash=h)
                command=dict(id=command_id,session_id=row['session_id'],kind='build_house',expected_version=cp['source_version'],payload_hash=fingerprint(body),payload=body,deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat(),bridge_epoch=cp['epoch'])
                self.queue.enqueue(row['project_id'],command,c)
        self.save(row,'building','Unity is assembling prefabs and checking geometry',native_command=command_id,manifest_hash=h)
        while True:
            with closing(self.store.connect()) as c:command=c.execute('SELECT * FROM commands WHERE id=?',(command_id,)).fetchone()
            if command['result']:
                result=json.loads(command['result'])
                if result['status']!='succeeded':raise AgentError((result.get('error') or {}).get('code','NATIVE_FAILED'),(result.get('error') or {}).get('message','Native build failed'))
                if not result.get('details_artifact_hash'):raise AgentError('EVIDENCE_MISSING','Native house receipt missing')
                proof=json.loads(self.artifacts.read(result['details_artifact_hash']))
                if proof.get('run_id')!=row['run_id'] or proof.get('manifest_hash')!=h:raise AgentError('STALE_EVIDENCE','Native receipt belongs to another manifest')
                return result,proof
            if command['status'] in {'unknown','cancelled','failed'}:raise AgentError('RECOVERY_REQUIRED','Native command requires reconciliation')
            self.guard(row);time.sleep(.25)
    def run(self,action):
        row=self.row(action);params=json.loads(row['request'])['parameters'];run=row['run_id']
        try:
            self.save(row,'outline','Muse is planning the requested rooms and activities')
            images=[]
            for h in params['reference_hashes']:
                with Image.open(io.BytesIO(self.artifacts.read(h))) as im:
                    im=im.convert('RGB');im.thumbnail((1280,720));buf=io.BytesIO();im.save(buf,format='PNG');images.append(buf.getvalue())
            outline=self.ask(row,'outline','Design a complete Unity house program from this brief. Preserve every requested room and floor; never omit an unsupported need. Give distinct stable room IDs. Dimensions in metres, prefer multiples of 3 compatible with native tiles. Hidden parts are creative and must follow brief. Native prefab contact checks, circulation inspection and SAM/Muse image review are provided by this pipeline; do not list those inspection requests as unsupported building features. Return unresolved architectural or furnishing requirements explicitly. User reference data: '+canonical(params),'ModelHouseOutline',images)
            building=building_from_outline(outline);assets=self.catalogue();designs=[];requirements=[];instances=[];missing=list(outline['unresolved']);access=[]
            for room in outline['rooms']:
                self.guard(row);self.save(row,'furnishing','Furnishing '+room['purpose'],current_scope=room['id'])
                design=self.ask(row,'room-'+room['id'],room_prompt(dict(room,geometry=next(r for r in building['rooms'] if r['id']==room['id']),portals=building['portals']),params['brief'],assets)+' Native lighting reference data: '+canonical(self.reference_context(row)),'ModelHouseRoomV2',images)
                if design['room_id']!=room['id'] or len({g['id'] for g in design['groups']})!=len(design['groups']):raise AgentError('INVALID_MODEL_OUTPUT','Room scope or group identity differs')
                placed=place_groups(building,design,assets);designs.append(dict(design=design,placement=placed))
                requirements.extend(placed['requirements']);instances.extend(placed['instances']);missing.extend(placed['missing']);missing.extend(design['unresolved']);access.append(dict(room_id=room['id'],points=placed['access_points']))
            if not requirements:raise AgentError('PROGRAM_INCOMPLETE','No supported functional requirements')
            program=dict(id='house',project_id=row['project_id'],run_id=run,brief=params['brief'],creative_policy=params['creative_policy'],reference_hashes=params['reference_hashes'],rooms=[dict(id=r['id'],floor_id='ground',purpose=r['purpose']) for r in outline['rooms']],requirements=requirements)
            self.houses.create(program,building)
            manifest=dict(schema_version='house-manifest.v1',run_id=run,building=building,instances=instances,access=access,interior_style=params['interior_style'],lighting='warm_interior',designs=designs,exposure_ev=6)
            self.save(row,'building','Metric plan ready; native assembly',unresolved=missing)
            def zone_inspect(candidate,evidence,room,zone):
                scoped=dict(outline,rooms=[r for r in outline['rooms'] if r['id']==room])
                return self.inspect(row,scoped,candidate['instances'],evidence,persist=False)
            def zone_record(room,zone,status,evidence):
                cp=json.loads(row['checkpoint']);history=cp.get('zone_history',[])
                history.append(dict(room_id=room,zone_id=zone,status=status,scene_path=(evidence or {}).get('scene_path')))
                self.save(row,'building','Zone '+zone+' : '+status,current_scope=room,zone_history=history)
            def zone_repair(candidate,receipt,evidence,observations,room,zone):
                def audit(index,status,patch,r,p):zone_record(room,zone,'repair_'+status,p)
                result=converge(candidate,receipt,evidence,observations,build=lambda c:self.native(row,c),inspect=lambda c,p:zone_inspect(c,p,room,zone),enrich=lambda *a:None,record=audit,guard=lambda:self.guard(row),reconsider=lambda c,p:self.replan_repairs(row,outline,assets,c,p))
                return result[:4]
            manifest,receipt,proof=assemble_zones(manifest,build=lambda c:self.native(row,c),inspect=zone_inspect,repair=zone_repair,record=zone_record,guard=lambda:self.guard(row))
            instances=manifest['instances']
            self.save(row,'inspection','Checking views and equipment',scene_path=proof['scene_path'],scene_version=proof['scene_version'],captures=proof.get('captures',[]),evidence_hashes=receipt['artifact_hashes'],last_evidence_at=utc_now())
            actual={i['id']:i for i in proof.get('instances',[])}
            resolved=[];unresolved=[]
            for r in requirements:
                native=actual.get(r['id'])
                if native and native.get('connected') and native.get('native_scale') and native.get('support_passed'):
                    resolved.append(dict(r,status='satisfied',fulfilled_by=[r['id']],evidence_ids=[receipt['details_artifact_hash']]))
                else:unresolved.append(r['id'])
            self.houses.reconcile_batch(run,[r['id'] for r in requirements],resolved,unresolved)
            for i,item in enumerate(missing+proof.get('defects',[])):
                self.houses.defect(run,dict(id='native-'+str(i),scope_id='house',severity='warning' if isinstance(item,dict) and item.get('priority') in {'preferred','optional'} else 'blocking',gate='completeness',message=canonical(item),evidence_ids=[receipt['details_artifact_hash']]))
            # Geometry, visual evidence and artistic acceptance are distinct gates.
            for gate,passed in [('traversal',proof.get('traversal_qualified') and proof.get('portal_qualified')),('lighting',proof.get('lighting_qualified')),('coverage',all(c.get('coverage_qualified') for c in proof.get('captures',[])) and bool(proof.get('captures')))]:
                if not passed:self.houses.defect(run,dict(id='gate-'+gate,scope_id='house',severity='blocking',gate=gate,message='Native qualification pending: '+gate,evidence_ids=[receipt['details_artifact_hash']]))
            observations=self.inspect(row,outline,instances,proof)
            selected={'receipt':receipt,'proof':proof}
            def inspect_candidate(candidate,evidence):return self.inspect(row,outline,candidate['instances'],evidence,persist=False)
            def record(index,status,patch,candidate_receipt,candidate_proof):
                cp=json.loads(row['checkpoint']);history=cp.get('iterations',[])
                event=dict(iteration=index,status=status,patch=patch,scope_id=patch.get('scope_id','house'),defect_ids=[d['id'] for d in self.houses.snapshot(run)['defects'] if d['scope_id']==patch.get('scope_id','house') and d['status']!='resolved'],scene_path=candidate_proof['scene_path'],scene_version=candidate_proof['scene_version'],receipt_hash=candidate_receipt['details_artifact_hash'])
                history.append(event)
                with self.store.tx() as c:
                    c.execute('INSERT OR REPLACE INTO house_patches VALUES(?,?,?)',(run,str(index)+'-'+status,canonical(event)))
                if status=='accepted':selected.update(receipt=candidate_receipt,proof=candidate_proof)
                best=selected['proof']
                self.save(row,'correcting','Correction '+str(index)+' : '+{'proposed':'trial in progress','accepted':'improvement retained','rejected':'regression or no progress; candidate rejected'}[status],iterations=history,scene_path=best['scene_path'],scene_version=best['scene_version'],captures=best['captures'])
            manifest,receipt,proof,observations,stop_reason=converge(manifest,receipt,proof,observations,build=lambda candidate:self.native(row,candidate),inspect=inspect_candidate,enrich=lambda m,p,o,a:self.enrich(row,outline,assets,m,p,o,a),record=record,guard=lambda:self.guard(row),reconsider=lambda c,p:self.replan_repairs(row,outline,assets,c,p))
            blockers=[]
            for observation in observations:
                action=observation.get('suggested_action','none')
                reason=('Operation '+action+' is not implemented in the correction loop' if action in {'replace','reframe','measure'} else 'Lighting/bake not qualified; exposure correction alone is insufficient' if observation.get('kind')=='lighting' else 'No new safe proposal after checks and replanning')
                blockers.append(dict(room_id=observation['room_id'],instance_id=observation.get('instance_id'),defect=observation['message'],reason=reason))
            self.save(row,'correcting','Correction summary and remaining blockers',correction_blockers=blockers)
            self.reconcile_selected(row,receipt,proof,observations)
            segmentation_hash=json.loads(row['checkpoint']).get('segmentation_receipts',{}).get(proof['scene_version'])
            self.save(row,'inspection','Restoring evidence for the retained candidate',segmentations=json.loads(self.artifacts.read(segmentation_hash)) if segmentation_hash else [])
            self.save(row,'inspection','Latest candidate retained after corrections',scene_path=proof['scene_path'],scene_version=proof['scene_version'],captures=proof.get('captures',[]),evidence_hashes=receipt['artifact_hashes'],manifest_hash=proof['manifest_hash'],stop_reason=stop_reason)
            quality=self.houses.finish(run)
            self.save(row,'finished',('Stopped without convergence: no new safe correction; review remaining requirements and defects' if quality=='incomplete' else 'Corrections verified; artistic review required'),execution_state='stalled' if quality=='incomplete' else 'finished',quality_state=quality)
            with self.store.tx() as c:
                c.execute("UPDATE house_actions SET state='completed' WHERE id=?",(action,));self.store.update_session(c,row['session_id'],state='completed',verdict='inconclusive',stop_reason='House quality: '+quality)
        except Exception as exc:
            code=exc.code if isinstance(exc,AgentError) else 'HOUSE_FAILED';message=exc.message if isinstance(exc,AgentError) else str(exc)
            self.save(row,'paused',message,error_code=code,quality_state='incomplete',execution_state='paused')
            with self.store.tx() as c:
                c.execute("UPDATE commands SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE session_id=? AND status IN ('queued','claimed','running')",(row['session_id'],))
                uncertain=c.execute("SELECT 1 FROM commands WHERE session_id=? AND status IN ('claimed','running','unknown')",(row['session_id'],)).fetchone()
                state='recovery_required' if uncertain else 'failed'
                c.execute('UPDATE house_actions SET state=? WHERE id=?',(state,action))
                self.store.update_session(c,row['session_id'],state='recovery_required' if uncertain else 'interrupted',verdict='inconclusive',stop_reason=code+': '+message)
    def inspect(self,row,outline,instances,proof,*,persist=True):
        from .providers.sam_decoder import decode
        run=row['run_id'];segments=[];observations=[];assets=self.catalogue();overlays={}
        for room in outline['rooms']:
            captures=[c for c in proof.get('captures',[]) if c['room_id']==room['id'] and c.get('usable')]
            if not captures:
                if persist:self.houses.defect(run,dict(id='coverage-'+room['id'],scope_id=room['id'],severity='blocking',gate='coverage',message='No usable interior observation',evidence_ids=[]))
                observations.append(dict(room_id=room['id'],instance_id='',kind='occlusion',severity='blocking',message='No usable interior observation',suggested_action='reframe',translation_m=[0,0,0],yaw_delta=0,evidence_ids=[]));continue
            for c in captures:
                self.save(row,'inspection','SAM is analyzing visible objects: '+room['id']+' / '+c['key'],current_scope=room['id'])
                binary=self.artifacts.read(c['artifact_hash'])
                with Image.open(io.BytesIO(binary)) as im:width,height=im.size
                local=[i for i in instances if i['room_id']==room['id']]
                for concept in segmentation_concepts(local,assets):
                    self.guard(row)
                    text=self.provider_call(row,'sam-'+c['artifact_hash']+'-'+fingerprint(concept)[:12],sam_request(concept,binary))
                    regions=decode(text,width,height)
                    for region in regions:region['mask_artifact_hash']=self.artifacts.put(region.pop('mask_png'),'image/png')
                    segments.append(dict(capture_hash=c['artifact_hash'],scene_version=proof['scene_version'],room_id=room['id'],concept=concept,regions=regions))
                composite=segmentation_overlay(binary,[r for s in segments if s['capture_hash']==c['artifact_hash'] for r in s['regions']],self.artifacts.read)
                overlays[c['artifact_hash']]=composite
                if c.get('file'):
                    relative=Path(c['file'])
                    if len(relative.parts)==2 and all(ch in '0123456789abcdef' for ch in relative.parts[0]) and relative.name.startswith('view-') and relative.suffix=='.png':
                        destination=self.settings.state/'house'/'runs'/run/relative.parent/('sam-'+relative.name)
                        destination.parent.mkdir(parents=True,exist_ok=True)
                        temporary=destination.with_suffix('.tmp');temporary.write_bytes(composite);temporary.replace(destination)
                self.save(row,'inspection','SAM masks saved: '+room['id'],segmentations=segments,last_evidence_at=utc_now())
            # Twelve is the provider transport maximum, never a semantic truncation.
            for batch_index,(batch,images) in enumerate(inspection_batches(captures,lambda h:overlays.get(h) or self.artifacts.read(h))):
                hashes=[c['artifact_hash'] for c in batch]
                context=HouseMemory(self.settings.state,run).compact(room['id'],self.houses.context(run,room['id']))
                review=self.ask(row,'inspect-'+room['id']+'-'+proof['scene_version'][:12]+'-'+fingerprint(context)[:12]+'-'+str(batch_index),RENDER_REFERENCE_POLICY+'Inspect this generated Unity room. Report concrete orientation, support, access, missing equipment, lighting and composition defects. Check every functional zone: primary activity, storage contents, secondary activity when appropriate, greenery, wall treatment and motivated light sources. An empty library, unused work surface or unlit task zone is a specific missing/composition defect even when the core furniture exists. Respect explicit minimalist/empty briefs and circulation; do not demand arbitrary clutter. Distinguish functional lighting from mere exposure; identify which zone lacks light or suffers glare. Images show translucent raster-mask overlays from SAM. Uncoloured pixels are NOT proof of absence: SAM can miss, merge or occlude objects. SAM regions are uncertain observations, not prefab identities. Pending requirements and archived defects are bookkeeping from earlier passes, not proof of absence: independently re-evaluate against the current instances and images. Use rejected_attempts to propose a different safe correction rather than repeating a rejected placement. Suggested actions are proposals, not executed changes. '+canonical(dict(room=room,lighting_reference=self.reference_context(row),instances=[i for i in instances if i['room_id']==room['id']],requirements=context,segmentations=[s for s in segments if s['capture_hash'] in hashes])),'ModelHouseInspection',images)
                if review['room_id']!=room['id']:raise AgentError('INVALID_MODEL_OUTPUT','Inspection room identity differs')
                for index,defect in enumerate(review['observations']):
                    observations.append(dict(defect,room_id=room['id'],evidence_ids=hashes))
                    if persist:self.houses.defect(run,dict(id='vision-'+room['id']+'-'+str(batch_index)+'-'+str(index),scope_id=room['id'],severity=defect['severity'],gate=defect['kind'],message=defect['message'],evidence_ids=hashes))
        saved=json.loads(row['checkpoint']).get('segmentation_receipts',{})
        saved[proof['scene_version']]=self.artifacts.put(canonical(segments).encode(),'application/json')
        self.save(row,'inspection','Visual inspection saved',segmentation_receipts=saved)
        return observations

    def replan_repairs(self,row,outline,assets,manifest,proof):
        """Ask for actionable local repairs when the initial observation cannot execute."""
        observations=[]
        for room in outline['rooms']:
            local=[i for i in manifest['instances'] if i['room_id']==room['id']]
            if not local:continue
            context=HouseMemory(self.settings.state,row['run_id']).compact(room['id'],self.houses.context(row['run_id'],room['id']))
            captures=[c for c in proof.get('captures',[]) if c.get('room_id')==room['id'] and c.get('usable')]
            for index,(batch,images) in enumerate(inspection_batches(captures,self.artifacts.read)):
                request=dict(room=room,scene_version=proof['scene_version'],lighting_reference=self.reference_context(row),geometry=manifest['building'],instances=local,context=context)
                self.save(row,'correcting','Targeted defect replanning: '+room['id'],current_scope=room['id'])
                review=self.ask(row,'repair-'+fingerprint(request)[:24]+'-'+str(index),
                    'Previous observed defects had no executable repair or regressed. Reinspect the supplied current evidence and propose DIFFERENT concrete corrections. Use exact instance_id from the inventory. Move/rotate controls move the WHOLE functional group with supported children, not just one prop. translation_m is a world-space delta, horizontal only, and yaw_delta rotates about the group anchor. Preserve room boundaries, doors and circulation and account for all other groups. Do not recommend the same rejected pose. Report missing/composition needs for additions; unsupported lighting bake, wall mounting or mesh/material edits must stay unresolved, not claim success. No corrected defect may be dismissed without visual evidence. '+canonical(request),'ModelHouseInspection',images)
                if review['room_id']!=room['id']:raise AgentError('INVALID_MODEL_OUTPUT','Repair room identity differs')
                observations.extend(dict(o,room_id=room['id'],evidence_ids=[c['artifact_hash'] for c in batch]) for o in review['observations'])
        return observations

    def enrich(self,row,outline,assets,manifest,proof,observations,attempted):
        for room in outline['rooms']:
            local=[o for o in observations if o['room_id']==room['id'] and o['kind'] in {'missing','composition'}]
            if not local:continue
            context=HouseMemory(self.settings.state,row['run_id']).compact(room['id'],self.houses.context(row['run_id'],room['id']))
            key='enrich-'+room['id']+'-'+fingerprint(dict(manifest=signature(manifest),context=context))[:16]
            supports=[dict(instance_id=i['id'],prefab_name=name,regions=a.get('support_regions',[]),surfaces=[dict(id=s['id'],height_m=s.get('height_m')) for s in a.get('surfaces',[])],children=[child['id'] for child in manifest['instances'] if child['support_id']==i['id']]) for i in manifest['instances'] if i['room_id']==room['id'] for name,a in assets.items() if a['prefab_guid']==i['prefab_guid'] and a.get('support_regions')]
            addition=self.ask(row,key,'Propose ONLY additions to repair the reported missing equipment or sparse composition. Keep every existing instance. Return empty groups/detail_assets when no qualified safe addition can address these defects; explain unsupported needs in unresolved. Do not substitute random props for missing rugs, lamps or paintings. When storage is too empty, plan a complete coherent enrichment across several shelf compartments in this pass, not a token single book. Repeated book-cluster prefabs are allowed. Use measured support capacity and occupied children; keep some calm/empty space. Return all proposed detail_assets, without a fixed item quota. '+room_prompt(dict(room,geometry=next(r for r in manifest['building']['rooms'] if r['id']==room['id']),portals=manifest['building']['portals']),json.loads(row['request'])['parameters']['brief'],assets)+' Native lighting reference data: '+canonical(self.reference_context(row))+' Current instances, defects and persistent requirements: '+canonical(dict(instances=[i for i in manifest['instances'] if i['room_id']==room['id']],observations=local,context=context,supports=supports)),'ModelHouseRoomV2')
            if addition['room_id']!=room['id']:raise AgentError('INVALID_MODEL_OUTPUT','Enrichment scope differs')
            addition=deepcopy(addition)
            for g in addition['groups']:g['id']='extra-'+signature(manifest)[:8]+'-'+g['id'][:40]
            offset=max([int(i['id'].rsplit('-',1)[1]) for i in manifest['instances'] if i['room_id']==room['id'] and '-detail-' in i['id'] and i['id'].rsplit('-',1)[1].isdigit()]+[-1])+1
            access=next((a['points'] for a in manifest['access'] if a['room_id']==room['id']),[])
            placed=place_groups(manifest['building'],addition,assets,existing=manifest['instances'],access_points=access,detail_offset=offset)
            self.houses.extend_requirements(row['run_id'],placed['requirements'])
            if addition['unresolved'] or placed['missing']:
                cp=json.loads(row['checkpoint']);self.save(row,'correcting','Additions evaluated; some requirements remain unavailable',unresolved=cp.get('unresolved',[])+addition['unresolved']+placed['missing'])
            if not placed['instances']:continue
            candidate=deepcopy(manifest);candidate['instances'].extend(placed['instances'])
            candidate['access']=[a for a in candidate['access'] if a['room_id']!=room['id']]+[dict(room_id=room['id'],points=placed['access_points'])]
            if signature(candidate) in attempted:continue
            return candidate,dict(kind='enrich_room',scope_id=room['id'],reason='Fill observed missing equipment or sparse composition',added_ids=[i['id'] for i in placed['instances']])
        return None

    def reconcile_selected(self,row,receipt,proof,observations):
        run=row['run_id'];actual={i['id']:i for i in proof.get('instances',[])}
        requirements=self.houses.snapshot(run)['requirements'];resolved=[];unresolved=[]
        for r in requirements:
            i=actual.get(r['id'])
            if i and all(i.get(k) for k in ('connected','native_scale','support_passed')):resolved.append(dict(r,status='satisfied',fulfilled_by=[r['id']],evidence_ids=[receipt['details_artifact_hash']]))
            else:unresolved.append(r['id'])
        self.houses.reconcile_batch(run,[r['id'] for r in requirements],resolved,unresolved)
        # Earlier reports remain archived with their scene version; only the fully
        # re-inspected selected candidate supplies the current visual defect set.
        with self.store.tx() as c:
            c.execute("UPDATE house_defects SET status='resolved' WHERE run_id=? AND id LIKE 'vision-%'",(run,))
        for index,defect in enumerate(observations):
            self.houses.defect(run,dict(id='vision-selected-'+str(index),scope_id=defect['room_id'],severity=defect['severity'],gate=defect['kind'],message=defect['message'],evidence_ids=defect['evidence_ids']))

    def stop(self,action,reason):
        payload('StopRequest',reason);row=self.row(action)
        with self.store.tx() as c:
            c.execute('UPDATE sessions SET stop_requested=1 WHERE id=?',(row['session_id'],))
            if row['state']=='queued':
                c.execute("UPDATE house_actions SET state='failed' WHERE id=?",(action,))
                self.store.update_session(c,row['session_id'],state='interrupted',verdict='inconclusive',stop_reason='STOP_REQUESTED')
            c.execute("UPDATE commands SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE session_id=? AND status IN ('queued','claimed','running')",(row['session_id'],))
        return self.get(action)
    def recover_startup(self):
        with self.store.tx() as c:
            for row in c.execute("SELECT * FROM house_actions WHERE state='running'").fetchall():
                cp=json.loads(row['checkpoint']);cp.update(stage='paused',message='Restart: receipt verification required',execution_state='paused')
                c.execute("UPDATE house_actions SET state='recovery_required',checkpoint=? WHERE id=?",(canonical(cp),row['id']))
                self.store.update_session(c,row['session_id'],state='recovery_required',stop_reason='House resume requires native and provider reconciliation')
