"""Durable admission for application actions. A preparation and run share one session."""
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import uuid

from .budget import Budget
from .budget_cli import load_pricing
from .domain import AgentError, canonical, fingerprint, payload
from .store import utc_now

SCHEMA = '''
CREATE TABLE IF NOT EXISTS app_actions(
 id TEXT PRIMARY KEY,project_id TEXT NOT NULL REFERENCES projects(id),
 idempotency_key TEXT NOT NULL,request_hash TEXT NOT NULL,request TEXT NOT NULL,
 operation_id TEXT NOT NULL UNIQUE,session_id TEXT NOT NULL UNIQUE REFERENCES sessions(id),
 run_id TEXT NOT NULL UNIQUE,command_id TEXT NOT NULL UNIQUE REFERENCES commands(id),
 state TEXT NOT NULL,bundle_hash TEXT,UNIQUE(project_id,idempotency_key));
CREATE TABLE IF NOT EXISTS app_artifacts(project_id TEXT NOT NULL REFERENCES projects(id),
 artifact_hash TEXT NOT NULL REFERENCES artifacts(hash),PRIMARY KEY(project_id,artifact_hash));
'''


def install(store):
    with closing(store.connect()) as c:c.executescript(SCHEMA)


class ReferenceCommands:
    def __init__(self,settings,store,queue,artifacts):
        self.settings,self.store,self.queue,self.artifacts=settings,store,queue,artifacts
        install(store)

    def admit(self,request):
        request=payload('AppActionRequest',request);digest=fingerprint(request)
        with self.store.tx() as c:
            previous=c.execute('SELECT * FROM app_actions WHERE id=? OR (project_id=? AND idempotency_key=?)',(request['action_id'],request['project_id'],request['idempotency_key'])).fetchall()
            if previous:
                if len(previous)!=1 or previous[0]['request_hash']!=digest:raise AgentError('IDEMPOTENCY_CONFLICT','Action identity already used with different content')
                return self._state(c,previous[0])
            if request['kind']!='reconstruct_reference':raise AgentError('CAPABILITY_MISSING','This action is not connected to native execution yet')
            project=c.execute('SELECT * FROM projects WHERE id=?',(request['project_id'],)).fetchone()
            if not project:raise AgentError('NOT_FOUND','Project is not registered',404)
            project_data=json.loads(project['body']);self.settings.project_path(project_data['project_root'])
            if 'prepare_reference_run' not in project_data['capabilities']:raise AgentError('CAPABILITY_MISSING','Editor has not registered reference preparation capability')
            if not request['expected_scene_version'] or request['expected_scene_version']!=project_data['scene_version']:raise AgentError('STALE_VERSION','Expected scene version does not match registered editor')
            if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached')").fetchone():raise AgentError('SESSION_ACTIVE','Another session owns the editor')
            presence=c.execute('SELECT epoch,last_seen FROM project_presence WHERE project_id=?',(request['project_id'],)).fetchone()
            if not presence or presence['epoch']!=project['epoch'] or datetime.fromisoformat(presence['last_seen'].replace('Z','+00:00')) < datetime.now(timezone.utc)-timedelta(seconds=15):
                raise AgentError('EDITOR_UNAVAILABLE','Connect Unity Local Service before starting an action')
            params=request['parameters'];hashes=params['reference_hashes']
            if not 1<=len(hashes)<=3 or len(set(hashes))!=len(hashes) or set(hashes)!=set(request['artifact_hashes']):raise AgentError('INVALID_INPUT','One to three distinct owned references required',422)
            if params['building_policy']!='atmospheric-house' or params['ceiling_prefab']!='Ceiling_3x3':raise AgentError('INVALID_INPUT','Unknown registered building policy or ceiling',422)
            media=[]
            for h in hashes:
                row=c.execute('SELECT artifacts.media_type FROM app_artifacts JOIN artifacts ON artifacts.hash=app_artifacts.artifact_hash WHERE project_id=? AND artifact_hash=?',(request['project_id'],h)).fetchone()
                if not row:raise AgentError('PROJECT_MISMATCH','Reference is not attached to this project')
                extension={'image/png':'.png','image/jpeg':'.jpg','video/mp4':'.mp4'}.get(row[0])
                if extension is None:raise AgentError('INVALID_MEDIA','Unsupported reference media')
                if row[0].startswith('video/') and len(hashes)!=1:raise AgentError('INVALID_MEDIA','Use one video or up to three images')
                media.append(dict(artifact_hash=h,extension=extension))
            budget=Budget(self.store,load_pricing(self.settings.state/'pricing.json'))
            if self.settings.provider_mode!='live' or not self.settings.api_key or not budget.state(c)['live_enabled']:raise AgentError('COST_BOUND_UNKNOWN','Live service and reconciled budget required')
            run=uuid.uuid4().hex;sid='reference-'+run;operation='operation-'+run;command_id='prepare-'+run;scene_id='reference-scene-'+run
            version=request['expected_scene_version']
            session=payload('Session',dict(id=sid,state='preflight',verdict='pending',best_version=version,current_version=version,attempts_used=0,max_attempts=6,criteria_hash=fingerprint(params),inspection_hash=fingerprint({}),stop_reason=None,provider_mode='live'))
            c.execute('INSERT INTO scenes VALUES(?,?,?)',(scene_id,request['project_id'],canonical(dict(kind='reference_preparation',operation_id=operation))))
            c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',(sid,request['project_id'],scene_id,'preflight',canonical(session)))
            body=dict(operation_id=operation,run_id=run,project_id=request['project_id'],brief=params['brief'],media=media,building_policy=params['building_policy'],interior_style=params['interior_style'],ceiling_prefab=params['ceiling_prefab'])
            command=dict(id=command_id,session_id=sid,kind='prepare_reference_run',expected_version=version,payload_hash=fingerprint(body),payload=body,deadline_utc=(datetime.now(timezone.utc)+timedelta(minutes=5)).isoformat(),bridge_epoch=project['epoch'])
            self.queue.enqueue(request['project_id'],command,c)
            c.execute('INSERT INTO app_actions VALUES(?,?,?,?,?,?,?,?,?,?,NULL)',(request['action_id'],request['project_id'],request['idempotency_key'],digest,canonical(request),operation,sid,run,command_id,'preparing'))
            self.store.event(c,request['action_id'],'action.queued',dict(project_id=request['project_id'],conversation_id=request['conversation_id'],operation_id=operation))
            return self._state(c,c.execute('SELECT * FROM app_actions WHERE id=?',(request['action_id'],)).fetchone())

    def _state(self,c,row):
        request=json.loads(row['request']);session=c.execute('SELECT state,stop_requested FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
        state=row['state']
        if session['state'] in {'recovery_required','interrupted','completed'}:state=session['state']
        elif session['state']=='limit_reached':state='inconclusive'
        if session['stop_requested'] and state=='interrupted':
            directory=self.settings.state/'reconstructions'/row['run_id']
            if (directory/'app-stop-request.json').exists():
                try:receipt=json.loads((directory/'app-stop-receipt.json').read_text())
                except (OSError,ValueError):receipt={}
                if receipt.get('run_id')!=row['run_id'] or receipt.get('stopped') is not True or not isinstance(receipt.get('version'),str):state='verifying'
        return payload('AppActionState',dict(action_id=row['id'],project_id=row['project_id'],conversation_id=request['conversation_id'],message_id=request['message_id'],operation_id=row['operation_id'],session_id=row['session_id'],run_id=row['run_id'],state=state,stop_requested=bool(session['stop_requested']),evidence_hashes=[],error_code=None))

    def get(self,action_id):
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM app_actions WHERE id=?',(action_id,)).fetchone()
            if not row:raise AgentError('NOT_FOUND','Action not found',404)
            return self._state(c,row)

    def stop(self,action_id,reason):
        reason=payload('StopRequest',reason)
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM app_actions WHERE id=?',(action_id,)).fetchone()
            if not row:raise AgentError('NOT_FOUND','Action not found',404)
            session=c.execute('SELECT state FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
            if session['state'] in {'completed','interrupted','limit_reached'}:return self._state(c,row)
            c.execute('UPDATE sessions SET stop_requested=1 WHERE id=?',(row['session_id'],))
            c.execute("UPDATE commands SET cancel_requested=1,status=CASE WHEN status='queued' THEN 'cancelled' ELSE status END WHERE session_id=?",(row['session_id'],))
            self.store.event(c,action_id,'action.stop_requested',reason)
            directory=self.settings.state/'reconstructions'/row['run_id']
            if directory.is_dir():
                from .reference_worker import atomic
                atomic(directory/'app-stop-request.json',dict(operation_id=row['operation_id'],reason=reason['reason']))
            return self._state(c,row)

    def reconcile(self):
        with self.store.tx() as c:
            rows=c.execute("SELECT app_actions.*,commands.status,commands.body FROM app_actions JOIN commands ON commands.id=app_actions.command_id WHERE app_actions.state='preparing'").fetchall()
            for row in rows:
                status=row['status']
                if status=='queued' and datetime.now(timezone.utc)>=datetime.fromisoformat(json.loads(row['body'])['deadline_utc']):
                    c.execute("UPDATE commands SET status='cancelled',cancel_requested=1 WHERE id=?",(row['command_id'],));status='cancelled'
                if status not in {'unknown','failed','cancelled'}:continue
                state='recovery_required' if status=='unknown' else 'interrupted'
                self.store.update_session(c,row['session_id'],state=state,verdict='inconclusive',stop_reason='Preparation '+status+'; no automatic replay')
                c.execute('UPDATE app_actions SET state=? WHERE id=?',(state,row['id']))

    def recover_startup(self):
        # No replay of preparations, including queued work that was never observed.
        with self.store.tx() as c:
            rows=c.execute("SELECT app_actions.*,commands.status FROM app_actions JOIN commands ON commands.id=app_actions.command_id WHERE app_actions.state='preparing'").fetchall()
            for row in rows:
                uncertain=row['status'] not in {'queued','cancelled','failed'}
                state='recovery_required' if uncertain else 'interrupted'
                self.store.update_session(c,row['session_id'],state=state,verdict='inconclusive',stop_reason='Application preparation interrupted; no replay')
                c.execute("UPDATE commands SET status='cancelled',cancel_requested=1 WHERE id=? AND status='queued'",(row['command_id'],))
                c.execute('UPDATE app_actions SET state=? WHERE id=?',(state,row['id']))


def verify_adoption(c,bundle,bundle_hash,artifacts):
    """Validate acknowledged native provenance before reusing the reserved session."""
    row=c.execute('SELECT * FROM app_actions WHERE run_id=?',(bundle['id'],)).fetchone()
    if not row:
        if bundle.get('operation_id') or bundle.get('session_id'):raise AgentError('APP_ADMISSION_MISSING','Bundle claims an unknown application operation')
        return None
    command=c.execute('SELECT * FROM commands WHERE id=?',(row['command_id'],)).fetchone()
    if row['state']!='preparing' or command['status']!='succeeded':raise AgentError('APP_PREPARATION_UNCONFIRMED','Native preparation receipt must be acknowledged first')
    request=json.loads(row['request']);params=request['parameters'];session=c.execute('SELECT * FROM sessions WHERE id=?',(row['session_id'],)).fetchone()
    project=c.execute('SELECT epoch FROM projects WHERE id=?',(row['project_id'],)).fetchone()
    if not project or project['epoch']!=command['epoch'] or session['state']!='preflight' or session['stop_requested']:raise AgentError('STALE_EPOCH','Admission no longer owns this editor')
    expected=dict(operation_id=row['operation_id'],session_id=row['session_id'],project_id=row['project_id'],brief=params['brief'],interior_style=params['interior_style'],ceiling_prefab=params['ceiling_prefab'],building_policy=params['building_policy'])
    if any(bundle.get(k)!=v for k,v in expected.items()):raise AgentError('APP_BUNDLE_MISMATCH','Native bundle differs from admitted action')
    receipt=json.loads(command['result']);details=json.loads(artifacts.read(receipt['details_artifact_hash']))
    if details!=dict(operation_id=row['operation_id'],session_id=row['session_id'],run_id=row['run_id'],bundle_sha256=bundle_hash):raise AgentError('APP_BUNDLE_MISMATCH','Bundle is not the acknowledged preparation output')
    return row
