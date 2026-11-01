"""House v1 admission and durable execution, separate from the legacy reconstructor."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import io
import json
import time
import uuid
from PIL import Image
from .domain import AgentError, canonical, fingerprint, payload
from .store import utc_now
from .house_store import HouseStore
from .house_planning import building_from_outline, place_groups, RECIPES
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
        return checkpoint
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
                checkpoint=dict(stage='queued',message='Programme de maison en attente',epoch=project['epoch'],source_version=data['scene_version'],quality_state='pending',updated_at=utc_now())
                c.execute('INSERT INTO house_actions VALUES(?,?,?,?,?,?,?,?,?)',(request['action_id'],run,sid,request['project_id'],request['idempotency_key'],digest,canonical(request),'queued',canonical(checkpoint)))
                action=request['action_id']
        return self.get(action)
    def get(self,action):
        row=self.row(action);r=json.loads(row['request']);cp=json.loads(row['checkpoint'])
        with closing(self.store.connect()) as c:stopped=bool(c.execute('SELECT stop_requested FROM sessions WHERE id=?',(row['session_id'],)).fetchone()[0])
        progress=dict(phase=cp['stage'],message=cp['message'],last_evidence_at=cp.get('last_evidence_at',cp['updated_at']),preview_images=0,render_receipts=len(cp.get('captures',[])),source='house_v1')
        native=self.settings.state/'house'/'runs'/row['run_id']/'progress.json'
        if cp['stage']=='building' and native.is_file() and not native.is_symlink() and native.resolve().is_relative_to(self.settings.state.resolve()) and native.stat().st_size<1000000:
            observed=json.loads(native.read_text())
            if observed.get('run_id')==row['run_id']:progress.update(message=observed['message'],render_receipts=observed['captured'],last_evidence_at=observed['updated_at'])
        return dict(progress=progress,action_id=action,project_id=row['project_id'],conversation_id=r['conversation_id'],message_id=r['message_id'],operation_id='house-operation-'+row['run_id'],session_id=row['session_id'],run_id=row['run_id'],state=row['state'],stop_requested=stopped,evidence_hashes=cp.get('evidence_hashes',[]),error_code=cp.get('error_code'),execution_state=cp.get('execution_state',row['state']),quality_state=cp.get('quality_state','pending'),stage=cp['stage'],message=cp['message'])
    def progress(self,action):
        row=self.row(action);cp=json.loads(row['checkpoint']);out=self.get(action)
        try:out['house']=self.houses.snapshot(row['run_id'])
        except AgentError:out['house']=None
        out.update(current_scope=cp.get('current_scope'),scene_path=cp.get('scene_path'),scene_version=cp.get('scene_version'),last_evidence_at=cp.get('last_evidence_at'),unresolved=cp.get('unresolved',[]),captures=cp.get('captures',[]),segmentations=cp.get('segmentations',[]),updated_at=cp['updated_at'])
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
        return self.provider_call(row,key,spark_request(text,list(images),schema),schema)
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
    def catalogue(self):
        with closing(self.store.connect()) as c:rows=c.execute('SELECT body FROM asset_semantics').fetchall()
        assets={}
        for r in rows:
            a=json.loads(r[0])
            if a['prefab_path'].startswith('Assets/AtmosphericHouse/Prefabs/'):
                name=a['prefab_path'].rsplit('/',1)[-1].removesuffix('.prefab')
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
        self.save(row,'building','Unity assemble les prefabs et contrôle la géométrie',native_command=command_id,manifest_hash=h)
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
            self.save(row,'outline','Muse prépare les pièces et les usages demandés')
            images=[]
            for h in params['reference_hashes']:
                with Image.open(io.BytesIO(self.artifacts.read(h))) as im:
                    im=im.convert('RGB');im.thumbnail((1280,720));buf=io.BytesIO();im.save(buf,format='PNG');images.append(buf.getvalue())
            outline=self.ask(row,'outline','Design a complete Unity house program from this brief. Preserve every requested room and floor; never omit an unsupported need. Give distinct stable room IDs. Dimensions in metres, prefer multiples of 3 compatible with native tiles. Hidden parts are creative and must follow brief. Native prefab contact checks, circulation inspection and SAM/Muse image review are provided by this pipeline; do not list those inspection requests as unsupported building features. Return unresolved architectural or furnishing requirements explicitly. User reference data: '+canonical(params),'ModelHouseOutline',images)
            building=building_from_outline(outline);assets=self.catalogue();designs=[];requirements=[];instances=[];missing=list(outline['unresolved']);access=[]
            for room in outline['rooms']:
                self.guard(row);self.save(row,'furnishing','Aménagement de '+room['purpose'],current_scope=room['id'])
                design=self.ask(row,'room-'+room['id'],'Plan every functional group for this room, without arbitrary object quotas. Use several groups when the brief needs them. Recipes: '+canonical({k:[s[1] for s in v] for k,v in RECIPES.items()})+'. custom keeps an unsupported need visible. Detail asset names must come from catalogue; select purposeful tabletop props. Do not repeat the same group unnecessarily. Room and global brief: '+canonical(dict(room=room,brief=params['brief'],available_assets=list(assets))),'ModelHouseRoom',images)
                if design['room_id']!=room['id'] or len({g['id'] for g in design['groups']})!=len(design['groups']):raise AgentError('INVALID_MODEL_OUTPUT','Room scope or group identity differs')
                placed=place_groups(building,design,assets);designs.append(dict(design=design,placement=placed))
                requirements.extend(placed['requirements']);instances.extend(placed['instances']);missing.extend(placed['missing']);missing.extend(design['unresolved']);access.append(dict(room_id=room['id'],points=placed['access_points']))
            if not requirements:raise AgentError('PROGRAM_INCOMPLETE','No supported functional requirements')
            program=dict(id='house',project_id=row['project_id'],run_id=run,brief=params['brief'],creative_policy=params['creative_policy'],reference_hashes=params['reference_hashes'],rooms=[dict(id=r['id'],floor_id='ground',purpose=r['purpose']) for r in outline['rooms']],requirements=requirements)
            self.houses.create(program,building)
            manifest=dict(schema_version='house-manifest.v1',run_id=run,building=building,instances=instances,access=access,interior_style=params['interior_style'],lighting='warm_interior',designs=designs)
            self.save(row,'building','Plan métrique prêt ; assemblage natif',unresolved=missing)
            receipt,proof=self.native(row,manifest)
            self.save(row,'inspection','Contrôle des vues et des équipements',scene_path=proof['scene_path'],scene_version=proof['scene_version'],captures=proof.get('captures',[]),evidence_hashes=receipt['artifact_hashes'],last_evidence_at=utc_now())
            actual={i['id']:i for i in proof.get('instances',[])}
            resolved=[];unresolved=[]
            for r in requirements:
                native=actual.get(r['id'])
                if native and native.get('connected') and native.get('native_scale') and native.get('support_passed'):
                    resolved.append(dict(r,status='satisfied',fulfilled_by=[r['id']],evidence_ids=[receipt['details_artifact_hash']]))
                else:unresolved.append(r['id'])
            self.houses.reconcile_batch(run,[r['id'] for r in requirements],resolved,unresolved)
            for i,item in enumerate(missing+proof.get('defects',[])):
                self.houses.defect(run,dict(id='native-'+str(i),scope_id='house',severity='warning' if isinstance(item,dict) and item.get('priority')=='preferred' else 'blocking',gate='completeness',message=canonical(item),evidence_ids=[receipt['details_artifact_hash']]))
            # Geometry, visual evidence and artistic acceptance are distinct gates.
            for gate,passed in [('traversal',proof.get('traversal_qualified') and proof.get('portal_qualified')),('lighting',proof.get('lighting_qualified')),('coverage',all(c.get('coverage_qualified') for c in proof.get('captures',[])) and bool(proof.get('captures')))]:
                if not passed:self.houses.defect(run,dict(id='gate-'+gate,scope_id='house',severity='blocking',gate=gate,message='Native qualification pending: '+gate,evidence_ids=[receipt['details_artifact_hash']]))
            self.inspect(row,outline,instances,proof)
            quality=self.houses.finish(run)
            self.save(row,'finished','Construction inspectée ; '+('des défauts restent à corriger' if quality=='incomplete' else 'revue artistique requise'),execution_state='finished',quality_state=quality)
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
    def inspect(self,row,outline,instances,proof):
        from .providers.sam_decoder import decode
        run=row['run_id'];segments=[]
        for room in outline['rooms']:
            captures=[c for c in proof.get('captures',[]) if c['room_id']==room['id'] and c.get('usable')]
            if not captures:
                self.houses.defect(run,dict(id='coverage-'+room['id'],scope_id=room['id'],severity='blocking',gate='coverage',message='No usable interior observation',evidence_ids=[]));continue
            for c in captures:
                self.save(row,'inspection','SAM analyse les objets visibles : '+room['id']+' / '+c['key'],current_scope=room['id'])
                binary=self.artifacts.read(c['artifact_hash'])
                with Image.open(io.BytesIO(binary)) as im:width,height=im.size
                text=self.provider_call(row,'sam-'+c['artifact_hash'],sam_request('furniture',binary))
                regions=decode(text,width,height)
                for region in regions:region['mask_artifact_hash']=self.artifacts.put(region.pop('mask_png'),'image/png')
                segments.append(dict(capture_hash=c['artifact_hash'],scene_version=proof['scene_version'],room_id=room['id'],concept='furniture',regions=regions))
                self.save(row,'inspection','Segmentation enregistrée : '+room['id'],segmentations=segments,last_evidence_at=utc_now())
            # Twelve is the provider transport maximum, never a semantic truncation.
            for batch_index,start in enumerate(range(0,len(captures),12)):
                batch=captures[start:start+12];hashes=[c['artifact_hash'] for c in batch]
                review=self.ask(row,'inspect-'+room['id']+'-'+proof['scene_version'][:12]+'-'+str(batch_index),'Inspect this generated Unity room. Report concrete orientation, support, access, missing equipment, lighting and composition defects. SAM regions are uncertain observations, not prefab identities. Suggested actions are proposals, not executed changes. '+canonical(dict(room=room,instances=[i for i in instances if i['room_id']==room['id']],requirements=self.houses.context(run,room['id']),segmentations=[s for s in segments if s['capture_hash'] in hashes])),'ModelHouseInspection',[self.artifacts.read(h) for h in hashes])
                if review['room_id']!=room['id']:raise AgentError('INVALID_MODEL_OUTPUT','Inspection room identity differs')
                for index,defect in enumerate(review['observations']):self.houses.defect(run,dict(id='vision-'+room['id']+'-'+str(batch_index)+'-'+str(index),scope_id=room['id'],severity=defect['severity'],gate=defect['kind'],message=defect['message'],evidence_ids=hashes))

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
                cp=json.loads(row['checkpoint']);cp.update(stage='paused',message='Redémarrage : vérification des reçus requise',execution_state='paused')
                c.execute("UPDATE house_actions SET state='recovery_required',checkpoint=? WHERE id=?",(canonical(cp),row['id']))
                self.store.update_session(c,row['session_id'],state='recovery_required',stop_reason='House resume requires native and provider reconciliation')
