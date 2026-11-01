"""Durable hierarchical house inventory/jobs. No provider calls or scene mutation."""
from contextlib import closing
import json
import sqlite3
from .domain import AgentError, canonical, fingerprint
from .house_domain import HouseProgram, BuildingIR, Requirement
from .store import utc_now

SCHEMA = [
'''CREATE TABLE IF NOT EXISTS house_programs(run_id TEXT PRIMARY KEY,project_id TEXT NOT NULL,body TEXT NOT NULL,building TEXT,execution_state TEXT NOT NULL,quality_state TEXT NOT NULL,created_at TEXT NOT NULL)''',
'''CREATE TABLE IF NOT EXISTS house_requirements(run_id TEXT NOT NULL REFERENCES house_programs(run_id),id TEXT NOT NULL,scope_id TEXT NOT NULL,status TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(run_id,id))''',
'''CREATE TABLE IF NOT EXISTS house_jobs(run_id TEXT NOT NULL REFERENCES house_programs(run_id),id TEXT NOT NULL,scope_id TEXT NOT NULL,kind TEXT NOT NULL,state TEXT NOT NULL,input_hash TEXT NOT NULL,dependencies TEXT NOT NULL,body TEXT NOT NULL,output TEXT,PRIMARY KEY(run_id,id))''',
'''CREATE TABLE IF NOT EXISTS house_defects(run_id TEXT NOT NULL REFERENCES house_programs(run_id),id TEXT NOT NULL,scope_id TEXT NOT NULL,status TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(run_id,id))''',
'''CREATE TABLE IF NOT EXISTS house_patches(run_id TEXT NOT NULL REFERENCES house_programs(run_id),id TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(run_id,id))''',
'''CREATE TABLE IF NOT EXISTS house_gates(run_id TEXT NOT NULL REFERENCES house_programs(run_id),id TEXT NOT NULL,scope_id TEXT NOT NULL,result TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(run_id,id))''',
'''CREATE TABLE IF NOT EXISTS asset_semantics(prefab_guid TEXT NOT NULL,dependency_hash TEXT NOT NULL,body TEXT NOT NULL,PRIMARY KEY(prefab_guid,dependency_hash))''',
]


class HouseStore:
    def __init__(self, store):
        self.store=store
        with closing(store.connect()) as c:
            installed=c.execute("SELECT value FROM meta WHERE key='house_schema_version'").fetchone()
            if installed:
                if installed[0]!='1':raise AgentError('SCHEMA_VERSION','Unsupported house storage schema')
                return
            backup=store.path.with_name(store.path.name+'.house-v1-backup')
            if backup.is_symlink():raise AgentError('OUT_OF_SCOPE','House migration backup cannot be a symlink')
            if not backup.exists():
                with closing(sqlite3.connect(backup)) as target:c.backup(target)
                backup.chmod(0o600)
        with store.tx() as c:
            for statement in SCHEMA:c.execute(statement)
            c.execute("INSERT OR IGNORE INTO meta VALUES('house_schema_version','1')")

    def create(self, value, building=None):
        p=HouseProgram.model_validate(value);body=p.model_dump(mode='json')
        b=BuildingIR.model_validate(building).model_dump(mode='json') if building is not None else None
        with self.store.tx() as c:
            prior=c.execute('SELECT body,building FROM house_programs WHERE run_id=?',(p.run_id,)).fetchone()
            if prior:
                if prior['body']!=canonical(body) or prior['building']!=(canonical(b) if b else None):raise AgentError('IDEMPOTENCY_CONFLICT','House run already has a different program')
                return body
            c.execute('INSERT INTO house_programs VALUES(?,?,?,?,?,?,?)',(p.run_id,p.project_id,canonical(body),canonical(b) if b else None,'queued','pending',utc_now()))
            for r in p.requirements:c.execute('INSERT INTO house_requirements VALUES(?,?,?,?,?)',(p.run_id,r.id,r.scope_id,r.status,canonical(r.model_dump(mode='json'))))
            self.store.event(c,p.run_id,'house.program_created',dict(requirements=len(p.requirements),rooms=len(p.rooms)))
        return body

    def _program(self,c,run):
        row=c.execute('SELECT * FROM house_programs WHERE run_id=?',(run,)).fetchone()
        if not row:raise AgentError('NOT_FOUND','House run not found',404)
        return row

    def add_jobs(self,run,jobs):
        with self.store.tx() as c:
            p=HouseProgram.model_validate_json(self._program(c,run)['body'])
            scopes={p.id}|{r.id for r in p.rooms}|{r.floor_id for r in p.rooms}|{g for r in p.rooms for g in r.group_ids}
            rows=c.execute('SELECT id,dependencies,body FROM house_jobs WHERE run_id=?',(run,)).fetchall()
            graph={r['id']:json.loads(r['dependencies']) for r in rows};prior={r['id']:r['body'] for r in rows}
            seen=set()
            for j in jobs:
                if set(j)!={'id','scope_id','kind','dependencies','input_hash'} or not all(isinstance(j[k],str) and j[k] for k in ('id','scope_id','kind','input_hash')) or not isinstance(j['dependencies'],list) or any(not isinstance(d,str) for d in j['dependencies']):raise AgentError('INVALID_INPUT','Invalid house job')
                if j['scope_id'] not in scopes or j['id'] in seen:raise AgentError('INVALID_INPUT','Unknown job scope or duplicate job')
                seen.add(j['id'])
                if j['id'] in prior and prior[j['id']]!=canonical(j):raise AgentError('IDEMPOTENCY_CONFLICT','Job identity reused')
                graph[j['id']]=j['dependencies']
            visited=set();active=set()
            def visit(key):
                if key not in graph:raise AgentError('INVALID_INPUT','Unknown job dependency')
                if key in active:raise AgentError('INVALID_INPUT','Cyclic job graph')
                if key in visited:return
                active.add(key)
                for dep in graph[key]:visit(dep)
                active.remove(key);visited.add(key)
            for key in graph:visit(key)
            for j in jobs:c.execute('INSERT OR IGNORE INTO house_jobs VALUES(?,?,?,?,?,?,?,?,NULL)',(run,j['id'],j['scope_id'],j['kind'],'queued',j['input_hash'],canonical(j['dependencies']),canonical(j)))

    def claim(self,run):
        with self.store.tx() as c:
            p=self._program(c,run)
            if p['execution_state'] not in {'queued','running'}:return None
            rows=c.execute('SELECT * FROM house_jobs WHERE run_id=? ORDER BY rowid',(run,)).fetchall()
            if any(r['state']=='running' for r in rows):return None
            complete={r['id'] for r in rows if r['state']=='succeeded'}
            for r in rows:
                if r['state']=='queued' and set(json.loads(r['dependencies']))<=complete:
                    c.execute("UPDATE house_jobs SET state='running' WHERE run_id=? AND id=?",(run,r['id']))
                    c.execute("UPDATE house_programs SET execution_state='running' WHERE run_id=?",(run,))
                    self.store.event(c,run,'house.job_claimed',dict(job_id=r['id'],scope_id=r['scope_id']))
                    return json.loads(r['body'])
        return None

    def complete(self,run,job_id,input_hash,output):
        with self.store.tx() as c:
            row=c.execute('SELECT * FROM house_jobs WHERE run_id=? AND id=?',(run,job_id)).fetchone()
            if not row or row['input_hash']!=input_hash:raise AgentError('STALE_EVIDENCE','Job completion input differs')
            if row['state']=='succeeded' and row['output']==canonical(output):return
            if row['state']!='running':raise AgentError('INVALID_STATE','Only a running job can complete')
            c.execute("UPDATE house_jobs SET state='succeeded',output=? WHERE run_id=? AND id=?",(canonical(output),run,job_id))
            self.store.event(c,run,'house.job_completed',dict(job_id=job_id,output_hash=fingerprint(output)))

    def reconcile_batch(self,run,expected_ids,resolved,unresolved):
        if len(expected_ids)!=len(set(expected_ids)) or len(unresolved)!=len(set(unresolved)):raise AgentError('INVALID_MODEL_OUTPUT','Duplicate batch IDs')
        parsed=[Requirement.model_validate(r) for r in resolved];done={r.id for r in parsed}
        if len(done)!=len(parsed) or done&set(unresolved) or done|set(unresolved)!=set(expected_ids):raise AgentError('INVALID_MODEL_OUTPUT','Batch omitted or duplicated requirements')
        with self.store.tx() as c:
            self._program(c,run)
            current={r['id']:json.loads(r['body']) for r in c.execute('SELECT * FROM house_requirements WHERE run_id=?',(run,))}
            if not set(expected_ids)<=set(current):raise AgentError('INVALID_MODEL_OUTPUT','Batch references unknown requirements')
            for r in parsed:
                data=r.model_dump(mode='json');old=current[r.id]
                if any(data[k]!=old[k] for k in ('id','scope_id','role','quantity','priority','provenance')):raise AgentError('INVALID_MODEL_OUTPUT','Batch changed requirement identity')
                if r.status=='satisfied':
                    # Provider text alone never proves native satisfaction.
                    if not all(c.execute('SELECT 1 FROM artifacts WHERE hash=?',(h,)).fetchone() for h in r.evidence_ids):raise AgentError('STALE_EVIDENCE','Unregistered satisfaction evidence')
                c.execute('UPDATE house_requirements SET status=?,body=? WHERE run_id=? AND id=?',(r.status,canonical(data),run,r.id))
            self.store.event(c,run,'house.batch_reconciled',dict(expected=expected_ids,resolved=list(done),unresolved=unresolved))

    def defect(self,run,value):
        required={'id','scope_id','severity','gate','message','evidence_ids'}
        if set(value)!=required or value['severity'] not in {'blocking','warning'}:raise AgentError('INVALID_INPUT','Invalid defect')
        with self.store.tx() as c:
            p=HouseProgram.model_validate_json(self._program(c,run)['body'])
            scopes={p.id}|{r.id for r in p.rooms}|{r.floor_id for r in p.rooms}|{g for r in p.rooms for g in r.group_ids}
            if value['scope_id'] not in scopes:raise AgentError('INVALID_INPUT','Unknown defect scope')
            previous=c.execute('SELECT body FROM house_defects WHERE run_id=? AND id=?',(run,value['id'])).fetchone()
            if previous and any(json.loads(previous[0])[k]!=value[k] for k in ('scope_id','gate')):raise AgentError('IDEMPOTENCY_CONFLICT','Defect identity changed')
            c.execute("INSERT INTO house_defects VALUES(?,?,?,'open',?) ON CONFLICT(run_id,id) DO UPDATE SET body=excluded.body,status='open'",(run,value['id'],value['scope_id'],canonical(value)))
            if value['severity']=='blocking':c.execute("UPDATE house_programs SET quality_state='incomplete' WHERE run_id=?",(run,))
            self.store.event(c,run,'house.defect_observed',value)

    def record_rejected_attempt(self,run,value):
        required={'id','scope_id','defect_ids','input_hash','proposal','reason','evidence_ids'}
        if set(value)!=required or not all(isinstance(value[k],str) and value[k] for k in ('id','scope_id','input_hash','reason')) or not isinstance(value['proposal'],dict) or not isinstance(value['defect_ids'],list) or not value['defect_ids'] or not isinstance(value['evidence_ids'],list):
            raise AgentError('INVALID_INPUT','Rejected attempt needs a proposal, defect IDs and reason')
        with self.store.tx() as c:
            self._program(c,run)
            defects={r['id']:r['scope_id'] for r in c.execute('SELECT id,scope_id FROM house_defects WHERE run_id=?',(run,))}
            if any(defects.get(d)!=value['scope_id'] for d in value['defect_ids']):raise AgentError('INVALID_INPUT','Attempt references unknown or out-of-scope defect')
            body=canonical(dict(value,status='rejected'))
            old=c.execute('SELECT body FROM house_patches WHERE run_id=? AND id=?',(run,value['id'])).fetchone()
            if old:
                if old[0]!=body:raise AgentError('IDEMPOTENCY_CONFLICT','Attempt identity reused')
                return
            c.execute('INSERT INTO house_patches VALUES(?,?,?)',(run,value['id'],body))
            self.store.event(c,run,'house.attempt_rejected',value)

    def context(self,run,scope):
        snapshot=self.snapshot(run)
        program=snapshot['program']
        rooms=program['rooms'];house=program['id']
        all_scopes={house}|{r['id'] for r in rooms}|{r['floor_id'] for r in rooms}|{g for r in rooms for g in r['group_ids']}
        if scope not in all_scopes:raise AgentError('INVALID_INPUT','Unknown context scope')
        room=next((r for r in rooms if r['id']==scope or scope in r['group_ids']),None)
        if scope==house:scopes=all_scopes
        elif room:scopes={house,room['floor_id'],room['id'],*room['group_ids']}
        else:
            local=[r for r in rooms if r['floor_id']==scope]
            scopes={house,scope}|{r['id'] for r in local}|{g for r in local for g in r['group_ids']}
        defects=[d for d in snapshot['defects'] if d['status']!='resolved' and (d['scope_id'] in scopes or d['severity']=='blocking')]
        defect_ids={d['id'] for d in defects}
        return dict(brief=program['brief'],creative_policy=program['creative_policy'],room=room,
            pending_requirements=[r for r in snapshot['requirements'] if r['scope_id'] in scopes and r['status']!='satisfied'],
            defects=defects,
            rejected_attempts=[p for p in snapshot['patches'] if p.get('status')=='rejected' and defect_ids.intersection(p['defect_ids'])],
            jobs=[j for j in snapshot['jobs'] if j['scope_id'] in scopes])

    def pause(self,run,reason):
        if not reason:raise AgentError('INVALID_INPUT','Pause requires a reason')
        with self.store.tx() as c:
            self._program(c,run)
            c.execute("UPDATE house_programs SET execution_state='paused' WHERE run_id=?",(run,))
            self.store.event(c,run,'house.paused',dict(reason=reason))

    def finish(self,run):
        with self.store.tx() as c:
            self._program(c,run)
            if c.execute("SELECT 1 FROM house_jobs WHERE run_id=? AND state IN ('queued','running','waiting')",(run,)).fetchone():raise AgentError('INVALID_STATE','Pending work cannot finish silently')
            requirements=[Requirement.model_validate_json(r[0]) for r in c.execute('SELECT body FROM house_requirements WHERE run_id=?',(run,))]
            missing=any(r.priority=='mandatory' and r.status!='satisfied' for r in requirements)
            blocking=any(json.loads(r[0])['severity']=='blocking' for r in c.execute("SELECT body FROM house_defects WHERE run_id=? AND status!='resolved'",(run,)))
            # Qualification will require explicit gate/review receipts; never inferred from completion.
            quality='incomplete' if missing or blocking else 'needs_review'
            c.execute("UPDATE house_programs SET execution_state='finished',quality_state=? WHERE run_id=?",(quality,run))
            self.store.event(c,run,'house.finished',dict(quality_state=quality))
        return quality

    def snapshot(self,run):
        with self.store.tx() as c:
            row=self._program(c,run);out={k:row[k] for k in ('run_id','project_id','execution_state','quality_state')}
            out['program']=json.loads(row['body']);out['building']=json.loads(row['building']) if row['building'] else None
            for name,table in [('requirements','house_requirements'),('jobs','house_jobs'),('defects','house_defects'),('gates','house_gates'),('patches','house_patches')]:
                out[name]=[]
                for r in c.execute('SELECT * FROM '+table+' WHERE run_id=? ORDER BY rowid',(run,)):
                    item=json.loads(r['body'])
                    for field in ('state','status','result'):
                        if field in r.keys():item[field]=r[field]
                    out[name].append(item)
            return out
