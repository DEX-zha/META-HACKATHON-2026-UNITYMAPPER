"""Scoped visual interaction experiment; immutable steps and budget-accounted model calls."""
import argparse
import hashlib
import html
import json
import time
import uuid
from pathlib import Path
from .artifacts import ArtifactStore
from .budget import Budget
from .budget_cli import load_pricing
from .config import Settings
from .domain import AgentError,canonical,fingerprint,payload
from .providers.meta_responses import MetaResponses,spark_request
from .store import Store


def choose_pair(instances):
    """Prefer a real task chair/desk pair; never invent a chair from an asset name."""
    for seating,table in [('chair','desk'),('sofa','table'),('seat','table')]:
        for a in instances:
            if seating not in a['id'].lower():continue
            for b in instances:
                if table in b['id'].lower() and a['group_id']==b['group_id'] and a['id']!=b['id']:return [a['id'],b['id']]
    return None


def prepare(settings,store,artifacts):
    with store.connect() as c:
        if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached')").fetchone():raise AgentError('SESSION_ACTIVE','Stop the running generation first')
        commands=c.execute("SELECT * FROM commands WHERE kind='build_house' AND status='succeeded' ORDER BY rowid DESC").fetchall()
        chosen=None
        for command in commands:
            body=json.loads(command['body']);receipt=json.loads(command['result']);manifest=json.loads(artifacts.read(body['payload']['manifest_hash']));pair=choose_pair(manifest['instances'])
            if pair and receipt.get('details_artifact_hash'):
                proof=json.loads(artifacts.read(receipt['details_artifact_hash']));chosen=command,manifest,proof,pair;break
        if chosen is None:raise AgentError('NOT_FOUND','No generated scene with a seating/table pair is available')
        command,manifest,proof,pair=chosen;project=json.loads(c.execute('SELECT body FROM projects WHERE id=?',(command['project_id'],)).fetchone()[0])
    source=settings.project_path(project['project_root'])/proof['scene_path']
    if not source.is_file():raise AgentError('NOT_FOUND','Generated source scene is missing')
    ident=uuid.uuid4().hex;directory=settings.state/'direct-room'/ident;directory.mkdir(parents=True)
    data=dict(id=ident,source_scene=proof['scene_path'],source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),selection_ids=pair,instances=manifest['instances'],building=manifest['building'],source_run=manifest['run_id'],project_id=command['project_id'])
    session=payload('Session',dict(id='direct-'+ident,state='preflight',verdict='pending',best_version=data['source_sha256'],current_version=data['source_sha256'],attempts_used=0,max_attempts=6,criteria_hash=fingerprint(pair),inspection_hash=fingerprint({}),stop_reason=None,provider_mode='live'))
    with store.tx() as c:
        if c.execute("SELECT 1 FROM sessions WHERE state NOT IN ('completed','interrupted','limit_reached')").fetchone():raise AgentError('SESSION_ACTIVE','Editor ownership changed')
        scene='direct-scene-'+ident;c.execute('INSERT INTO scenes VALUES(?,?,?)',(scene,command['project_id'],canonical(dict(kind='direct_experiment'))))
        c.execute('INSERT INTO sessions(id,project_id,scene_id,state,body) VALUES(?,?,?,?,?)',(session['id'],command['project_id'],scene,session['state'],canonical(session)))
    (directory/'bootstrap.json').write_text(canonical(data));(directory.parent/'bootstrap.json').write_text(canonical(data))
    return data


def validate_action(action,selection):
    payload('ModelRoomInteractionAction',action)
    if action['action']=='move' and action['target_id'] not in selection:raise AgentError('OUT_OF_SCOPE','Model selected furniture outside this experiment')
    return action


def native_step(directory,ordinal,version,action):
    path=directory/f'command-{ordinal:04d}.json'
    data=dict(action,expected_version=version)
    # The same ordinal is never sent twice; uncertain outcomes require inspection.
    if path.exists():raise AgentError('RECOVERY_REQUIRED','Interaction command already exists; no replay')
    tmp=path.with_suffix('.writing');tmp.write_text(canonical(data));tmp.replace(path)
    result=Path(str(path)+'.result.json');deadline=time.monotonic()+180
    while not result.exists():
        if time.monotonic()>deadline:raise AgentError('RECOVERY_REQUIRED','Native interaction receipt missing; no replay')
        time.sleep(.2)
    return json.loads(result.read_text())


def report(directory,log):
    rows=['<!doctype html><html lang="en"><meta charset="utf-8"><title>Direct room experiment</title><style>body{font:16px system-ui;max-width:1100px;margin:auto;padding:24px}img{max-width:100%}pre{white-space:pre-wrap}</style><h1>Direct room interaction</h1><p>Model proposals and native receipts. Artistic improvement requires visual review.</p>']
    for step in log:
        rows.append('<h2>'+html.escape(step['label'])+'</h2><pre>'+html.escape(json.dumps(step.get('action',{}),indent=2,ensure_ascii=False))+'</pre>')
        result=step['result']
        if result.get('error'):rows.append('<p>'+html.escape(result['error'])+'</p>')
        if result.get('file'):rows.append('<img src="'+html.escape(result['file'],quote=True)+'">')
    (directory/'report.html').write_text(''.join(rows))


def run(settings,store,artifacts,ident):
    if len(ident)!=32 or any(c not in '0123456789abcdef' for c in ident):raise ValueError('Invalid experiment ID')
    directory=settings.state/'direct-room'/ident;config=json.loads((directory/'bootstrap.json').read_text());ready=directory/'ready.json'
    if not ready.exists():raise AgentError('EDITOR_UNAVAILABLE','Start the direct interaction experiment in Unity first')
    state=json.loads(ready.read_text());version=state['version'];ordinal=0;log=[];images=[];seen=set();terminal=False
    provider=MetaResponses(settings,Budget(store,load_pricing(settings.state/'pricing.json')),artifacts)
    try:
        inventory={o['id']:o for o in state['objects']};pair=[inventory[k] for k in config['selection_ids']]
        centre=[sum(o['bounds_center'][i] for o in pair)/2 for i in range(3)];room_id=next(i['room_id'] for i in config['instances'] if i['id']==config['selection_ids'][0]);room=next(r for r in config['building']['rooms'] if r['id']==room_id)
        xs=[p[0] for p in room['polygon']];zs=[p[1] for p in room['polygon']]
        for direction in [-1,1]:
            position=[min(max(centre[0]+direction*2,min(xs)+.4),max(xs)-.4),1.7,min(max(centre[2]+direction*2,min(zs)+.4),max(zs)-.4)]
            action=dict(action='observe',position=position,look_at=centre,fov=65)
            result=native_step(directory,ordinal,version,action);ordinal+=1;log.append(dict(label='Initial observation',action=action,result=result));images.append(result['file']);report(directory,log)
        while True:
            with store.connect() as c:
                if c.execute('SELECT stop_requested FROM sessions WHERE id=?',('direct-'+ident,)).fetchone()[0]:raise AgentError('STOP_REQUESTED','Experiment stopped by user')
            previews=[p['file'] for p in state['previews']];files=previews+images[-2:]
            # Preserve full history on disk; model sees recent receipts and current exact state.
            context=dict(selection=config['selection_ids'],state=state,room=room,images=files,recent=[dict(action=s.get('action'),error=s['result'].get('error'),version=s['result'].get('version')) for s in log[-8:]])
            prompt='You are testing direct visual furniture editing in a persistent Unity scene. Improve ONLY the functional relationship and orientation of the selected seating/table pair. First understand the actual prefabs from their two-angle previews; do not call a sofa a desk chair or a coffee table a desk. No new furniture, no scaling, no automatic rearrangement. The reference field contains measured real furniture poses from House_clean_day, not target coordinates to copy. You may observe from a camera position/look_at, move ONE selected object to an exact world pivot position and absolute yaw (its supported props follow), undo the last move, or finish. Keep y unchanged, room boundaries, door access, collisions and realistic sitting/use distance. Inspect another viewpoint when uncertain. After moving, observe the result before finishing. Native rejection is a failed action, not a correction. Summarize the public reason for the next action; never claim success without observed evidence. Finish honestly if the existing assets cannot fulfill the requested relationship. Return unused coordinates as [0,0,0], unused target as null, unused yaw as 0 and unused fov as 65. Context: '+canonical(context)
            response=provider.send(spark_request(prompt,[(directory/f).read_bytes() for f in files],'ModelRoomInteractionAction'),'ModelRoomInteractionAction')
            action=validate_action(response['value'],config['selection_ids']);(directory/f'model-{ordinal:04d}.json').write_text(canonical(response))
            key=fingerprint(dict(version=version,action={k:v for k,v in action.items() if k!='summary'}))
            if key in seen:raise AgentError('REPEATED_STATE','Same action on unchanged scene; stopping instead of looping')
            seen.add(key)
            if action['action']=='finish':
                # Match the initial camera poses before closing the persistent scene.
                for initial in log[:2]:
                    comparison=native_step(directory,ordinal,version,initial['action']);ordinal+=1
                    log.append(dict(label='Final matched observation',action=initial['action'],result=comparison))
            result=native_step(directory,ordinal,version,action);ordinal+=1;log.append(dict(label='Model action',action=action,result=result))
            print(action['action'],action['summary'], 'REJECTED: '+result['error'] if result.get('error') else 'acknowledged',flush=True)
            if not result.get('error'):state=result;version=result['version']
            if result.get('file'):images.append(result['file'])
            (directory/'history.json').write_text(canonical(log));report(directory,log)
            if action['action']=='finish' and not result.get('error'):terminal=True;break
    finally:
        provider.client.close()
        if not terminal and not (directory/f'command-{ordinal:04d}.json').exists():
            result=native_step(directory,ordinal,version,dict(action='finish'));terminal=not result.get('error')
        with store.tx() as c:store.update_session(c,'direct-'+ident,state='completed' if terminal else 'recovery_required',verdict='inconclusive',stop_reason='Experiment ended; inspect report' if terminal else 'Native receipt requires reconciliation')
        report(directory,log)
    return str(directory/'report.html')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--prepare',action='store_true');parser.add_argument('--run');args=parser.parse_args()
    settings=Settings.load(Path.cwd(),provider_mode='live',env_file=Path('.env'));store=Store(settings.db_path);artifacts=ArtifactStore(settings.state/'artifacts',store)
    if args.prepare:print(json.dumps(prepare(settings,store,artifacts),indent=2))
    elif args.run:print(run(settings,store,artifacts,args.run))

if __name__=='__main__':main()
