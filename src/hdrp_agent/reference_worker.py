"""Durable, bounded image/video reconstruction with a native file handoff."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime,timedelta,timezone
from html import escape
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import re
import time

import numpy as np
from PIL import Image,ImageOps

from .artifacts import ArtifactStore
from .budget import Budget
from .budget_cli import load_pricing
from .capture_validation import read_capture
from .config import contained
from .domain import AgentError,canonical,fingerprint,payload
from .orchestrator import SessionBudget
from .providers.meta_responses import MetaResponses,terminal_text
from .reference_geometry import fit_initial_positions,size_evidence
from .reference_media import ingest,bounded_image
from .reference_planner import ReferencePlanner,validate_plan,validate_analysis
from .reference_assets import candidate_groups,boards,select_assets
from .reference_details import native_details,original_crops
from .store import utc_now
from .reference_schedule import default_policy,next_action,assess,proposal_base
from .reference_metrics import GeometryEvaluator
from .reference_memory import evidence_key,new_memory,phase_for,constrain_proposal,update_memory,regressions,appearance_step,experiment_identity


def atomic(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.writing');temporary.write_text(canonical(value));temporary.replace(path)


def inspection_for(frames,plan,recorded=None):
    if recorded is not None:return recorded
    views=json.loads(canonical(plan['estimated_views']))
    # The comparison uses an aspect-preserving central crop of the GameView.
    # Widen vertical FOV only when a wider source requires vertical cropping.
    for frame,view in zip(frames,views):
        aspect=frame['model_size'][0]/frame['model_size'][1]
        if aspect>1280/720:view['fov_deg']=math.degrees(2*math.atan(math.tan(math.radians(view['fov_deg'])/2)*aspect/(1280/720)))
    while len(views)<3:
        view=json.loads(canonical(views[0]));view['key']='novel-'+str(len(views));view['position_m'][0]+=.25*len(views);views.append(view)
    controls=[]
    for name,offset in [('control-high',.3),('control-low',-.2)]:
        view=json.loads(canonical(views[0]));view['key']=name;view['position_m'][1]+=offset;controls.append(view)
    return dict(work_views=views,control_views=controls,path_key='reference-orbit',fps=24,duration_seconds=6,width=1280,height=720,fixed_ev=0,seed=1729,warmup_frames=64)


def score_pairs(artifacts,references,candidates,analysis,*,priority_view=None,segments=()):
    by_key={frame['key']:frame for frame in candidates};per_view={};per_object={o['key']:dict(per_view={},priority_rgb_mae=None) for o in analysis['objects']}
    for frame in references:
        other=by_key.get(frame['key'])
        if other is None:raise AgentError('MISSING_FRAME','Candidate lacks a matched reference camera')
        with Image.open(io.BytesIO(artifacts.read(frame['artifact_hash']))) as original:
            a=np.asarray(original.convert('RGB'),dtype=np.float64)/255
            with Image.open(io.BytesIO(artifacts.read(other['artifact_hash']))) as candidate:
                b=np.asarray(ImageOps.fit(candidate.convert('RGB'),original.size,method=Image.Resampling.LANCZOS),dtype=np.float64)/255
        error=np.abs(a-b).mean(axis=2);h,w=error.shape
        regions=[]
        for item in analysis['objects']:
            selected=next((v['selection'] for v in segments if v['object_key']==item['key'] and v['view_key']==frame['key'] and v.get('selection')),None)
            box=selected['bbox_xyxy'] if selected else next((v['bbox_xyxy'] for v in item['view_boxes'] if v['view_key']==frame['key']),None)
            if box:
                x0,y0,x1,y1=[round(x*d) for x,d in zip(box,[w,h,w,h])]
                if x1>x0 and y1>y0:
                    value=float(error[y0:y1,x0:x1].mean());regions.append(value);per_object[item['key']]['per_view'][frame['key']]=dict(rgb_mae=value,region_source='sam_mask_box' if selected else 'reference_analysis_box')
                    if frame['key']==priority_view:per_object[item['key']]['priority_rgb_mae']=value
        edge_a=np.abs(np.diff(a,axis=1)).mean(axis=2);edge_b=np.abs(np.diff(b,axis=1)).mean(axis=2)
        global_error=float(error.mean());roi_error=float(np.mean(regions)) if regions else global_error;edge_error=float(np.abs(edge_a-edge_b).mean())
        per_view[frame['key']]=dict(rgb_mae=global_error,object_box_rgb_mae=roi_error,edge_mae=edge_error,score=.3*global_error+.5*roi_error+.2*edge_error)
    global_score=float(np.mean([v['score'] for v in per_view.values()]));priority_score=per_view.get(priority_view,{}).get('score');object_errors=[o['priority_rgb_mae'] for o in per_object.values() if o['priority_rgb_mae'] is not None]
    score=.55*priority_score+.25*global_score+.2*max(object_errors,default=priority_score) if priority_score is not None else global_score
    return dict(score=score,global_score=global_score,priority_view=priority_view,priority_score=priority_score,per_object=per_object,selection_metric='0.55 priority view + 0.25 all-view mean + 0.20 worst priority object region' if priority_score is not None else 'all-view mean',lower_is_better=True,per_view=per_view,metric='0.3 RGB MAE + 0.5 mean object-box RGB MAE + 0.2 horizontal edge MAE; aspect-preserving central comparison crop',fidelity_verified=False,limitation='A pixel discrepancy is not proof of correct 3D geometry, object identity or invisible surfaces. Human reference review is still required.')


def candidate_rank(attempt):
    contacts=attempt['metrics'].get('contacts',{'passed':False,'checks':[]})
    return (not contacts['passed'],sum(c['status']!='contact' for c in contacts['checks']),attempt['metrics']['score'])


def accept_external_candidate(attempt,best):
    if best is None:return True
    def unresolved(a):return sum(c['status'] not in {'contact','offset_evidenced'} for c in a['metrics']['contacts']['checks'])
    new,old=unresolved(attempt),unresolved(best)
    architecture=attempt['metrics'].get('architecture',{});prior=best['metrics'].get('architecture',{})
    improved_architecture=False
    if prior.get('qualified'):
        if not architecture.get('qualified') or architecture['defect_count']>prior['defect_count']:return False
        improved_architecture=architecture['defect_count']<prior['defect_count']
    delta=attempt['metrics'].get('photometric_selection_score',attempt['metrics']['score'])-best['metrics'].get('photometric_selection_score',best['metrics']['score'])
    return new<=old and (delta < -1e-6 or new<old and delta<=.025 or improved_architecture and delta<=.05)


def validate_native_placement(native,proposed,analysis,frames,catalogue,*,support_policies=()):
    from copy import deepcopy
    applied=native.get('applied_plan');contacts=native.get('contacts')
    if not isinstance(applied,dict) or not isinstance(contacts,dict) or not isinstance(contacts.get('passed'),bool) or not isinstance(contacts.get('checks'),list):
        raise AgentError('INVALID_CONTACT_RECEIPT','Native applied plan and contact checks required')
    validate_plan(applied,analysis,frames,catalogue)
    expected=deepcopy(proposed);by_key={o['key']:o for o in expected['objects']};seen=set();supports={o['key']:o['support_key'] for o in analysis['objects']}
    policies={p['object_key']:p for p in support_policies}
    for row in contacts['checks']:
        key=row.get('object_key');parent=row.get('support_key')
        unknown_support=parent is None and row.get('status')=='unresolved' and policies.get(key,{}).get('contact_policy')=='unresolved'
        if key not in by_key or (parent not in by_key and not unknown_support) or key==parent or key in seen or row.get('status') not in {'contact','offset_evidenced','unresolved'}:raise AgentError('INVALID_CONTACT_RECEIPT','Invalid native contact evidence')
        if supports.get(key) is not None and parent!=supports[key]:raise AgentError('INVALID_CONTACT_RECEIPT','Native changed the observed support relationship')
        seen.add(key)
        if row['status'] in {'contact','offset_evidenced'}:
            shift=row.get('required_shift_y_m');gap=row.get('residual_gap_m')
            if not isinstance(shift,(float,int)) or not math.isfinite(shift) or abs(shift)>.5 or not isinstance(gap,(float,int)) or not math.isfinite(gap):raise AgentError('INVALID_CONTACT_RECEIPT','Unbounded or unverified native correction')
            if row['status']=='offset_evidenced':
                policy=policies.get(key,{})
                if policy.get('contact_policy')!='offset_evidenced' or policy.get('evidence_hashes')!=row.get('evidence_hashes') or not 0<=gap<=.25 or abs(gap-policy.get('offset_m',-1))>1e-6:raise AgentError('INVALID_CONTACT_RECEIPT','Unproposed contact offset')
            elif not 0<=gap<=.003:raise AgentError('INVALID_CONTACT_RECEIPT','Unverified contact gap')
            by_key[key]['position_m'][1]+=shift
    if any(o['support_key'] is not None and o['key'] not in seen for o in analysis['objects']) or contacts['passed']!=all(c['status'] in {'contact','offset_evidenced'} for c in contacts['checks']):raise AgentError('INVALID_CONTACT_RECEIPT','Missing or inconsistent support checks')
    actual=deepcopy(applied)
    for item in actual['objects']:
        wanted=by_key[item['key']]
        if not np.allclose(item['position_m'],wanted['position_m'],atol=1e-5,rtol=0):raise AgentError('INVALID_CONTACT_RECEIPT','Native placement differs from measured correction')
        item['position_m']=wanted['position_m']
    if actual!=expected:raise AgentError('INVALID_CONTACT_RECEIPT','Unexpected native plan mutation')
    return applied


class ReferenceWorker:
    def __init__(self,settings,store,artifacts,runner):
        self.settings,self.store,self.artifacts,self.runner=settings,store,artifacts,runner
        from .reference_commands import install
        install(store)
        self.root=settings.state/'reconstructions';self.root.mkdir(exist_ok=True)
        self.last_record_focus=0
        with store.tx() as c:c.execute('CREATE TABLE IF NOT EXISTS reference_runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id),status TEXT NOT NULL,body TEXT NOT NULL)')

    def _event(self,sid,kind,data):
        with self.store.tx() as c:self.store.event(c,sid,kind,data)

    def save(self,job):
        with self.store.tx() as c:c.execute('UPDATE reference_runs SET status=?,body=? WHERE id=?',(job['state'],canonical(job),job['id']))

    def guard(self,sid):
        with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE session_id=?',(sid,)).fetchone()
        job=json.loads(row[0]);directory=self.root/job['id']
        with closing(self.store.connect()) as c:session=c.execute('SELECT stop_requested,state FROM sessions WHERE id=?',(sid,)).fetchone()
        if self.runner.shutdown.is_set():raise AgentError('SERVICE_STOPPING','Reconstruction stopped; no automatic replay')
        if session['stop_requested'] or (directory/'native-stop.json').exists():raise AgentError('STOP_REQUESTED','Native reconstruction stopped; no automatic replay')
        if session['state'] in {'completed','interrupted','limit_reached','recovery_required'}:raise AgentError('SESSION_TERMINAL','Reference session has stopped')
        if not (directory/'native-conflict.json').exists() and datetime.now(timezone.utc)>=datetime.fromisoformat(job['deadline_utc']):raise AgentError('SESSION_DEADLINE','Reconstruction time limit reached')

    def status(self,job,state,message,**extra):
        job['state']=state;job['message']=message;job.update(extra);self.save(job)
        atomic(self.root/job['id']/'status.json',dict(state=state,message=message,**extra))

    def recover_startup(self):
        with closing(self.store.connect()) as c:rows=c.execute("SELECT body FROM reference_runs WHERE status NOT IN ('completed','interrupted','failed')").fetchall()
        for row in rows:
            job=json.loads(row[0]);self.status(job,'interrupted','Service restarted; no provider call or native construction is replayed')
            with self.store.tx() as c:self.store.update_session(c,job['session_id'],state='interrupted',verdict='inconclusive',stop_reason=job['message'])

    def next_ready(self):
        owner=self.settings.state/'reference-owner.json'
        if owner.is_file() and not owner.is_symlink() and time.monotonic()-self.last_record_focus>=1:
            try:data=json.loads(owner.read_text())
            except (OSError,ValueError):data={}
            job_id=data.get('id','')
            if re.fullmatch('[a-f0-9]{32}',job_id) and not (self.root/job_id/'bundle.json').exists():
                self.last_record_focus=time.monotonic();self.runner.focus_editor('reference-recording-'+job_id)
        for path in sorted(self.root.glob('*/bundle.json')):
            if not re.fullmatch('[a-f0-9]{32}',path.parent.name):continue
            contained(self.root,path)
            with closing(self.store.connect()) as c:exists=c.execute('SELECT 1 FROM reference_runs WHERE id=?',(path.parent.name,)).fetchone()
            if not exists and not (path.parent/'native-stop.json').exists():
                with closing(self.store.connect()) as c:
                    admitted=c.execute('SELECT app_actions.state,commands.status FROM app_actions JOIN commands ON commands.id=app_actions.command_id WHERE run_id=?',(path.parent.name,)).fetchone()
                if admitted and (admitted['state']!='preparing' or admitted['status']!='succeeded'):continue
                return path
            if exists and (path.parent/'resume-request.json').exists() and not (path.parent/'native-stop.json').exists():
                with closing(self.store.connect()) as c:row=c.execute('SELECT status,body FROM reference_runs WHERE id=?',(path.parent.name,)).fetchone()
                if row['status']=='interrupted' and not json.loads(row['body']).get('resume_count'):return path
        return None

    def resume_claim(self,path):
        directory=Path(path).parent;request=json.loads((directory/'resume-request.json').read_text())
        with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(directory.name,)).fetchone()
        job=json.loads(row[0])
        if request!={'cached_sam_only':True,'new_layout_only':True} or job['state']!='interrupted' or job.get('resume_count') or job['attempts'] or list(directory.glob('plan-*.json')) or list(directory.glob('receipt-*.json')):raise AgentError('RESPONSE_RECOVERY_REFUSED','Only a pre-construction checkpoint can continue once; no replay')
        if hashlib.sha256(Path(path).read_bytes()).hexdigest()!=job['input_bundle_sha256'] or hashlib.sha256((directory/job['bundle']['catalogue_file']).read_bytes()).hexdigest()!=job['catalogue_sha256']:raise AgentError('STALE_VERSION','Reference inputs changed since the checkpoint')
        response=job.get('analysis_response')
        if not response:raise AgentError('RESPONSE_RECOVERY_REFUSED','A completed settled analysis is required')
        with closing(self.store.connect()) as c:
            call=c.execute('SELECT status FROM calls WHERE id=?',(response['call_id'],)).fetchone()
            envelope=c.execute("SELECT body FROM events WHERE subject=? AND kind='provider_envelope' ORDER BY id DESC LIMIT 1",(response['call_id'],)).fetchone()
        if not call or call['status']!='settled' or not envelope or json.loads(envelope[0])['artifact_hash']!=response['artifact_hash']:raise AgentError('RESPONSE_RECOVERY_REFUSED','Analysis receipt is not a known completed paid response')
        original=json.loads(self.artifacts.read(response['artifact_hash']))
        if json.loads(terminal_text(original))!=response['value']:raise AgentError('RESPONSE_RECOVERY_REFUSED','Stored analysis differs from provider evidence')
        for frame in job['frames']:self.artifacts.read(frame['artifact_hash'])
        with self.store.tx() as c:
            if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached')").fetchone():raise AgentError('SESSION_ACTIVE','Another session owns the editor')
            self.store.update_session(c,job['session_id'],state='preflight',verdict='pending',stop_reason=None)
            c.execute('UPDATE sessions SET stop_requested=0 WHERE id=?',(job['session_id'],))
            self.store.event(c,job['session_id'],'reference_checkpoint_continued',dict(analysis_call_id=response['call_id'],cached_sam_only=True,provider_retry=False,native_replay=False))
        job.update(state='preflight',resume_count=1,deadline_utc=(datetime.now(timezone.utc)+timedelta(seconds=1200)).isoformat());self.save(job);return job

    def claim(self,path):
        path=contained(self.root,Path(path));raw=path.read_bytes()
        if len(raw)>1_000_000:raise AgentError('INVALID_INPUT','Reference bundle exceeds its size bound',422)
        bundle=json.loads(raw);job_id=path.parent.name
        if bundle['id']!=job_id or not re.fullmatch('[a-f0-9]{32}',job_id) or bundle['kind'] not in {'recorded','external'}:raise AgentError('INVALID_INPUT','Invalid native reference bundle',422)
        if bundle['provider_mode']!=self.settings.provider_mode or self.settings.provider_mode!='live':raise AgentError('OFFLINE_MODE','Live reference reconstruction requires the explicitly configured live service')
        if type(bundle['max_iterations']) is not int or not 1<=bundle['max_iterations']<=6 or type(bundle['session_timeout_seconds']) is not int or not 1200<=bundle['session_timeout_seconds']<=2400:raise AgentError('INVALID_INPUT','Reconstruction is bounded to six candidates and forty minutes',422)
        policy=default_policy() if bundle.get('fidelity_mode')=='1.0' else None
        if bundle.get('fidelity_mode') not in {None,'1.0'}:raise AgentError('INVALID_INPUT','Unknown fidelity policy version')
        if policy:policy.update(max_candidates=bundle['max_iterations'],max_seconds=bundle['session_timeout_seconds'])
        if policy:
            policy['scale_mode']=bundle.get('scale_mode','locked');payload('FidelityPolicy',policy)
        noise=None;noise_path=self.settings.state/'reports'/'reference-fidelity-noise.json'
        if policy and bundle['kind']=='recorded' and noise_path.is_file():
            measured=json.loads(noise_path.read_text())
            source=read_capture(contained(self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',Path(bundle['capture_directory'])))
            if measured.get('kind')=='same_applied_plan_native_capture_repetition' and measured.get('conditions_hash')==source['request']['conditions_hash'] and measured.get('inspection_hash')==source['request']['inspection_hash'] and isinstance(measured.get('noise_bound'),(int,float)) and math.isfinite(measured['noise_bound']) and 0<=measured['noise_bound']<=.01:
                noise=measured;policy['noise_baseline_hash']=fingerprint(noise)
        sid='reference-'+job_id;scene_id='reference-scene-'+job_id
        job=dict(id=job_id,session_id=sid,state='preflight',created_at=utc_now(),deadline_utc=(datetime.now(timezone.utc)+timedelta(seconds=bundle['session_timeout_seconds'])).isoformat(),input_bundle_sha256=hashlib.sha256(raw).hexdigest(),bundle=bundle,attempts=[],provider_mode=self.settings.provider_mode)
        if policy:
            job['fidelity_policy']=policy;job['policy_hash']=fingerprint(policy);atomic(path.parent/'fidelity-policy.json',policy)
            if noise:job['capture_noise']=noise;job['capture_noise_artifact']=self.artifacts.put(canonical(noise).encode(),'application/json')
        with self.store.tx() as c:
            if c.execute('SELECT 1 FROM reference_runs WHERE id=?',(job_id,)).fetchone():raise AgentError('REFERENCE_ALREADY_STARTED','Reference job is never implicitly replayed')
            from .reference_commands import verify_adoption
            admission=verify_adoption(c,bundle,job['input_bundle_sha256'],self.artifacts)
            if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached') AND id!=?",(admission['session_id'] if admission else '',)).fetchone():raise AgentError('SESSION_ACTIVE','Another session owns the editor')
            if not c.execute('SELECT 1 FROM projects WHERE id=?',(bundle['project_id'],)).fetchone():raise AgentError('NOT_FOUND','Native project must have been registered',404)
            budget=Budget(self.store,load_pricing(self.settings.state/'pricing.json'))
            if not self.settings.api_key or not budget.state(c)['live_enabled']:raise AgentError('COST_BOUND_UNKNOWN','Reconciled global budget and live key required')
            if not admission:c.execute('INSERT INTO scenes VALUES(?,?,?)',(scene_id,bundle['project_id'],canonical(dict(kind='reference_reconstruction',input_bundle_sha256=job['input_bundle_sha256']))))
            session=payload('Session',dict(id=sid,state='preflight',verdict='pending',best_version='reference-pending',current_version='reference-pending',attempts_used=0,max_attempts=bundle['max_iterations'],criteria_hash=job.get('policy_hash') or fingerprint(dict(metric='reference_priority_regions_v2',priority_view=bundle.get('priority_view','work-top-front'),priority_weight=.55,global_weight=.25,worst_object_weight=.2,view_regression_bound=.025,object_regression_bound=.06,exact_fidelity_unverified=True)),inspection_hash=fingerprint(bundle.get('inspection',{})),stop_reason=None,provider_mode='live'))
            if admission:
                if sid!=admission['session_id']:raise AgentError('APP_BUNDLE_MISMATCH','Reserved session differs')
                c.execute("UPDATE sessions SET body=? WHERE id=?",(canonical(session),sid))
                c.execute("UPDATE app_actions SET state='running',bundle_hash=? WHERE id=?",(job['input_bundle_sha256'],admission['id']))
            else:c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',(sid,bundle['project_id'],scene_id,'preflight',canonical(session)))
            c.execute('INSERT INTO reference_runs VALUES(?,?,?,?)',(job_id,sid,'preflight',canonical(job)))
            self.store.event(c,sid,'reference_created',dict(job_id=job_id,input_bundle_sha256=job['input_bundle_sha256'],source_scene_transforms_provided=False))
        return job

    def wait_render(self,job,ordinal):
        directory=self.root/job['id'];file=directory/f'render-{ordinal}.json'
        def wait(sid,cleanup=False):
            paused_at=None
            while not file.exists():
                conflict=(directory/'native-conflict.json').exists()
                if conflict and paused_at is None:
                    paused_at=time.monotonic();self.status(job,'paused','Modification de scène détectée : mesure en pause, modifications conservées. Reprise disponible dans Unity après vérification de la version.')
                if not conflict and paused_at is not None:
                    from datetime import timedelta
                    job['deadline_utc']=(datetime.fromisoformat(job['deadline_utc'])+timedelta(seconds=time.monotonic()-paused_at)).isoformat()
                    paused_at=None;self.status(job,'rendering','Reprise de la mesure hors écran ; aucun appel modèle rejoué.')
                self.guard(sid);time.sleep(.25)
            result=json.loads(file.read_text());self.guard(sid)
            if result['ordinal']!=ordinal:raise AgentError('STALE_VERSION','Native reference receipt ordinal differs')
            expected_prefix=f"Assets/AgentWorkspace/Runs/repro-{job['id']}-{ordinal}/"
            if result['scene_path']!=expected_prefix+'Reconstruction.unity':raise AgentError('OUT_OF_SCOPE','Native reconstruction escaped its owned scope')
            if result.get('capture_mode')=='floorplan_offscreen':
                path=contained(directory,Path(result['capture_directory']))
                proof=json.loads((path/'result.json').read_text())
                if proof.get('camera')!=job.get('composition',{}).get('camera') or proof.get('scene_path')!=result['scene_path']:raise AgentError('STALE_EVIDENCE','Offscreen camera or scene differs from requested composition')
                if proof['version']!=result['version'] or proof['status']!='complete':raise AgentError('STALE_VERSION','Offscreen capture version mismatch')
                for name in ('beauty','geometry'):
                    if hashlib.sha256((path/(name+'.png')).read_bytes()).hexdigest()!=proof[name+'_sha256']:raise AgentError('HASH_MISMATCH','Offscreen image changed')
                result['composition_proof']=proof
                return result,dict(directory=path,request=dict(version_id=result['version']),statics=[dict(camera_key=job['frames'][0]['key'],file='beauty.png')],result=dict(performance=None,composition=proof))
            capture_path=contained(self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',Path(result['capture_directory']))
            capture=read_capture(capture_path)
            if capture['request']['version_id']!=result['version']:raise AgentError('STALE_VERSION','Candidate frame version differs from construction')
            return result,capture
        # Same tested macOS focus owner as the inspection workflow. Its use is
        # labelled separately from comparative performance or bake qualification.
        if job.get('composition'):return wait(job['session_id'])
        from copy import copy
        focus_runner=copy(self.runner);focus_runner._capture_once=wait
        return focus_runner._capture_with_focus(job['session_id'])

    def inspect_candidate(self,job,attempt,analysis,details,catalogue=(),provider=None):
        if not job['bundle'].get('scene_inspection'):return []
        from .reference_inspection import inspection_targets,read_inspection,room_inspection_targets,segment_room_observations,choose_room_closeups
        history=[a.get('inspection_targets',[]) for a in job['attempts']]
        views=inspection_targets(analysis,details,attempt['metrics'],history)
        if not views and job['bundle']['kind']=='external':
            views=room_inspection_targets(attempt['applied_plan'],catalogue,attempt['ordinal'])
            prior=next((a for a in reversed(job['attempts']) if a['ordinal']<attempt['ordinal'] and a.get('inspection_pairs')),None)
            if views and prior and provider is not None:
                try:
                    extra,response=choose_room_closeups(provider,self.artifacts,attempt['applied_plan'],catalogue,prior['inspection_pairs'],attempt['candidate_frames'])
                    attempt['inspection_camera_response']=response
                    if extra:views=views[:10]+extra
                except AgentError as error:
                    if error.code!='INVALID_INSPECTION_CAMERA':raise
                    attempt['inspection_camera_rejected']=dict(reason=error.code,fallback='bounded_default_closeups',retry_attempted=False)
        if not views:return []
        directory=self.root/job['id'];ordinal=attempt['ordinal'];native=attempt['native']
        geometry=attempt['metrics'].get('geometry',{}).get('per_object',{})
        def residual(key):
            if geometry:
                iou=geometry.get(key,{}).get('mean_iou');return None if iou is None else 1-iou
            return attempt['metrics']['per_object'].get(key,{}).get('priority_rgb_mae')
        request=dict(ordinal=ordinal,version=native['version'],scene_path=native['scene_path'],views=views,objects=[dict(key=o['key'],support_key=o['support_key'],residual=residual(o['key'])) for o in analysis['objects']])
        if job.get('fidelity_policy'):job.setdefault('decisions',[]).append(dict(action='observing',reason='geometric_residual_and_missing_coverage',ordinal=ordinal,version=native['version'],target_keys=list(dict.fromkeys(v['object_key'] for v in views))))
        attempt['inspection_targets']=views;self.save(job)
        self.status(job,'inspecting','La caméra Scene observe les objets incertains de près…')
        atomic(directory/f'inspection-request-{ordinal}.json',request)
        output=directory/f'inspection-{ordinal}'
        while not (output/'result.json').exists():
            self.guard(job['session_id'])
            if (output/'interruption.json').exists():raise AgentError('NATIVE_INTERRUPTED','Scene inspection interrupted; no replay')
            time.sleep(.25)
        self.guard(job['session_id'])
        pairs=read_inspection(output,request,details,self.artifacts)
        if provider is not None and any(p.get('reference') is None for p in pairs):
            pairs=segment_room_observations(pairs,provider,self.artifacts)
        self._event(job['session_id'],'reference_scene_inspection',dict(ordinal=ordinal,views=len(pairs),version=native['version'],performance_qualified=False))
        return pairs

    def acquire_pose_geometry(self,job,analysis,catalogue):
        if not job['bundle'].get('pose_geometry'):return []
        ids=sorted({o['asset_id'] for o in analysis['objects'] if o['asset_id'] is not None})
        directory=self.root/job['id'];self.status(job,'geometry','Préparation des silhouettes des prefabs candidats…')
        atomic(directory/'geometry-request.json',dict(catalogue_sha256=job['catalogue_sha256'],asset_ids=ids))
        result=directory/'geometry-result.json'
        while not result.exists():self.guard(job['session_id']);time.sleep(.25)
        if result.stat().st_size>50_000_000:raise AgentError('INVALID_GEOMETRY','Candidate geometry exceeds size bound')
        value=json.loads(result.read_text());by_id={a['asset_id']:a for a in catalogue}
        if value['catalogue_sha256']!=job['catalogue_sha256'] or sorted(a['asset_id'] for a in value['assets'])!=ids:raise AgentError('INVALID_GEOMETRY','Candidate geometry catalogue differs')
        for asset in value['assets']:
            if asset['dependency_hash']!=by_id[asset['asset_id']]['dependency_hash']:raise AgentError('INVALID_GEOMETRY','Candidate mesh dependency differs')
            count=0
            for mesh in asset['meshes']:
                v=np.asarray(mesh['vertices']);t=np.asarray(mesh['triangles']);count+=len(v)
                if v.ndim!=2 or v.shape[1]!=3 or count>100000 or not np.isfinite(v).all() or t.ndim!=1 or len(t)%3 or t.dtype.kind not in 'iu' or t.min(initial=0)<0 or t.max(initial=0)>=len(v):raise AgentError('INVALID_GEOMETRY','Invalid bounded static mesh')
        job['pose_geometry_hash']=self.artifacts.put(result.read_bytes(),'application/json');self.save(job)
        return value['assets']

    def acquire_details(self,job,analysis,frames):
        directory=self.root/job['id']
        checkpoint=job['bundle'].get('detail_checkpoint_job_id')
        if checkpoint:
            if job.get('analysis_reused_from')!=job['bundle'].get('analysis_checkpoint_job_id'):raise AgentError('STALE_VERSION','Closeups require verified reused analysis')
            previous=contained(self.root,self.root/checkpoint)
            with closing(self.store.connect()) as c:origin=c.execute('SELECT body FROM reference_runs WHERE id=?',(checkpoint,)).fetchone()
            if checkpoint!=job['analysis_reused_from'] and (not origin or json.loads(origin[0]).get('analysis_response',{}).get('value')!=analysis):raise AgentError('STALE_VERSION','Ancestor closeups must match the exact object analysis')
            old_private=json.loads((previous/'source-private.json').read_text());new_private=json.loads((directory/'source-private.json').read_text())
            if old_private['source_scene_sha256']!=new_private['source_scene_sha256']:raise AgentError('STALE_VERSION','Preserved source differs from recorded closeups')
            old_bundle=json.loads((previous/'bundle.json').read_text())
            source=read_capture(contained(self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',Path(old_bundle['capture_directory'])))
            details=native_details(json.loads((previous/'detail-result.json').read_text()),analysis,self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',source['request']['version_id'],self.artifacts)
            job['details_reused_from']=checkpoint
        elif not job['bundle'].get('detail_capture'):
            details=original_crops(analysis,frames,self.artifacts)
            job['detail_limit']='Crops use available source pixels; no unseen detail or additional camera coverage is recovered.'
        else:
            self.status(job,'analysing','Enregistrement de gros plans réels par objet : face, dos et dessus…')
            atomic(directory/'detail-request.json',dict(input_bundle_sha256=job['input_bundle_sha256'],objects=[{k:item[k] for k in ['key','view_boxes']} for item in analysis['objects']]))
            def wait(sid,cleanup=False):
                while not (directory/'detail-result.json').exists():self.guard(sid);time.sleep(.25)
                self.guard(sid);return json.loads((directory/'detail-result.json').read_text())
            from copy import copy
            focus=copy(self.runner);focus._capture_once=wait
            result=focus._capture_with_focus(job['session_id'])
            source=read_capture(contained(self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',Path(job['bundle']['capture_directory'])))
            details=native_details(result,analysis,self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',source['request']['version_id'],self.artifacts)
            job['detail_limits']=result['limits']
        job['detail_frames']=details;self.save(job);self._event(job['session_id'],'reference_details',dict(count=len(details),acquisitions=sorted({f['acquisition'] for f in details})))
        return details

    def visual_asset_match(self,job,analysis,frames,catalogue,provider,segments,details=None):
        if job.get('resume_count'):
            # A continuation cannot replay an unknown asset-selection call.
            # Keep only settled responses already attached to this checkpoint;
            # the original visual analysis supplies explicitly provisional IDs.
            effective=deepcopy(analysis);by_key={o['key']:o for o in effective['objects']};verified=[];matched=set()
            for response in job.get('object_asset_matches',[]):
                with closing(self.store.connect()) as c:call=c.execute('SELECT status FROM calls WHERE id=?',(response['call_id'],)).fetchone()
                if not call or call['status']!='settled' or json.loads(terminal_text(json.loads(self.artifacts.read(response['artifact_hash']))))!=response['value']:
                    raise AgentError('RESPONSE_RECOVERY_REFUSED','Asset selection is not verified settled evidence')
                for match in response['value']['matches']:
                    if match['object_key'] not in by_key:raise AgentError('RESPONSE_RECOVERY_REFUSED','Asset selection names an unknown object')
                    by_key[match['object_key']]['asset_id']=match['asset_id'];matched.add(match['object_key'])
                verified.append(response)
            validate_analysis(effective,frames,catalogue)
            job.update(asset_match_response=dict(object_responses=verified,mode='settled_checkpoint_only'),effective_analysis=effective,provisional_asset_keys=[o['key'] for o in effective['objects'] if o['asset_id'] is not None and o['key'] not in matched])
            self.save(job);self._event(job['session_id'],'reference_asset_checkpoint_only',dict(verified_count=len(verified),provisional_keys=job['provisional_asset_keys'],network_sent=False));return effective
        checkpoint=job.get('analysis_reused_from')
        if checkpoint:
            with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(checkpoint,)).fetchone()
            prior=json.loads(row[0]) if row else {};responses=prior.get('asset_match_response',{}).get('object_responses',[])
            if responses:
                effective=deepcopy(analysis);by_key={o['key']:o for o in effective['objects']};known=True
                for response in responses:
                    with closing(self.store.connect()) as c:call=c.execute('SELECT status FROM calls WHERE id=?',(response['call_id'],)).fetchone()
                    if not call or call['status']!='settled' or json.loads(terminal_text(json.loads(self.artifacts.read(response['artifact_hash']))))!=response['value']:known=False;break
                    for match in response['value']['matches']:
                        if match['object_key'] not in by_key:known=False;break
                        by_key[match['object_key']]['asset_id']=match['asset_id']
                if known:
                    validate_analysis(effective,frames,catalogue)
                    expected={o['key']:o['asset_id'] for o in prior.get('effective_analysis',{}).get('objects',[])}
                    if {o['key']:o['asset_id'] for o in effective['objects']}==expected:
                        job.update(asset_match_response=prior['asset_match_response'],effective_analysis=effective,asset_identities_reused_from=checkpoint);self.save(job)
                        self._event(job['session_id'],'reference_asset_identity_memory',dict(checkpoint=checkpoint,source_evidence_verified=True,network_sent=False));return effective
        groups=candidate_groups(analysis,catalogue)
        if not groups:return analysis
        for group in groups:group['size_evidence']=size_evidence(group,frames,segments)
        job['asset_size_evidence']=[dict(object_key=g['object_key'],scores=g['size_evidence']) for g in groups];self.save(job)
        directory=self.root/job['id'];ids=list(dict.fromkeys(a['asset_id'] for group in groups for a in group['candidates']))
        self.status(job,'previewing','Comparaison des variantes de meubles et de sol avec leurs aperçus Unity…')
        atomic(directory/'preview-request.json',dict(asset_ids=ids,catalogue_sha256=job['catalogue_sha256']))
        while not (directory/'preview-result.json').exists():self.guard(job['session_id']);time.sleep(.25)
        previews=json.loads((directory/'preview-result.json').read_text())
        if not all(any(p['asset_id']==a['asset_id'] and p.get('file') for p in previews) for g in groups for a in g['candidates']):
            job['asset_preview_limit']='Some native asset previews unavailable; original visual analysis retained';self.save(job);return analysis
        sheets=boards(groups,frames,previews,directory,self.artifacts)
        completed=[]
        if job.get('details_reused_from'):
            with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(job['details_reused_from'],)).fetchone()
            if row:completed=json.loads(row[0]).get('asset_match_response',{}).get('object_responses',[])
        def retain(response):
            job.setdefault('object_asset_matches',[]).append(response);self.save(job)
        def recover(request):
            self.guard(job['session_id'])
            with closing(self.store.connect()) as c:known=c.execute("SELECT id FROM calls WHERE payload_hash=? AND status='settled' ORDER BY created_at DESC",(fingerprint(request),)).fetchall()
            for call in known:
                try:return provider.recover_completed(call['id'],request,'ModelReferenceAssetSelection')
                except AgentError as error:
                    if error.code!='RESPONSE_RECOVERY_REFUSED':raise
            return None
        effective,response=select_assets(provider,self.artifacts,analysis,frames,groups,sheets,details=details,previews=previews,directory=directory,completed_responses=completed,on_response=retain,recover_exact=recover)
        job.update(asset_match_response=response,asset_matching_sheets=sheets,effective_analysis=effective);self.save(job);self._event(job['session_id'],'reference_asset_matching',response);return effective

    def checkpoint_analysis(self,job,frames,catalogue):
        checkpoint=job['bundle']['analysis_checkpoint_job_id']
        if not re.fullmatch('[a-f0-9]{32}',checkpoint):raise AgentError('INVALID_INPUT','Invalid analysis checkpoint')
        with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(checkpoint,)).fetchone()
        if not row:raise AgentError('RESPONSE_RECOVERY_REFUSED','Reference analysis checkpoint unavailable')
        previous=json.loads(row[0]);response=previous.get('analysis_response')
        old_catalogue=json.loads((self.root/checkpoint/previous['bundle']['catalogue_file']).read_text())
        identity_fields=['asset_id','name','bounds_center_m','bounds_size_m','asset_guid','dependency_hash','path']
        same_catalogue=[{key:a.get(key) for key in identity_fields} for a in old_catalogue]==[{key:a.get(key) for key in identity_fields} for a in catalogue]
        if not response or not same_catalogue or [f['artifact_hash'] for f in frames]!=[f['artifact_hash'] for f in previous['frames']] or [f['calibration'] for f in frames]!=[f['calibration'] for f in previous['frames']]:raise AgentError('STALE_VERSION','Recorded reference or catalogue differs from completed analysis')
        with closing(self.store.connect()) as c:call=c.execute('SELECT status FROM calls WHERE id=?',(response['call_id'],)).fetchone()
        if not call or call['status']!='settled' or json.loads(terminal_text(json.loads(self.artifacts.read(response['artifact_hash']))))!=response['value']:raise AgentError('RESPONSE_RECOVERY_REFUSED','A known completed paid analysis is required')
        validate_analysis(response['value'],frames,catalogue);job['analysis_reused_from']=checkpoint;return response

    def recorded_scale_origin(self,job,checkpoint):
        """Use a completed paid layout in this reference lineage, not an audit."""
        seen=set();origin=None
        for _ in range(32):
            if not checkpoint or checkpoint in seen:return origin
            self.guard(job['session_id']);seen.add(checkpoint)
            with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(checkpoint,)).fetchone()
            if not row:return origin
            prior=json.loads(row[0])
            for attempt in prior.get('attempts',[]):
                response=attempt.get('provider_response',{})
                if not all(k in response for k in ['call_id','artifact_hash','value']):continue
                with closing(self.store.connect()) as c:call=c.execute('SELECT status FROM calls WHERE id=?',(response['call_id'],)).fetchone()
                if call and call['status']=='settled' and json.loads(terminal_text(json.loads(self.artifacts.read(response['artifact_hash']))))==response['value']:
                    origin=dict(plan=response['value'],run_id=checkpoint,call_id=response['call_id'],artifact_hash=response['artifact_hash']);break
            checkpoint=prior['bundle'].get('analysis_checkpoint_job_id')
        return origin

    def run(self,path):
        job=None;provider=None
        try:
            resuming=(Path(path).parent/'resume-request.json').exists()
            job=self.resume_claim(path) if resuming else self.claim(path);sid=job['session_id'];directory=self.root/job['id'];bundle=job['bundle']
            brief=bundle['brief']
            if bundle.get('building_policy')=='atmospheric-house':brief='[building-prefabs-required] '+brief+' Interior family '+bundle['interior_style']+'; connected '+bundle['ceiling_prefab']+' ceiling required.'
            self.status(job,'preflight','Préparation des images et du catalogue local…')
            catalogue_path=contained(directory,directory/bundle['catalogue_file']);catalogue_raw=catalogue_path.read_bytes()
            if len(catalogue_raw)>1_000_000:raise AgentError('INVALID_CATALOGUE','Catalogue exceeds native handoff limit')
            catalogue=json.loads(catalogue_raw);frames=job['frames'] if resuming else ingest(bundle,directory,self.artifacts)
            appearance_reference=read_capture(contained(self.settings.workspace/'unity/HDRPValidation/.hdrp-agent/captures',Path(bundle['capture_directory']))) if job.get('fidelity_policy') and bundle['kind']=='recorded' else None
            job['frames']=frames;job['catalogue_sha256']=hashlib.sha256(catalogue_raw).hexdigest();self.save(job)
            budget=SessionBudget(self,sid,Budget(self.store,load_pricing(self.settings.state/'pricing.json')))
            provider=MetaResponses(self.settings,budget,self.artifacts);planner=ReferencePlanner(provider,self.artifacts)
            self.guard(sid);self.status(job,'analysing','Muse analyse les objets, la composition et les caméras…')
            analysed=job['analysis_response'] if resuming else self.checkpoint_analysis(job,frames,catalogue) if bundle.get('analysis_checkpoint_job_id') else planner.analyse(frames,catalogue,brief);validate_analysis(analysed['value'],frames,catalogue);job['analysis_response']=analysed;self.save(job);self._event(sid,'reference_analysis_reused' if resuming or bundle.get('analysis_checkpoint_job_id') else 'reference_analysis',analysed)
            details=self.acquire_details(job,analysed['value'],frames) if bundle.get('asset_visual_matching') else []
            self.status(job,'segmenting','SAM mesure chaque objet, la vue du dessus et les gros plans…')
            def save_segments(partial):
                self.guard(sid);job['segments']=partial;self.save(job)
            segments=planner.segment(analysed['value'],frames,cached_only=resuming or bundle.get('cached_sam_only',False),details=details,comprehensive=bundle.get('autonomous_refinement',False),checkpoint=save_segments,extra_angles=bundle.get('fidelity_mode')=='1.0');job['segments']=segments;self.save(job)
            effective=self.visual_asset_match(job,analysed['value'],frames,catalogue,provider,segments,details) if bundle.get('asset_visual_matching') else analysed['value']
            seed=None;prior={}
            checkpoint=bundle.get('analysis_checkpoint_job_id')
            seed_checkpoint=checkpoint
            for depth in range(32):
                if not seed_checkpoint:break
                with closing(self.store.connect()) as c:row=c.execute('SELECT body FROM reference_runs WHERE id=?',(seed_checkpoint,)).fetchone()
                prior=json.loads(row[0]) if row else {}
                if prior.get('state')=='completed' and isinstance(prior.get('best_ordinal'),int):
                    candidate=prior['attempts'][prior['best_ordinal']]['applied_plan']
                    expected={o['key']:o['asset_id'] for o in effective['objects']}
                    actual={o['key']:o['asset_id'] for o in candidate['objects'] if o['key'] in expected}
                    if actual==expected:
                        validate_plan(candidate,effective,frames,catalogue);seed=candidate;job['layout_reused_from']=seed_checkpoint
                    break
                # Only follow the existing same-reference checkpoint lineage;
                # never use an unrelated source or an interrupted candidate.
                seed_checkpoint=prior.get('bundle',{}).get('analysis_checkpoint_job_id')
            composition_requested=bundle['kind']=='external' and not job.get('fidelity_policy') and len(frames)==1 and '[building-prefabs-required]' in brief
            geometry=None if composition_requested else self.acquire_pose_geometry(job,effective,catalogue)
            policy=job.get('fidelity_policy')
            external_visual=bundle['kind']=='external' and not policy
            if external_visual:job['evaluation_mode']='uncalibrated_image_visual';self.save(job)
            composition_plan=None
            if composition_requested:
                from .floorplan import extract,optimize,build_plan,checkpoint as save_composition
                self.status(job,'composition','Extraction des pièces et optimisation des contraintes de placement…')
                composition_evidence=fingerprint(dict(frames=frames,catalogue=job['catalogue_sha256'],analysis=effective,segments=segments,brief=brief,solver_version='floorplan-2'))
                saved=prior.get('composition',{})
                observation=saved['observation'] if saved.get('evidence_hash')==composition_evidence else extract(provider,self.artifacts,frames,effective,catalogue,segments,brief)
                fit=optimize(observation['value'],guard=lambda:self.guard(sid))
                composition_plan,composition=build_plan(observation['value'],fit,effective,catalogue,frames[0])
                job['composition']=dict(composition,observation=observation,evidence_hash=composition_evidence)
                save_composition(directory/'composition-checkpoint.json',job['composition']);self.save(job)

            scale_origin=self.recorded_scale_origin(job,checkpoint) if policy and checkpoint else None
            if scale_origin:job['scale_origin']=scale_origin;self.save(job)
            evidence=evidence_key(frames,job['catalogue_sha256'])
            if policy:evidence=fingerprint(dict(reference=evidence,details=evidence_key(details,job['catalogue_sha256']),geometry=job.get('pose_geometry_hash'),segments=segments))
            # Upgrade historical checkpoints that archived poses but omitted the
            # rejected lighting/camera values. Reuse actual applied receipts only.
            for entry in (prior.get('memory') or {}).get('history',[]):
                if 'appearance_values' not in entry and entry.get('run_id')==prior.get('id'):
                    past=next((a for a in prior.get('attempts',[]) if a['ordinal']==entry['ordinal']),None)
                    if past and past.get('applied_plan'):
                        entry['appearance_values']={k:deepcopy(past['applied_plan'].get(k)) for k in ['lights','exposure_ev','sky_color_rgb','fog_mean_free_path_m','estimated_views']}
            memory=new_memory(evidence,effective,prior.get('memory'),bundle.get('priority_view','work-top-front'),policy_hash=job.get('policy_hash'),solver_version=policy['solver_version'] if policy else None);job['memory']=memory
            pose_frames=frames+details
            previous=None;previous_frames=None;metrics=None;best=None
            evaluation=GeometryEvaluator(pose_frames,segments,geometry,self.artifacts,width=1280,guard=lambda:self.guard(sid)) if policy and geometry else None
            search=GeometryEvaluator(frames,segments,geometry,self.artifacts,width=192,guard=lambda:self.guard(sid)) if policy and geometry else None
            relative_search=GeometryEvaluator(pose_frames,segments,geometry,self.artifacts,width=256,guard=lambda:self.guard(sid)) if policy and geometry else None
            stopping='candidate_limit'
            for ordinal in range(bundle['max_iterations']):
                self.guard(sid);self.status(job,'planning',f'Muse prépare la composition et les lumières ({ordinal+1}/{bundle["max_iterations"]})…')
                decision=(dict(action='baseline' if ordinal==0 else 'image_refinement',reason='uncalibrated_image_joint_visual_fit') if external_visual else next_action(job['attempts'],best,policy) if policy else dict(action=phase_for(ordinal),reason='legacy_fixed_phases'))
                job.setdefault('decisions',[]).append(decision);self.save(job)
                if decision['action']=='stop':stopping=decision['reason'];break
                phase=decision['action']
                photometry=None
                if external_visual and '[building-prefabs-required]' in brief and ordinal>0:
                    from .reference_plan_fit import exposure_probe
                    photometry=None if (best or {}).get('metrics',{}).get('architecture',{}).get('defect_count') else exposure_probe(job['attempts'])
                    if photometry is not None:phase='photometry_probe';decision['action']=phase;decision['reason']='measured_floor_luminance_bracket'
                appearance_experiment=appearance_step(memory) if policy and phase=='appearance' else None
                if composition_plan is not None:
                    if ordinal==0:proposed=dict(value=composition_plan,local_composition_solver=True)
                    else:
                        from .floorplan import correct_native
                        corrected=correct_native(best['applied_plan'],job['composition'],best['metrics']['composition'],catalogue)
                        if corrected is None:
                            stopping='composition_requires_aperture_and_silhouette_validation';break
                        if any(fingerprint(a.get('provider_response',{}).get('value',{}))==fingerprint(corrected) for a in job['attempts']):
                            stopping='composition_no_new_delta';break
                        proposed=dict(value=corrected,local_composition_solver=True)
                elif photometry is not None:proposed=dict(value=photometry,local_photometry_probe=True)
                elif ordinal==0 and seed is not None:proposed=dict(value=seed,reused_from=seed_checkpoint)
                elif policy and phase in {'anchoring','arranging','scaling'}:
                    base=proposal_base(job['attempts'],best,phase)
                    proposed=dict(value=base['applied_plan'],local_geometry_proposal=True,base_candidate_ordinal=base['ordinal'])
                elif not policy and not external_visual and ordinal==1 and geometry and bundle.get('autonomous_refinement'):proposed=dict(value=previous,local_mask_refinement=True)
                else:proposed=planner.layout(effective,frames,catalogue,segments,brief,previous,previous_frames,metrics,matched_assets=bool(job.get('asset_match_response')),memory=memory,phase=phase,inspection_pairs=best.get('inspection_pairs',[]) if best else [],appearance_experiment=appearance_experiment)
                self._event(sid,'reference_layout_reused' if 'reused_from' in proposed else 'reference_layout',proposed)
                plan=deepcopy(proposed['value']) if external_visual else constrain_proposal(proposed['value'],previous,phase,appearance_experiment);fits=[]
                if policy and previous:
                    scales={o['key']:o['scale'] for o in (base['applied_plan'] if phase in {'anchoring','arranging','scaling'} else previous)['objects']}
                    for item in plan['objects']:item['scale']=scales[item['key']]
                if policy and phase=='anchoring' and search:
                    from .reference_pose import fit_global_anchor
                    if scale_origin:
                        from .reference_scale import restore_origin_scale
                        plan,scale_proof=restore_origin_scale(plan,scale_origin['plan'],policy['scale_change_bound']);fits.append(scale_proof)
                    self.status(job,'fitting','Estimation visuelle de l’ancrage XYZ du groupe…')
                    plan,fit=fit_global_anchor(plan,search,policy,guard=lambda:self.guard(sid));fits.append(fit)
                elif policy and phase=='arranging' and search:
                    from .reference_pose import fit_relative_poses
                    supports=[dict(object_key=o['key'],support_key=o['support_key']) for o in effective['objects']]
                    for row in base['native']['contacts']['checks']:
                        edge=next((e for e in supports if e['object_key']==row['object_key']),None)
                        if edge is not None and edge['support_key'] is None:edge['support_key']=row['support_key']
                    self.status(job,'fitting','Ajustement des poses relatives aux supports, échelles verrouillées…')
                    plan,fit=fit_relative_poses(plan,relative_search,supports,policy,guard=lambda:self.guard(sid));fits.append(fit)
                elif policy and phase=='scaling' and relative_search:
                    from .reference_scale import fit_evidenced_scale
                    origin=scale_origin['plan'] if scale_origin else job['attempts'][0]['provider_response']['value']
                    plan,fit=fit_evidenced_scale(plan,relative_search,origin,policy,guard=lambda:self.guard(sid));fits.append(fit)
                if composition_plan is None and ordinal==0 and seed is None:plan,fits=fit_initial_positions(plan,effective,frames,catalogue,segments)
                if not policy and geometry and phase=='placement':
                    from .reference_pose import fit_mask_poses
                    self.status(job,'fitting','Ajustement des silhouettes sur les masques SAM de plusieurs vues…')
                    plan,pose_fits=fit_mask_poses(plan,pose_frames,segments,geometry,self.artifacts,guard=lambda:self.guard(sid),fine=bundle.get('autonomous_refinement',False));fits.extend(pose_fits)
                if policy and phase!='appearance':
                    from .reference_geometry import native_pose_precision
                    plan=native_pose_precision(plan);fits.append(dict(method='native_pose_serialization',decimal_places=12,source_transforms_used=False))
                if composition_plan is None and external_visual and '[building-prefabs-required]' in brief:
                    if ordinal==0:
                        from .reference_plan_fit import fit_overhead_plan
                        plan,region_fits=fit_overhead_plan(plan,effective,frames,catalogue,segments);fits.extend(region_fits)
                    from .reference_assembly import fit_building_perimeter
                    plan,assembly_fits=fit_building_perimeter(plan,catalogue);fits.extend(assembly_fits)
                if external_visual and composition_plan is None:
                    from .reference_geometry import orient_empty_estimated_views
                    plan,camera_fixes=orient_empty_estimated_views(plan,catalogue);fits.extend(camera_fixes)
                validate_plan(plan,effective,frames,catalogue)
                experiment_hash=experiment_identity(plan,memory['evidence_key'],job.get('policy_hash'))
                if (policy or external_visual) and phase!='baseline' and any(a.get('experiment_hash')==experiment_hash for a in job['attempts']):
                    stopping='duplicate_experiment_without_new_evidence';job['decisions'].append(dict(action='stop',reason=stopping,experiment_hash=experiment_hash));self.save(job);break
                inspection=inspection_for(frames,plan,bundle.get('inspection'));payload('InspectionPlan',inspection)
                command=dict(ordinal=ordinal,input_bundle_sha256=job['input_bundle_sha256'],catalogue_sha256=job['catalogue_sha256'],plan=plan,inspection=inspection,supports=[dict(object_key=o['key'],support_key=o['support_key']) for o in effective['objects']])
                if job.get('composition'):
                    command['composition_capture']=job['composition']['camera']
                    command['architecture']=job['composition']['architecture']
                if policy:
                    proposal_id=f'{job["id"]}-{ordinal}'
                    origin='baseline' if phase=='baseline' else 'local' if phase in {'anchoring','arranging','scaling'} else 'muse'
                    expected_version=job['attempts'][-1]['native']['version'] if job['attempts'] else bundle['candidate_base_version']
                    proposal=payload('PoseProposal',dict(schema_version='1.0',proposal_id=proposal_id,origin=origin,phase=phase,parent_version=expected_version,policy_hash=job['policy_hash'],proposed_plan_hash=fingerprint(plan),evidence_hashes=[f['artifact_hash'] for f in frames]))
                    command.update(schema_version='2.0',expected_version=expected_version,policy_hash=job['policy_hash'],proposal=proposal)
                    if appearance_reference and appearance_reference['result'].get('render_protocol'):
                        command['capture_protocol']=appearance_reference['result']['render_protocol']
                attempt=dict(ordinal=ordinal,phase=phase,provider_response=proposed,applied_plan=plan,calibrated_placement_fits=fits,state='native_pending',experiment_hash=experiment_hash)
                if appearance_experiment:attempt['appearance_experiment']=appearance_experiment
                job['attempts'].append(attempt);self.save(job)
                with self.store.tx() as c:self.store.update_session(c,sid,state='applying',attempts_used=ordinal+1)
                self.guard(sid);atomic(directory/f'plan-{ordinal}.json',command)
                self.status(job,'rendering',f'Unity construit et vérifie le candidat {ordinal+1}/{bundle["max_iterations"]}…')
                native,capture=self.wait_render(job,ordinal)
                plan=validate_native_placement(native,plan,effective,frames,catalogue,support_policies=command['supports'])
                attempt['applied_plan']=plan
                candidates=[]
                for frame,view in zip(frames,inspection['work_views']):
                    record=next(item for item in capture['statics'] if item['camera_key']==view['key']);raw=(capture['directory']/record['file']).read_bytes();data,transform=bounded_image(raw)
                    candidates.append(dict(key=frame['key'],artifact_hash=self.artifacts.put(data,'image/png'),calibration=view,**transform))
                metrics=score_pairs(self.artifacts,frames,candidates,effective,priority_view=memory['priority_view'],segments=segments)
                metrics['contacts']=native['contacts']
                if job.get('composition'):
                    from .floorplan import measure_native
                    metrics['composition']=measure_native(job['composition']['observation']['value'],native['composition_proof'])
                    structure=native.get('room_finish',{}).get('architecture',{})
                    metrics['composition']['architecture']=structure
                    metrics['composition']['structural_admissible']=bool(structure.get('walls')) and all(w.get('surface_audit',{}).get('passed') for w in structure.get('walls',[]))
                    atomic(directory/f'composition-metrics-{ordinal}.json',metrics['composition'])
                if external_visual and '[building-prefabs-required]' in brief:
                    from .reference_plan_fit import luminance_stats
                    floor_ids={a['asset_id'] for a in catalogue if a['name'].startswith('Floor_')}
                    floor=next((o for o in effective['objects'] if o['asset_id'] in floor_ids),None)
                    if floor:
                        selected=next((s['selection'] for s in segments if s['object_key']==floor['key'] and s.get('selection')),None)
                        box=selected['bbox_xyxy'] if selected else floor['view_boxes'][0]['bbox_xyxy']
                        with Image.open(io.BytesIO(self.artifacts.read(frames[0]['artifact_hash']))) as ref, Image.open(io.BytesIO(self.artifacts.read(candidates[0]['artifact_hash']))) as cand:
                            observed=luminance_stats(ImageOps.fit(cand,ref.size),box);target=luminance_stats(ref,box)
                        if observed and target:
                            metrics['plan_photometry']=dict(reference=target,candidate=observed,region=box)
                            metrics['photometric_selection_score']=metrics['score']+abs(observed['median']-target['median'])+.5*max(0,observed['bright_fraction']-target['bright_fraction'])

                if appearance_reference:
                    from .reference_appearance import measure_capture_pair
                    metrics['appearance']=measure_capture_pair(appearance_reference,capture,effective,noise=job.get('capture_noise'))
                if evaluation:
                    self.status(job,'measuring','Mesures géométriques sur les poses réellement appliquées…')
                    job.setdefault('decisions',[]).append(dict(action='verifying',reason='after_native_contacts',ordinal=ordinal,version=native['version']))
                    metrics['geometry']=evaluation.measure(plan,native['version'])
                    payload('GeometryMetrics',metrics['geometry'])
                    for key,row in metrics['per_object'].items():row['geometry']=metrics['geometry']['per_object'].get(key)
                    attempt['applied_evidence']=payload('AppliedPoseEvidence',dict(schema_version='1.0',proposal_id=proposal_id,version=native['version'],applied_plan_hash=fingerprint(plan),contacts_hash=fingerprint(native['contacts']),metrics_hash=fingerprint(metrics['geometry']),stage='after_native_contacts'))
                for key,item in metrics['per_object'].items():
                    item['mask_views']=[s['view_key'] for s in segments if s['object_key']==key and s.get('selection')]
                    item['support_contact']=next((r for r in native['contacts']['checks'] if r['object_key']==key),None)
                    item['pose_fit_before_contact']=next((r for r in fits if r.get('object_key')==key and r.get('method')=='candidate_mesh_silhouette_to_multiview_sam'),None)
                attempt.update(state='rendered',native=native,candidate_frames=candidates,metrics=metrics,performance=capture['result']['performance'])
                if policy and ordinal==0 and evaluation and not metrics['geometry']['coverage_complete']:
                    from .reference_observation import acquire_observations
                    self.status(job,'observing','Recherche bornée d’observations fiables pour les objets insuffisamment couverts…')
                    def retain_observation(updated,proof):
                        job['segments']=updated;job['observation_followup']=proof;self.save(job)
                    updated,proof=acquire_observations(provider,self.artifacts,effective,frames,details,segments,metrics['geometry'],lambda:self.guard(sid),retain_observation)
                    job['observation_followup']=proof
                    if updated!=segments:
                        segments=updated;job['segments']=segments
                        evaluation=GeometryEvaluator(pose_frames,segments,geometry,self.artifacts,width=1280,guard=lambda:self.guard(sid))
                        search=GeometryEvaluator(frames,segments,geometry,self.artifacts,width=192,guard=lambda:self.guard(sid))
                        relative_search=GeometryEvaluator(pose_frames,segments,geometry,self.artifacts,width=256,guard=lambda:self.guard(sid))
                        attempt['geometry_before_observation_revision']=metrics['geometry']
                        metrics['geometry']=evaluation.measure(plan,native['version']);payload('GeometryMetrics',metrics['geometry'])
                        for key,row in metrics['per_object'].items():
                            row['geometry']=metrics['geometry']['per_object'].get(key);row['mask_views']=[s['view_key'] for s in segments if s['object_key']==key and s.get('selection')]
                        attempt['applied_evidence']['metrics_hash']=fingerprint(metrics['geometry'])
                        evidence=fingerprint(dict(reference=evidence_key(frames,job['catalogue_sha256']),details=evidence_key(details,job['catalogue_sha256']),geometry=job.get('pose_geometry_hash'),segments=segments))
                        memory=new_memory(evidence,effective,priority_view=bundle.get('priority_view','work-top-front'),policy_hash=job['policy_hash'],solver_version=policy['solver_version']);job['memory']=memory
                    job['decisions'].append(dict(action='observing',reason='insufficient_reliable_geometry_coverage',ordinal=ordinal,new_evidence_requests=len(proof.get('attempts',[]))))
                    self.save(job)
                attempt['inspection_pairs']=self.inspect_candidate(job,attempt,effective,details,catalogue,None if job.get('composition') else provider)
                from .reference_inspection import architecture_findings
                metrics['architecture']=architecture_findings(attempt['inspection_pairs'])
                if policy:accepted,attempt['regressions']=assess(attempt,best,policy)
                elif job.get('composition'):
                    from .floorplan import composition_rank
                    accepted=best is None or composition_rank(metrics)<composition_rank(best['metrics'])
                    attempt['regressions']=[] if accepted else [dict(kind='native_composition_did_not_improve')]
                elif external_visual:
                    attempt['regressions']=regressions(attempt,best)
                    # Object crops are not geometrically aligned while an imported
                    # camera is still estimated. Keep their warnings, but do not
                    # veto a globally better view merely for a shifted crop.
                    accepted=accept_external_candidate(attempt,best)
                else:
                    attempt['regressions']=regressions(attempt,best)
                    accepted=best is None or not attempt['regressions'] and candidate_rank(attempt)<candidate_rank(best)
                attempt['retained']=accepted
                update_memory(memory,attempt,best,accepted,job['id'])
                if accepted:best=attempt
                job['retained_ordinal']=best['ordinal']
                atomic(directory/'memory.json',memory)
                with self.store.tx() as c:self.store.update_session(c,sid,state='verifying',current_version=native['version'],best_version=best['native']['version'])
                self.save(job);self.export(job)
                # Every phase runs internally. A failed experiment returns to
                # the retained baseline and becomes evidence for the next one.
                previous=best['applied_plan'];previous_frames=best['candidate_frames'];metrics=best['metrics']
            job['stop_reason']=stopping
            self.status(job,'completed',('Parcours autonome terminé ; meilleur candidat conservé, écarts résiduels consignés. Fidélité exacte non démontrée.' if best['metrics']['contacts']['passed'] else 'Essai terminé avec contacts non résolus ; candidat conservé pour diagnostic, reproduction non validée.'),best_scene_path=best['native']['scene_path'],best_ordinal=best['ordinal'],best_score=best['metrics']['score'],fidelity_verified=False,contacts_passed=best['metrics']['contacts']['passed'])
            with self.store.tx() as c:self.store.update_session(c,sid,state='completed',verdict='inconclusive',stop_reason='Reference reproduction rendered; human fidelity review and invisible geometry remain unverified')
            self.export(job)
        except Exception as error:
            code=error.code if isinstance(error,AgentError) else type(error).__name__
            message=code+': '+(error.message if isinstance(error,AgentError) else 'Reference workflow interrupted; original scene and evidence retained')
            if job:
                self.status(job,'interrupted',message)
                with self.store.tx() as c:self.store.update_session(c,job['session_id'],state='interrupted',verdict='inconclusive',stop_reason=message)
                self._event(job['session_id'],'reference_error',dict(code=code,retry_attempted=False));self.export(job)
            else:
                atomic(Path(path).parent/'status.json',dict(state='failed',message=message))
                # Keep malformed/refused input from being admitted in a polling loop.
                atomic(Path(path).parent/'native-stop.json',dict(reason=message,replay_allowed=False))
                with self.store.tx() as c:
                    admission=c.execute('SELECT * FROM app_actions WHERE run_id=?',(Path(path).parent.name,)).fetchone()
                    if admission and admission['state']=='preparing':
                        self.store.update_session(c,admission['session_id'],state='recovery_required',verdict='inconclusive',stop_reason=message)
                        c.execute("UPDATE app_actions SET state='recovery_required' WHERE id=?",(admission['id'],))
        finally:
            if provider is not None:provider.client.close()

    def export(self,job):
        directory=self.root/job['id'];sid=job['session_id']
        with closing(self.store.connect()) as c:
            events=[dict(kind=r['kind'],body=json.loads(r['body']),created_at=r['created_at']) for r in c.execute('SELECT * FROM events WHERE subject=? ORDER BY id',(sid,))]
            call_ids=[event['body']['call_id'] for event in events if event['kind']=='provider_admitted']
            calls=[dict(c.execute('SELECT id,model,status,reserved,actual,created_at FROM calls WHERE id=?',(call_id,)).fetchone()) for call_id in call_ids]
        report=dict(generated_at=utc_now(),job=job,provider_calls=calls,settled_usd_micro=sum(c['actual'] or 0 for c in calls if c['status']=='settled'),reserved_usd_micro=sum(c['reserved'] for c in calls if c['status'] in {'reserved','sent','unknown'}),events=events,fidelity_verified=False,source_scene_transforms_provided=False,limits=['Static mesh/material reconstruction with local assets; no geometry generation for absent assets.','Recorded cameras calibrated; external footage cameras are estimates.','No guaranteed reconstruction of occluded surfaces or unique 3D geometry from a single image.','Real-time lighting reconstruction; baked indirect equality is unqualified.','Sampled video frames do not establish temporal consistency.'])
        atomic(directory/'report.json',report)
        rendered=[a for a in job['attempts'] if a['state']=='rendered']
        best=next((a for a in rendered if a['ordinal']==job.get('retained_ordinal',job.get('best_ordinal'))),None) or (min(rendered,key=candidate_rank) if rendered else None)
        header='<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Reproduction de la référence</title><style>body{background:#11151d;color:#edf2fa;font:16px system-ui;max-width:1400px;margin:30px auto;padding:20px}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}img{width:100%}figure{margin:0}pre{white-space:pre-wrap}section{margin:28px 0}@media(max-width:700px){.pair{grid-template-columns:1fr}}</style><h1>Reproduction depuis la référence</h1>'
        html=header+'<p>'+escape(job.get('message','En cours'))+'</p><p>La comparaison montre des rendus Unity originaux. La fidélité reste à apprécier ; le score mesure des écarts de pixels.</p>'
        if job.get('composition'):
            html+='<p>Composition mesurée dans Unity avec une caméra orthographique fixe. Le classement utilise les contraintes géométriques ; les boîtes ne certifient pas les silhouettes ni les ouvertures.</p>'
            html+='<table><tr><th>Candidat</th><th>Erreur de placement</th><th>Contraintes des boîtes</th><th>Décision</th></tr>'
            for row in rendered:
                measured=row['metrics'].get('composition',{});loss=(measured.get('objective') or {}).get('loss')
                html+='<tr><td>'+str(row['ordinal']+1)+'</td><td>'+('non mesurée' if loss is None else f'{loss:.6g}')+'</td><td>'+('respectées' if measured.get('bounds_admissible') else 'écarts non résolus')+'</td><td>'+('retenu' if row.get('retained') else 'rejeté')+'</td></tr>'
            html+='</table><p>Portes, silhouettes, identité des assets et surfaces cachées : non qualifiées.</p>'
        if job.get('fidelity_policy'):
            html+='<p>Classement géométrique indépendant de la couleur ; mesures après contacts Unity. Motif de fin : '+escape(job.get('stop_reason','essai en cours'))+'.</p>'
            html+='<table><tr><th>Candidat</th><th>Expérience</th><th>Erreur de silhouettes</th><th>Décision</th></tr>'
            for row in rendered:
                geometry=row['metrics'].get('geometry',{});value=geometry.get('score')
                reasons=', '.join(r['kind']+(' : '+r['object_key'] if r.get('object_key') else '') for r in row.get('regressions',[]))
                html+='<tr><td>'+str(row['ordinal'])+'</td><td>'+escape(row.get('phase',''))+'</td><td>'+('non mesurée' if value is None else f'{value:.4f}')+'</td><td>'+escape('retenu à cette étape' if row.get('retained') else reasons or 'non retenu')+'</td></tr>'
            html+='</table>'
            if best and best['metrics'].get('geometry'):
                html+='<table><tr><th>Objet</th><th>IoU visible</th><th>Erreur de contour (px)</th><th>Couverture</th></tr>'
                for key,row in best['metrics']['geometry']['per_object'].items():
                    iou=row['mean_iou'];contour=row['contour_error_px']
                    html+='<tr><td>'+escape(key)+'</td><td>'+('non mesurée' if iou is None else f'{iou:.3f}')+'</td><td>'+('non mesurée' if contour is None else f'{contour:.2f}')+'</td><td>'+escape('observations disponibles' if row['covered'] else ', '.join(row['missing_reasons']))+'</td></tr>'
                html+='</table><p>Les silhouettes ne certifient ni les surfaces cachées ni une pose exacte.</p>'
        if job.get('memory'):
            html+='<p>Vue prioritaire : '+escape(job['memory']['priority_view'])+'. <a href="memory.json">Mémoire des mesures et essais</a>. Les écarts restent non résolus tant que leur absence n’est pas démontrée.</p>'
        if best:
            html+='<table><tr><th>Objet</th><th>Écart moyen de couleur — dessus</th><th>Support</th><th>Vues avec masque</th></tr>'
            for key,measured in best['metrics'].get('per_object',{}).items():
                error=measured.get('priority_rgb_mae');contact=measured.get('support_contact')
                html+='<tr><td>'+escape(key)+'</td><td>'+('non mesuré' if error is None else f'{100*error:.1f} %')+'</td><td>'+('contact contrôlé' if contact and contact['status']=='contact' else 'non certifié')+'</td><td>'+str(len(measured.get('mask_views',[])))+'</td></tr>'
            html+='</table><p>Ces mesures décrivent les écarts ; elles ne constituent pas un pourcentage de fidélité.</p>'
            right={frame['key']:frame for frame in best['candidate_frames']}
            for frame in sorted(job['frames'],key=lambda f:f['key']!=job.get('memory',{}).get('priority_view')):
                html+='<section><h2>'+escape(frame['key'])+'</h2><div class="pair">'
                for name,item in [('Référence',frame),('Reconstruction — candidat '+str(best['ordinal']+1),right[frame['key']])]:
                    encoded=base64.b64encode(self.artifacts.read(item['artifact_hash'])).decode();html+='<figure><figcaption>'+escape(name)+'</figcaption><img src="data:image/png;base64,'+encoded+'"></figure>'
                html+='</div></section>'
            html+='<details><summary>Mesures et limites</summary><pre>'+escape(json.dumps(best['metrics'],ensure_ascii=False,indent=2))+'</pre></details>'
        if job.get('detail_frames'):
            html+='<p><a href="details.html">Voir les gros plans par objet et les variantes retenues</a></p>'
            detail_html=header+'<p>Gros plans originaux associés aux objets observés. Une association par région peut rester ambiguë en cas d’occlusion.</p>'
            preview_file=directory/'preview-result.json';previews=json.loads(preview_file.read_text()) if preview_file.exists() else []
            catalogue_file=directory/job['bundle']['catalogue_file'];asset_names={a['asset_id']:a['name'] for a in json.loads(catalogue_file.read_text())}
            effective=job.get('effective_analysis',job.get('analysis_response',{}).get('value',{}))
            for item in effective.get('objects',[]):
                linked=[frame for frame in job['detail_frames'] if frame['object_key']==item['key']]
                if not linked:continue
                detail_html+='<section><h2>'+escape(item['key'])+'</h2><div class="pair">'
                for frame in linked:
                    encoded=base64.b64encode(self.artifacts.read(frame['artifact_hash'])).decode();detail_html+='<figure><figcaption>'+escape(frame.get('angle',frame['acquisition']))+'</figcaption><img src="data:image/png;base64,'+encoded+'"></figure>'
                preview=next((p for p in previews if p['asset_id']==item['asset_id'] and p.get('file')),None)
                if preview:
                    path=contained(directory,directory/preview['file']);encoded=base64.b64encode(path.read_bytes()).decode();detail_html+='<figure><figcaption>Variante retenue : '+escape(asset_names.get(item['asset_id'],item['asset_id']))+'</figcaption><img src="data:image/png;base64,'+encoded+'"></figure>'
                detail_html+='</div></section>'
            temp=directory/'details.html.writing';temp.write_text(detail_html+'</html>');temp.replace(directory/'details.html')
        html+='<p>Appels réglés : '+str(report['settled_usd_micro']/1e6)+' $ ; engagements conservés : '+str(report['reserved_usd_micro']/1e6)+' $.</p></html>'
        temp=directory/'comparison.html.writing';temp.write_text(html);temp.replace(directory/'comparison.html')
