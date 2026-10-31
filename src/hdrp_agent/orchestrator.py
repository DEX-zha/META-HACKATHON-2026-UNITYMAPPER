"""One durable correction loop. Unknown effects are never automatically repeated."""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import json
import hashlib
import sqlite3
import threading
import time
import subprocess
import sys
from pathlib import Path

import numpy as np

from .domain import AgentError,canonical,fingerprint,payload
from .config import contained
from .store import new_id,utc_now
from .evaluation import Evaluator
from .planner import Planner
from .budget import Budget
from .budget_cli import load_pricing
from .providers.meta_responses import MetaResponses

TERMINAL={'completed','limit_reached','interrupted','recovery_required'}
FOCUS_WATCH_INTERVAL_SECONDS=1.0
CAPTURE_POLICY_REVISION='foreground-ownership-v1'


class SessionBudget:
    def __init__(self,runner,sid,budget):self.runner,self.sid,self.budget=runner,sid,budget
    def __getattr__(self,name):return getattr(self.budget,name)
    def reserve(self,model,request,**kwargs):
        self.runner.guard(self.sid)
        call=self.budget.reserve(model,request,**kwargs)
        self.runner._event(self.sid,'provider_admitted',dict(call_id=call['id'],model=model,reserved_usd_micro=call['reserved']))
        return call
    def mark_sent(self,call_id):
        try:self.runner.guard(self.sid)
        except AgentError:
            self.budget.release_unsent(call_id)
            raise
        self.budget.mark_sent(call_id)



class Orchestrator:
    def __init__(self,settings,store,queue,artifacts,provider_factory=None):
        self.settings,self.store,self.queue,self.artifacts=settings,store,queue,artifacts
        self.evaluator=Evaluator(artifacts,settings.state/'reviews')
        self.shutdown=threading.Event();self.provider_factory=provider_factory
        with self.store.tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS session_runs(session_id TEXT PRIMARY KEY REFERENCES sessions(id),body TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS attempts(session_id TEXT NOT NULL REFERENCES sessions(id),ordinal INTEGER NOT NULL CHECK(ordinal BETWEEN 1 AND 3),patch_id TEXT NOT NULL UNIQUE,body TEXT NOT NULL,PRIMARY KEY(session_id,ordinal))')

    def capture_policy(self):
        return dict(revision=CAPTURE_POLICY_REVISION,platform=sys.platform,focus_owner='registered_editor_pid_watchdog' if sys.platform=='darwin' else 'external',watch_interval_seconds=FOCUS_WATCH_INTERVAL_SECONDS)

    def renderer_profile(self):
        root=self.settings.workspace/'unity/Packages/com.hackathon.hdrp-agent'
        sources={str(path.relative_to(root)):hashlib.sha256(path.read_bytes()).hexdigest() for folder in ['Runtime','Editor'] for path in sorted((root/folder).glob('*.cs'))}
        return fingerprint(dict(native_sources=sources,capture_policy=self.capture_policy()))

    def run_data(self,sid):
        with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM session_runs WHERE session_id=?',(sid,)).fetchone()
        if not row:raise AgentError('NOT_FOUND','Session execution journal is unavailable',404)
        return json.loads(row[0])

    def save_run(self,sid,data,conn=None):
        with self.store.tx(conn) as c:c.execute('UPDATE session_runs SET body=? WHERE session_id=?',(canonical(data),sid))

    def _update(self,sid,**changes):
        with self.store.tx() as c:return self.store.update_session(c,sid,**changes)

    def _event(self,sid,kind,data):
        with self.store.tx() as c:self.store.event(c,sid,kind,data)

    def _targets(self,request):
        # Operator files are kept outside both model context and user-supplied session payload.
        root=contained(self.settings.workspace,self.settings.workspace/'evaluation-private')
        config=contained(root,root/'configs'/(request['scene_id']+'.json'))
        if config.is_file():
            if config.stat().st_size>1_000_000:raise AgentError('INVALID_CRITERIA','Evaluation configuration is oversized',422)
            data=json.loads(config.read_text())
            if data['base_version']!=request['base_version'] or data['criteria_hash']!=fingerprint(request['criteria']):raise AgentError('CRITERIA_FROZEN','Private criteria refer to another baseline')
            return data['targets']
        views={v['key'] for role in ['work_views','control_views'] for v in request['inspection'][role]}
        targets={key:dict(camera_key=key,roi=[0,0,1,1]) for key in views}
        targets.update(performance={},ambiance={})
        return targets

    def create(self,request,key):
        request=payload('SessionCreate',request)
        if request['provider_mode']!=self.settings.provider_mode:raise AgentError('PROVIDER_MODE_CONFLICT','Session and service provider modes differ')
        if request['mode']!='inspect':raise AgentError('CAPABILITY_MISSING','Scene construction has not been qualified')
        if request['session_timeout_seconds']>1200 or request['bake_timeout_seconds']>600:raise AgentError('INVALID_INPUT','Qualified limits are 1200 seconds per session and 600 per bake',422)
        frozen=self.evaluator.freeze(request['criteria'],self._targets(request))
        # Content hashes use canonical numeric encoding on both Python and Unity.
        inspection_hash=self.artifacts.put(canonical(request['inspection']).encode(),'application/json')
        if inspection_hash!=fingerprint(request['inspection']):
            # Byte SHA-256 is the endpoint address; canonical wire representation must also
            # be the cross-language content fingerprint, checked by the editor adapter.
            from .domain import fingerprint_bytes
            inspection_hash=self.artifacts.put(fingerprint_bytes(request['inspection']),'application/json')
        def action(c):
            if (self.settings.state/'reference-owner.json').exists():raise AgentError('SESSION_ACTIVE','Reference reconstruction owns the editor')
            scene=c.execute('SELECT * FROM scenes WHERE id=?',(request['scene_id'],)).fetchone()
            project=c.execute('SELECT * FROM projects WHERE id=?',(request['project_id'],)).fetchone()
            if not scene or not project or scene['project_id']!=request['project_id']:raise AgentError('NOT_FOUND','Registered scene/project is missing',404)
            if json.loads(scene['body'])['scene_version']!=request['base_version']:raise AgentError('STALE_VERSION','Registered scene version changed')
            if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','limit_reached','interrupted')").fetchone():raise AgentError('SESSION_ACTIVE','Another session or recovery owns the editor')
            capabilities=set(json.loads(project['body'])['capabilities'])
            if not {'inspect','snapshot','apply_patch','restore','bake','capture'}<=capabilities:raise AgentError('CAPABILITY_MISSING','Required editor jobs are unavailable')
            if request['provider_mode']=='live':
                budget=Budget(self.store,load_pricing(self.settings.state/'pricing.json'))
                if not self.settings.api_key or not budget.state(c)['live_enabled']:raise AgentError('COST_BOUND_UNKNOWN','Live key and reconciled USD budget with fresh pricing required')
            sid=new_id('session')
            session=payload('Session',dict(id=sid,state='created',verdict='pending',best_version=request['base_version'],current_version=request['base_version'],attempts_used=0,max_attempts=request['max_attempts'],criteria_hash=frozen['criteria_hash'],inspection_hash=inspection_hash,stop_reason=None,provider_mode=request['provider_mode']))
            data=dict(request=request,frozen=frozen,render_sources_hash=self.renderer_profile(),capture_policy=self.capture_policy(),created_at=utc_now(),deadline_utc=(datetime.now(timezone.utc)+timedelta(seconds=request['session_timeout_seconds'])).isoformat(),baseline=None,best_snapshot=None,root_snapshot=None,last_manifest=None,mutated=False,attempts=[],evidence=[],calls=[])
            c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',(sid,request['project_id'],request['scene_id'],'created',canonical(session)))
            c.execute('INSERT INTO session_runs VALUES(?,?)',(sid,canonical(data)))
            self.store.event(c,sid,'session_created',dict(request=request,frozen_hash=frozen['frozen_hash']))
            return session
        return self.store.idempotent('create_session',key,request,action)

    def next_created(self):
        with closing(self.store.connect()) as c:row=c.execute("SELECT sessions.id FROM sessions JOIN session_runs ON session_runs.session_id=sessions.id WHERE state='created' ORDER BY sessions.rowid LIMIT 1").fetchone()
        return row[0] if row else None

    def recover_startup(self):
        with self.store.tx() as c:
            rows=c.execute("SELECT sessions.id,state,session_runs.body FROM sessions JOIN session_runs ON session_runs.session_id=sessions.id WHERE state NOT IN ('completed','limit_reached','interrupted','recovery_required')").fetchall()
            for row in rows:
                data=json.loads(row['body'])
                uncertain=data.get('mutated') or c.execute("SELECT 1 FROM commands WHERE session_id=? AND status IN ('claimed','running','unknown')",(row['id'],)).fetchone()
                self.store.update_session(c,row['id'],state='recovery_required' if uncertain else 'interrupted',verdict='inconclusive',stop_reason='Service restarted; no provider call, bake or patch is replayed')
                c.execute("UPDATE commands SET status='cancelled',cancel_requested=1 WHERE session_id=? AND status='queued'",(row['id'],))

    def guard(self,sid,conn=None):
        with self.store.tx(conn) as c:
            row=c.execute('SELECT body,stop_requested FROM sessions WHERE id=?',(sid,)).fetchone();session=json.loads(row['body'])
            if session['state']=='recovery_required':raise AgentError('RECOVERY_REQUIRED','Editor state requires explicit reconciliation')
            if session['state'] in TERMINAL:raise AgentError('SESSION_TERMINAL','This session has already stopped')
            if self.shutdown.is_set():raise AgentError('SERVICE_STOPPING','Service is stopping')
            if row['stop_requested']:raise AgentError('STOP_REQUESTED','Operator requested stop')
            data=json.loads(c.execute('SELECT body FROM session_runs WHERE session_id=?',(sid,)).fetchone()[0])
            if datetime.now(timezone.utc)>=datetime.fromisoformat(data['deadline_utc']):raise AgentError('SESSION_DEADLINE','Session time limit reached')
            return session

    def accept_attempt(self,sid,patch):
        with self.store.tx() as c:
            session=self.guard(sid,c)
            if session['attempts_used']>=session['max_attempts']:raise AgentError('ATTEMPT_LIMIT','Three correction attempts maximum; the ordinal survives restart')
            if patch['expected_version']!=session['current_version']:raise AgentError('STALE_VERSION','Patch no longer matches the current version')
            ordinal=session['attempts_used']+1
            c.execute('INSERT INTO attempts VALUES(?,?,?,?)',(sid,ordinal,patch['id'],canonical(dict(ordinal=ordinal,patch=patch,state='validated',accepted_at=utc_now()))))
            self.store.update_session(c,sid,attempts_used=ordinal,state='applying')
            self.store.event(c,sid,'attempt_accepted',dict(ordinal=ordinal,patch=patch))
            return ordinal

    def command(self,sid,kind,body,timeout=180,cleanup=False):
        session=self.store.get('sessions',sid) if cleanup else self.guard(sid)
        data=self.run_data(sid)
        with self.store.tx() as c:
            project=c.execute('SELECT epoch FROM projects WHERE id=?',(data['request']['project_id'],)).fetchone()
            deadline=datetime.now(timezone.utc)+timedelta(seconds=timeout)
            if not cleanup:deadline=min(deadline,datetime.fromisoformat(data['deadline_utc']))
            command=dict(id=new_id('command'),session_id=sid,kind=kind,expected_version=session['current_version'],payload_hash=fingerprint(body),payload=body,deadline_utc=deadline.isoformat(),bridge_epoch=project['epoch'])
            self.queue.enqueue(data['request']['project_id'],command,c)
        while True:
            with closing(self.store.connect()) as c:row=c.execute('SELECT status,result FROM commands WHERE id=?',(command['id'],)).fetchone()
            if row['result']:
                result=json.loads(row['result']);self._event(sid,'command_evidence',result)
                if result['status']=='unknown':raise AgentError('RECOVERY_REQUIRED','Command outcome is unknown; no replay')
                self._update(sid,current_version=result['after_version'])
                data=self.run_data(sid);data['last_manifest']=result['manifest_hash'];data['evidence'].append(result);self.save_run(sid,data)
                if result['status']!='succeeded':raise AgentError((result['error'] or {}).get('code','COMMAND_FAILED'),(result['error'] or {}).get('message','Editor command did not succeed'))
                return result
            if row['status']=='unknown':raise AgentError('RECOVERY_REQUIRED','Command receipt is missing')
            if row['status']=='cancelled':raise AgentError('STOP_REQUESTED','Command cancelled before execution')
            now=datetime.now(timezone.utc)
            if self.shutdown.is_set() or now>deadline:
                with self.store.tx() as c:
                    c.execute('UPDATE commands SET cancel_requested=1 WHERE id=?',(command['id'],))
                    if row['status']=='queued':c.execute("UPDATE commands SET status='cancelled' WHERE id=?",(command['id'],))
                if row['status']=='queued':raise AgentError('SESSION_DEADLINE','Editor did not claim the command before the deadline')
                if now>deadline+timedelta(seconds=30) or self.shutdown.is_set():raise AgentError('RECOVERY_REQUIRED','Await native cancellation and reconcile the receipt before any restore')
            time.sleep(.2)

    def details(self,result):
        if not result['details_artifact_hash']:raise AgentError('EVIDENCE_MISSING','Editor details artifact missing')
        return json.loads(self.artifacts.read(result['details_artifact_hash']))

    def focus_editor(self,sid):
        if sys.platform!='darwin':return False
        editor_pid=None
        try:
            identity=self.settings.state/'unity-editor.pid'
            if identity.is_symlink():raise ValueError('Editor identity cannot be a link')
            raw=identity.read_text().strip()
            if not raw.isascii() or not raw.isdigit() or not 1<=len(raw)<=10:raise ValueError('Invalid process identity')
            editor_pid=int(raw)
            if not 1<=editor_pid<=2147483647:raise ValueError('Invalid process identity')
            script='\n'.join(['tell application "System Events"',f'tell first application process whose unix id is {editor_pid}','if name is not "Unity" then error "Editor process identity mismatch"','set frontmost to true','repeat with editorWindow in windows','if name of editorWindow contains " - Unity " then perform action "AXRaise" of editorWindow','end repeat','end tell','end tell'])
            result=subprocess.run(['/usr/bin/osascript','-e',script],capture_output=True,timeout=5,check=False)
            self._event(sid,'editor_focus_requested',dict(method='macos_registered_editor_process',editor_process_id=editor_pid,succeeded=result.returncode==0,return_code=result.returncode))
            return result.returncode==0
        except (OSError,ValueError,subprocess.TimeoutExpired):
            self._event(sid,'editor_focus_requested',dict(method='macos_registered_editor_process',editor_process_id=editor_pid,succeeded=False));return False

    def _capture_with_focus(self,sid,*,cleanup=False):
        activated=self.focus_editor(sid);stop=threading.Event();watch=None
        if activated is True:
            def maintain():
                while not stop.wait(FOCUS_WATCH_INTERVAL_SECONDS):
                    if self.focus_editor(sid) is not True:return
            watch=threading.Thread(target=maintain,name='hdrp-capture-focus',daemon=True);watch.start()
        try:return self._capture_once(sid,cleanup=cleanup)
        finally:
            stop.set()
            if watch is not None:watch.join(timeout=6)

    def capture(self,sid,*,cleanup=False):
        packet=self._capture_with_focus(sid,cleanup=cleanup)
        data=self.run_data(sid);performance=packet.get('performance',{})
        required=any(item['required'] and item['method']=='frame_time_regression' for item in data['request']['criteria'])
        unqualified=performance.get('focused') is not True or performance.get('focus_stable') is not True
        if required and unqualified and not cleanup and packet['version'] not in data.get('focus_requalifications',[]):
            # Keep the failed measurement unchanged. A fresh full render of the
            # exact same version supplies new measured evidence, never a new flag
            # on the old measurement. Bounded to one extra capture per version.
            self._event(sid,'capture_focus_unqualified',packet)
            data.setdefault('focus_requalifications',[]).append(packet['version']);self.save_run(sid,data)
            fresh=self._capture_with_focus(sid,cleanup=cleanup)
            fresh=self.witness(fresh,packet)
            self._event(sid,'capture_focus_requalified',dict(version=fresh['version'],original_capture_details_hash=packet['capture_details_hash'],new_capture_details_hash=fresh['capture_details_hash'],performance=fresh.get('performance',{})))
            return fresh
        return packet

    def _capture_once(self,sid,*,cleanup=False):
        from .media import encode_clip
        session=self.store.get('sessions',sid)
        result=self.command(sid,'capture',dict(inspection_hash=session['inspection_hash'],role='all'),timeout=240,cleanup=cleanup)
        detail=self.details(result);request=detail['request'];manifest=detail['manifest'];proof=detail['editor_proof']
        for key in ['capture_id','version_id','inspection_hash','conditions_hash']:
            if request[key]!=manifest[key]:raise AgentError('STALE_VERSION','Capture does not match the request')
        if manifest['status']!='complete' or manifest['render_ready'] is not True or request['version_id']!=result['before_version'] or result['before_version']!=result['after_version'] or proof['scene_version_after']!=result['after_version'] or proof['manifest_hash_after']!=result['manifest_hash'] or request['inspection_hash']!=session['inspection_hash']:raise AgentError('CAPTURE_UNSTABLE','Capture version/conditions proof is inconsistent')
        if request['scene_manifest_hash']!=result['manifest_hash']:raise AgentError('STALE_VERSION','Scene dependencies changed during rendering')
        from .capture_validation import unity_render_plan
        expected=unity_render_plan(self.run_data(sid)['request']['inspection'])
        if fingerprint(request['plan'])!=fingerprint(expected):raise AgentError('CRITERIA_FROZEN','Rendered inspection plan changed')
        frames=manifest['frames'];by_hash={c['artifact_hash']:c for c in result['captures']}
        directory=contained(self.settings.state,self.settings.state/'sessions'/sid/manifest['capture_id']);directory.mkdir(parents=True,exist_ok=True)
        for frame in frames:
            name=frame['file']
            if Path(name).name!=name:raise AgentError('OUT_OF_SCOPE','Frame name is not local')
            digest=proof['frame_hashes'][name]
            if digest not in by_hash:raise AgentError('EVIDENCE_MISSING','Frame artifact is not in the durable receipt')
            content=self.artifacts.read(digest);(directory/name).write_bytes(content)
        for name,value in [('request.json',request),('manifest.json',manifest),('editor-proof.json',proof)]: (directory/name).write_text(canonical(value))
        from .capture_validation import read_capture
        checked=read_capture(directory)
        clip=encode_clip(directory,checked['clip'],request['plan']['fps']) if request['include_clip'] else None
        video_hash=self.artifacts.put((directory/'clip.mp4').read_bytes(),'video/mp4') if clip else None
        statics=[c for c in result['captures'] if c['camera_key']!=request['plan']['path_key']]
        packet=dict(version=result['after_version'],inspection_hash=request['inspection_hash'],conditions_hash=request['conditions_hash'],captures=statics,comparable=False,performance=manifest['performance'],geometry={},requires_bake=True,bake_verified=request['bake_status']=='complete',clip_artifact_hash=video_hash,capture_details_hash=result['details_artifact_hash'],manifest_hash=result['manifest_hash'],capture_policy=self.capture_policy())
        count=len(checked['clip']);indices={0,count//3,2*count//3} if count else set()
        packet['planner_frames']=[capture for capture in result['captures'] if capture['camera_key']==request['plan']['path_key'] and capture['frame_index'] in indices and capture['role']=='work']
        return packet

    def witness(self,baseline,repeated):
        if baseline['version']!=repeated['version'] or baseline['inspection_hash']!=repeated['inspection_hash'] or baseline['conditions_hash']!=repeated['conditions_hash']:raise AgentError('CAPTURE_UNSTABLE','Repeated witness belongs to another version')
        targets={c['camera_key']:dict(camera_key=c['camera_key'],roi=[0,0,1,1]) for c in baseline['captures']}
        errors={key:float(np.mean(np.abs(self.evaluator._image(baseline,target)-self.evaluator._image(repeated,target)))) for key,target in targets.items()}
        if any(error>.01 for error in errors.values()):raise AgentError('CAPTURE_UNSTABLE','Repeated witness exceeded frozen linear luminance tolerance')
        baseline['comparable']=True;baseline['witness_errors']=errors;baseline['witness_details_hash']=repeated['capture_details_hash']
        return baseline

    def bake(self,sid):
        self._update(sid,state='baking');data=self.run_data(sid)
        result=self.command(sid,'bake',dict(timeout_seconds=data['request']['bake_timeout_seconds'],lightmapper='progressive_gpu'),timeout=data['request']['bake_timeout_seconds']+25)
        detail=self.details(result)
        phases=[event.get('phase') for event in detail.get('events',[]) if isinstance(event,dict)]
        valid=detail.get('status')=='complete' and detail.get('resources_verified') is True and detail.get('after_version')==result['after_version'] and detail.get('before_version')==result['before_version'] and isinstance(detail.get('job_id'),str) and 'bakeStarted' in phases and 'bakeCompleted' in phases and phases[-1:] == ['stopped'] and not set(phases)&{'cancel_requested','bakeCancelled','engine_error_or_fallback','domain_reload_without_completion_proof'}
        if result['bake_status']!='complete' or not valid:raise AgentError('BAKE_INCOMPLETE','Current GPU bake has no completion proof')
        return result

    def cached_baseline(self,sid,version,manifest_hash):
        current=self.run_data(sid);session=self.store.get('sessions',sid)
        with closing(self.store.connect()) as c:rows=c.execute('SELECT session_id,body FROM session_runs WHERE session_id!=? ORDER BY rowid DESC',(sid,)).fetchall()
        for row in rows:
            prior=json.loads(row['body']);baseline=prior.get('baseline')
            if prior.get('render_sources_hash')!=self.renderer_profile():continue
            if current.get('capture_policy')!=self.capture_policy() or prior.get('capture_policy')!=current['capture_policy']:continue
            if not baseline or baseline.get('comparable') is not True or baseline.get('bake_verified') is not True:continue
            if baseline.get('capture_policy')!=current['capture_policy']:continue
            if baseline.get('version')!=version or baseline.get('manifest_hash')!=manifest_hash or baseline.get('inspection_hash')!=session['inspection_hash']:continue
            if prior['request']['brief']['mutation_scope_id']!=current['request']['brief']['mutation_scope_id']:continue
            if any(capture['provenance']!='live' or capture['version_id']!=version for capture in baseline['captures']):continue
            hashes=[capture['artifact_hash'] for capture in baseline['captures']]+[baseline['capture_details_hash'],baseline['witness_details_hash'],baseline['clip_artifact_hash']]
            try:
                for digest in hashes:self.artifacts.read(digest)
            except AgentError:continue
            self._event(sid,'baseline_reused',dict(source_session_id=row['session_id'],version=version,manifest_hash=manifest_hash,inspection_hash=session['inspection_hash'],witness_details_hash=baseline['witness_details_hash']))
            return baseline
        return None

    def _provider(self,sid=None):
        if self.provider_factory:return self.provider_factory()
        if self.settings.provider_mode!='live':raise AgentError('OFFLINE_MODE','Offline sessions preserve local evidence but do not request or claim model repairs')
        return MetaResponses(self.settings,SessionBudget(self,sid,Budget(self.store,load_pricing(self.settings.state/'pricing.json'))),self.artifacts)

    def restore_best(self,sid):
        data=self.run_data(sid)
        if not data.get('mutated'):return
        self._update(sid,state='restoring')
        result=self.command(sid,'restore',dict(snapshot_id=data['best_snapshot'],expected_manifest_hash=data['last_manifest']),cleanup=True)
        expected=self.store.get('sessions',sid)['best_version']
        if result['after_version']!=expected:raise AgentError('RECOVERY_REQUIRED','Restored version differs from the retained best version')
        fresh=self.capture(sid,cleanup=True)
        # Restoring exact bytes invalidates the in-memory bake job association; saved
        # lightmaps remain verified by the baseline manifest and a fresh comparison.
        fresh['requires_bake']=False
        baseline=data['baseline']
        if baseline:
            check=self.witness(baseline.copy(),fresh)
            fresh['comparable']=True;fresh['witness_errors']=check['witness_errors']
        data=self.run_data(sid);data['mutated']=False;data['restore_capture']=fresh;self.save_run(sid,data)

    @staticmethod
    def audit_clear(audit):
        value=audit['value']
        return not value['observations'] and not value['hypotheses'] and not value['unsupported_limits']

    def can_stage(self,data,evaluation):
        if evaluation.get('issues'):return False
        required=[c for c in data['request']['criteria'] if c['required']]
        for criterion in required:
            passed=evaluation['per_criterion'].get(criterion['id'],{}).get('passed')
            if passed is False:
                partial=criterion['kind'] in {'artifact','geometry'} and criterion['unit']!='regression' and evaluation.get('target_progress',{}).get(criterion['id']) is True
                if not partial:return False
            if passed is None and criterion['method']!='artistic_review':return False
        return evaluation['verdict'] in {'inconclusive','improved','rejected'}

    def planning_context(self,sid,planner,scene,packet):
        data=self.run_data(sid)
        context=planner.context(data['request']['brief'],data['request']['criteria'],scene,packet['captures']+packet.get('planner_frames',[]))
        plan=data['request']['inspection']
        context['render_conditions']={key:plan[key] for key in ['fixed_ev','width','height','fps','seed','warmup_frames']}
        context['render_conditions'].update(exposure_mode='Fixed',color_space='sRGB_LDR_gameview',temporal_coverage='Sparse timestamped frames; absence of flicker is not established')
        diagnostic=self.artifacts.cache_get(fingerprint(dict(kind='measured_rendering',scene_version=scene['version'])))
        if diagnostic:
            measured=json.loads(self.artifacts.read(diagnostic))
            if set(measured) in ({'scene_version','tonemapping','source'},{'scene_version','tonemapping','source','fog_quality'}) and measured['scene_version']==scene['version'] and measured['source']=='edit_mode_global_volume_stack' and measured['tonemapping'] in {'None','Neutral','ACES','Custom','External'}:
                context['render_conditions'].update(tonemapping=measured['tonemapping'],tonemapping_provenance=measured['source'],diagnostic_artifact_hash=diagnostic)
                quality=measured.get('fog_quality')
                if isinstance(quality,dict) and set(quality)=={'declared_volume_slices','declared_screen_resolution_percent','budget','resolution_depth_ratio','denoising','depth_extent_m','control_mode'}:
                    numeric=['declared_volume_slices','declared_screen_resolution_percent','budget','resolution_depth_ratio','depth_extent_m']
                    if all(type(quality[k]) in (int,float) and 0<=quality[k]<=512 for k in numeric) and quality['denoising'] in {'Gaussian','Reprojection','Both','None'} and quality['control_mode'] in {'Balance','Manual'}:context['render_conditions']['fog_quality']=quality
        return context

    def restore_working(self,sid):
        data=self.run_data(sid);working=data.get('working_capture') or data['baseline']
        self._update(sid,state='restoring')
        result=self.command(sid,'restore',dict(snapshot_id=data.get('working_snapshot') or data['best_snapshot'],expected_manifest_hash=data['last_manifest']),cleanup=True)
        if result['after_version']!=working['version']:raise AgentError('RECOVERY_REQUIRED','Restored provisional working version differs')
        fresh=self.capture(sid,cleanup=True);fresh['requires_bake']=False
        fresh=self.witness(working.copy(),fresh)
        data=self.run_data(sid);data['working_capture']=fresh;data['mutated']=fresh['version']!=self.store.get('sessions',sid)['best_version'];self.save_run(sid,data)

    def finish_candidate(self,sid,reason,*,limited=False):
        data=self.run_data(sid)
        candidate=data.get('provisional_candidate')
        if candidate:data['final_audit']=candidate['audit']
        self.save_run(sid,data)
        self.restore_best(sid)
        self._event(sid,'final_candidate_ready',dict(candidate_snapshot=candidate['snapshot_id'] if candidate else None,reason=reason,requires_human_review=True,limited=limited))
        self._update(sid,state='limit_reached' if limited else 'completed',verdict='inconclusive',stop_reason=reason)

    def run(self,sid):
        provider=None
        try:
            self._update(sid,state='preflight');self.guard(sid)
            inspection=self.details(self.command(sid,'inspect',dict(diagnostic_keys=['geometry','lights','volumes','materials','gi','bake_state'])))
            data=self.run_data(sid)
            if inspection['version']!=data['request']['base_version']:raise AgentError('STALE_VERSION','Scene changed since session creation')
            if inspection['scope_id']!=data['request']['brief']['mutation_scope_id']:raise AgentError('OUT_OF_SCOPE','Brief mutation scope differs from active owned copy')
            root=self.command(sid,'snapshot',dict(scope_id=inspection['scope_id']))
            data=self.run_data(sid);data['root_snapshot']=root['snapshot_id'];data['best_snapshot']=root['snapshot_id'];data['mutated']=True;self.save_run(sid,data)
            self._update(sid,state='baseline')
            baseline=self.cached_baseline(sid,inspection['version'],root['manifest_hash'])
            if baseline is None:
                self.bake(sid);self._update(sid,state='capturing')
                baseline=self.capture(sid);repeated=self.capture(sid);baseline=self.witness(baseline,repeated)
            best=self.command(sid,'snapshot',dict(scope_id=inspection['scope_id']))
            data=self.run_data(sid);data['baseline']=baseline;data['best_snapshot']=best['snapshot_id'];data['working_snapshot']=best['snapshot_id'];data['working_capture']=baseline;data['mutated']=False;self.save_run(sid,data)
            self._update(sid,best_version=baseline['version'],current_version=baseline['version'])
            if data['request']['provider_mode']=='live':
                for criterion in data['request']['criteria']:
                    if criterion['required'] and criterion['method']=='frame_time_regression':
                        try:self.evaluator._measure(criterion,data['frozen']['targets'][criterion['target']],baseline,baseline,sid,data['frozen']['criteria_hash'])
                        except (KeyError,ValueError,TypeError) as error:raise AgentError('CAPTURE_UNSTABLE','Baseline performance is unqualified; no provider call admitted: '+str(error)) from error
            provider=self._provider(sid);planner=Planner(provider,self.artifacts)
            while True:
                self.guard(sid);session=self.store.get('sessions',sid)
                if session['attempts_used']>=session['max_attempts']:
                    self.finish_candidate(sid,'Correction limit reached; final global audit and residual defects retained',limited=True);return
                self._update(sid,state='diagnosing')
                scene=self.details(self.command(sid,'inspect',dict(diagnostic_keys=['geometry','lights','volumes','materials','gi','bake_state'])))
                data=self.run_data(sid)
                context=self.planning_context(sid,planner,scene,data.get('working_capture') or data['baseline'])
                diagnosis=data.pop('pending_diagnosis',None);self.save_run(sid,data)
                if diagnosis is None:
                    diagnosis=planner.diagnose(context);self._event(sid,'diagnosis',diagnosis)
                else:
                    if diagnosis['value']['scene_version']!=scene['version']:raise AgentError('STALE_VERSION','Global audit belongs to another working version')
                    self._event(sid,'diagnosis_reused',diagnosis)
                blocked=[h for h in diagnosis['value']['hypotheses'] if h['target_ids'] and h['missing_information']]
                if blocked and not any(h['target_ids'] and not h['missing_information'] for h in diagnosis['value']['hypotheses']) and scene['version'] not in data.get('diagnostic_followups',[]):
                    # A changed, explicit diagnostic request, never a retry of the
                    # original inference. One fresh read/clarification per version.
                    data.setdefault('diagnostic_followups',[]).append(scene['version']);self.save_run(sid,data)
                    fresh=self.details(self.command(sid,'inspect',dict(diagnostic_keys=['geometry','lights','volumes','materials','gi','bake_state'])))
                    if fresh['version']!=scene['version']:raise AgentError('STALE_VERSION','Scene changed during targeted diagnostics')
                    context=self.planning_context(sid,planner,fresh,data.get('working_capture') or data['baseline'])
                    context['diagnostic_followup']=dict(requested_information=list(dict.fromkeys(item for hypothesis in blocked for item in hypothesis['missing_information'])),previous_diagnosis=diagnosis['value'],verified_scene_version=fresh['version'],available_fact_sources=['objects: measured bounds, mesh, light and volume properties','bake_settings: actual global bake settings','mutation_rules: authoritative capability and parameter bounds'],limitation='Only exported facts are known. Bounds are not geometry gaps; an atlas allocation is not measured UV occupancy. Do not invent unavailable facts. Missing information is only a fact essential to safely specify a bounded experiment, not a future rendered outcome. Use existing exported facts when they already answer a request; otherwise retain the missing information. This is the only diagnostic clarification for this version.')
                    diagnosis=planner.diagnose(context);self._event(sid,'targeted_diagnosis',diagnosis)
                    self.guard(sid)
                tried={(entry['patch']['expected_version'],entry['patch']['hypothesis_id']) for entry in data['attempts']}
                grounded=[h for h in diagnosis['value']['hypotheses'] if h['target_ids'] and not h['missing_information']]
                hypotheses=[h for h in grounded if (scene['version'],h['key']) not in tried]
                if not hypotheses:
                    data=self.run_data(sid);data['final_audit']=diagnosis;self.save_run(sid,data)
                    reason='All supported hypotheses were already attempted on this version; residual defects retained' if grounded else 'No further supported correction; final global audit retained for one human review'
                    self.finish_candidate(sid,reason);return
                from .segmentation import Segmenter
                hypothesis_targets={target for h in diagnosis['value']['hypotheses'] for target in h['target_ids']}
                concepts={'table','chair','window','door','wall'}
                concept=next((word for obj in context['objects'] if obj['logical_key'] in hypothesis_targets and obj.get('renderer') is not None for word in obj['name'].lower().replace('-',' ').split() if word in concepts),None)
                if concept:
                    selection=Segmenter(provider,self.artifacts).segment(dict(context['work_captures'][0],role='work'),concept)
                    context['segmentation']=selection;self._event(sid,'segmentation',selection)
                self._update(sid,state='proposing');self.guard(sid)
                proposed=planner.propose(context,diagnosis['value'],hypotheses[0]['key'],sid);self.guard(sid)
                repeated=any(entry['patch']['expected_version']==proposed['patch']['expected_version'] and fingerprint(entry['patch']['operations'])==fingerprint(proposed['patch']['operations']) for entry in data['attempts'])
                if repeated:
                    self._event(sid,'proposal_refused_duplicate',proposed)
                    self.finish_candidate(sid,'Identical correction on this version was already tested; no replay');return
                ordinal=self.accept_attempt(sid,proposed['patch']);self._event(sid,'proposal',proposed)
                self.command(sid,'snapshot',dict(scope_id=scene['scope_id']))
                # Persist uncertainty before the mutation can cross the bridge.
                data=self.run_data(sid);data['mutated']=True;self.save_run(sid,data)
                patched=self.command(sid,'apply_patch',proposed['patch'])
                self.bake(sid);self._update(sid,state='capturing')
                after=self.capture(sid);after=self.witness(after,self.capture(sid))
                candidate_snapshot=self.command(sid,'snapshot',dict(scope_id=scene['scope_id']))
                self._update(sid,state='verifying');data=self.run_data(sid)
                evaluation=self.evaluator.evaluate(data['frozen'],data['baseline'],after,session_id=sid)
                if (data['request']['provider_mode']!='live' or getattr(provider,'mode','live')!='live') and evaluation['verdict']=='improved':evaluation['verdict']='inconclusive'
                self._event(sid,'evaluation',evaluation)
                entry=dict(ordinal=ordinal,candidate_snapshot=candidate_snapshot['snapshot_id'],patch=proposed['patch'],diagnosis=diagnosis,after=after,evaluation=evaluation,audit=None)
                data['attempts'].append(entry);data['latest_candidate']=dict(snapshot_id=candidate_snapshot['snapshot_id'],after=after,ordinal=ordinal);self.save_run(sid,data)
                # A global work-view audit follows every patch, even when only the
                # independent artistic review is missing. Controls remain private.
                self._update(sid,state='diagnosing')
                rendered_scene=self.details(self.command(sid,'inspect',dict(diagnostic_keys=['geometry','lights','volumes','materials','gi','bake_state'])))
                audit_context=self.planning_context(sid,planner,rendered_scene,after)
                audit=planner.diagnose(audit_context);self._event(sid,'global_audit',audit)
                data=self.run_data(sid);data['attempts'][-1]['audit']=audit;data['final_audit']=audit;self.save_run(sid,data)
                if evaluation['verdict']=='improved' and self.audit_clear(audit):
                    data['best_snapshot']=candidate_snapshot['snapshot_id'];data['mutated']=False;data['provisional_candidate']=None;data['final_candidate']=dict(snapshot_id=candidate_snapshot['snapshot_id'],after=after,audit=audit,ordinal=ordinal);self.save_run(sid,data)
                    self._event(sid,'final_candidate_ready',dict(candidate_snapshot=candidate_snapshot['snapshot_id'],requires_human_review=False,limited=False))
                    self._update(sid,state='completed',verdict='improved',best_version=after['version'],stop_reason='Frozen independent criteria passed and global work-view audit reports no residual defects');return
                if self.can_stage(data,evaluation):
                    data['provisional_candidate']=dict(snapshot_id=candidate_snapshot['snapshot_id'],after=after,audit=audit,ordinal=ordinal)
                    data['working_capture']=after;data['working_snapshot']=candidate_snapshot['snapshot_id'];data['pending_diagnosis']=audit;self.save_run(sid,data)
                    self._event(sid,'candidate_staged',dict(version=after['version'],ordinal=ordinal,accepted=False))
                    actionable=[h for h in audit['value']['hypotheses'] if h['target_ids'] and not h['missing_information']]
                    diagnostic_pending=any(h['target_ids'] and h['missing_information'] for h in audit['value']['hypotheses']) and after['version'] not in data.get('diagnostic_followups',[])
                    if self.audit_clear(audit) or not actionable and not diagnostic_pending:
                        self.finish_candidate(sid,'Global automatic pass finished; final candidate and any unsupported defects await one independent human review');return
                    continue
                self.restore_working(sid);data=self.run_data(sid)
                if data.get('provisional_candidate'):data['pending_diagnosis']=data['provisional_candidate']['audit'];self.save_run(sid,data)
                unknown_technical=any(criterion['required'] and criterion['kind']!='artistic' and evaluation['per_criterion'].get(criterion['id'],{}).get('passed') is None for criterion in data['request']['criteria'])
                if evaluation['verdict']=='inconclusive' or unknown_technical:
                    self.finish_candidate(sid,'Required technical evidence is missing; no further automatic mutation is admissible');return
                self._update(sid,state='diagnosing')
        except AgentError as exc:
            current=self.store.get('sessions',sid)
            if exc.code=='RECOVERY_REQUIRED' or current['state']=='recovery_required':
                self._update(sid,state='recovery_required',verdict='inconclusive',stop_reason=exc.message)
            else:
                try:self.restore_best(sid)
                except Exception as restore_error:
                    self._event(sid,'return_error',dict(original_error=exc.as_dict(),return_error_type=type(restore_error).__name__,return_error_code=getattr(restore_error,'code',None)))
                    self._update(sid,state='recovery_required',verdict='inconclusive',stop_reason='Conditional return incomplete; inspect durable receipts and files before recovery');return
                limited=exc.code in {'ATTEMPT_LIMIT','SESSION_DEADLINE','BUDGET_LIMIT'}
                provisional=self.run_data(sid).get('provisional_candidate')
                self._update(sid,state='limit_reached' if limited else 'interrupted',verdict='no_improvement' if limited and not provisional else 'inconclusive',stop_reason=exc.code+': '+exc.message)
            self._event(sid,'session_error',exc.as_dict())
        except Exception as exc:
            data=self.run_data(sid)
            self._update(sid,state='recovery_required' if data.get('mutated') else 'interrupted',verdict='inconclusive',stop_reason='Unexpected '+type(exc).__name__+'; durable evidence retained and automatic replay disabled')
            self._event(sid,'internal_error',dict(error_type=type(exc).__name__))
        finally:
            if provider is not None and hasattr(provider,'client'):provider.client.close()
            # One final review package per request, including partial/failed runs.
            from .reporting import export,comparison_html
            output=self.settings.state/'reports';output.mkdir(parents=True,exist_ok=True)
            try:
                export(self.settings,self.store,self.artifacts,sid,output/(sid+'.json'))
                if self.run_data(sid).get('attempts'):
                    html=comparison_html(self.store,self.artifacts,sid)
                    temporary=output/(sid+'.html.writing');temporary.write_text(html);temporary.replace(output/(sid+'.html'))
            except Exception as report_error:self._event(sid,'final_report_error',dict(error_type=type(report_error).__name__))
