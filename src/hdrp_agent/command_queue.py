"""At-most-one claim. Uncertain delivery requires reconciliation, never replay."""
from contextlib import closing
from datetime import datetime, timezone, timedelta
import json

from .domain import AgentError, canonical, fingerprint, payload
from .store import utc_now

ACTIVE = ('claimed', 'running', 'unknown')
TERMINAL = ('succeeded', 'failed', 'cancelled')


def instant(value):
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


class CommandQueue:
    def __init__(self, store):
        self.store = store
        with store.tx() as c:
            c.execute('CREATE TABLE IF NOT EXISTS project_presence(project_id TEXT PRIMARY KEY REFERENCES projects(id),epoch TEXT NOT NULL,last_seen TEXT NOT NULL)')

    def touch(self,c,project_id,epoch):
        c.execute('INSERT OR REPLACE INTO project_presence VALUES(?,?,?)',(project_id,epoch,utc_now()))

    def _epoch(self, c, project_id, epoch):
        row = c.execute('SELECT * FROM projects WHERE id=?', (project_id,)).fetchone()
        if not row: raise AgentError('NOT_FOUND', 'Project is not registered', 404)
        if row['epoch'] != epoch: raise AgentError('STALE_EPOCH', 'Editor epoch has changed')
        return json.loads(row['body'])

    def enqueue(self, project_id, command, conn=None):
        command = payload('Command', command)
        if fingerprint(command['payload']) != command['payload_hash']: raise AgentError('HASH_MISMATCH', 'Command payload hash failed', 422)
        with self.store.tx(conn) as c:
            self._epoch(c, project_id, command['bridge_epoch'])
            existing = c.execute('SELECT body FROM commands WHERE id=?', (command['id'],)).fetchone()
            if existing:
                if json.loads(existing[0]) != command: raise AgentError('COMMAND_CONFLICT', 'Command ID already has a different payload')
                return command
            session = c.execute('SELECT * FROM sessions WHERE id=?', (command['session_id'],)).fetchone()
            if not session or session['project_id'] != project_id: raise AgentError('NOT_FOUND', 'Session does not belong to project', 404)
            if session['state']=='recovery_required' and command['kind']!='inspect': raise AgentError('RECOVERY_REQUIRED', 'Only inspection is allowed until explicit reconciliation')
            if session['stop_requested'] and not (session['state']=='restoring' and command['kind'] in {'restore','capture'}): raise AgentError('STOP_REQUESTED', 'Session is stopping')
            c.execute('INSERT INTO commands(id,session_id,project_id,epoch,kind,status,body,payload_hash) VALUES(?,?,?,?,?,?,?,?)',
                (command['id'], command['session_id'], project_id, command['bridge_epoch'], command['kind'], 'queued', canonical(command), command['payload_hash']))
            self.store.event(c, command['id'], 'queued', command)
            return command

    def poll(self, request):
        request = payload('Poll', request)
        with self.store.tx() as c:
            self._epoch(c, request['project_id'], request['bridge_epoch'])
            self.touch(c,request['project_id'],request['bridge_epoch'])
            session_active=c.execute("SELECT 1 FROM sessions WHERE project_id=? AND state NOT IN ('completed','interrupted','limit_reached') LIMIT 1",(request['project_id'],)).fetchone() is not None
            # Unknown mutation prevents another mutation, but inspection can reconcile state.
            busy = c.execute("SELECT 1 FROM commands WHERE project_id=? AND status IN ('claimed','running')", (request['project_id'],)).fetchone()
            if busy: return dict(commands=[],session_active=session_active)
            rows = c.execute("SELECT commands.*,sessions.state,sessions.stop_requested FROM commands JOIN sessions ON sessions.id=commands.session_id WHERE commands.project_id=? AND commands.epoch=? AND commands.status='queued' ORDER BY commands.rowid", (request['project_id'],request['bridge_epoch'])).fetchall()
            for row in rows:
                command = json.loads(row['body'])
                if (row['stop_requested'] and not (row['state']=='restoring' and row['kind'] in {'restore','capture'})) or row['cancel_requested'] or instant(command['deadline_utc']) <= datetime.now(timezone.utc):
                    c.execute("UPDATE commands SET status='cancelled' WHERE id=?", (row['id'],)); continue
                if row['state']=='recovery_required' and row['kind']!='inspect': continue
                c.execute("UPDATE commands SET status='claimed',heartbeat=? WHERE id=?", (utc_now(), row['id']))
                self.store.event(c, row['id'], 'claimed', {})
                return dict(commands=[command],session_active=session_active)
            return dict(commands=[],session_active=session_active)

    def progress(self, command_id, request):
        request = payload('Progress', request)
        with self.store.tx() as c:
            row = self._command(c, command_id, request['bridge_epoch'])
            self.touch(c,row['project_id'],request['bridge_epoch'])
            if row['status'] not in ACTIVE: raise AgentError('COMMAND_STATE', 'Command is not active')
            body = json.loads(row['body'])
            session = c.execute('SELECT stop_requested,state FROM sessions WHERE id=?', (row['session_id'],)).fetchone()
            cancel = row['cancel_requested'] or (session['stop_requested'] and not (session['state']=='restoring' and row['kind'] in {'restore','capture'})) or row['status']=='unknown' or instant(body['deadline_utc']) <= datetime.now(timezone.utc)
            # A late heartbeat does not establish that a lost command is safe to replay.
            status = row['status'] if row['status']=='unknown' else ('running' if request['phase']!='claimed' else row['status'])
            c.execute('UPDATE commands SET status=?,heartbeat=? WHERE id=?', (status, utc_now(), command_id))
            self.store.event(c, command_id, 'progress', request)
            return dict(command_id=command_id, directive='cancel' if cancel else 'continue', deadline_utc=body['deadline_utc'])

    def _command(self, c, command_id, epoch):
        row = c.execute('SELECT * FROM commands WHERE id=?', (command_id,)).fetchone()
        if not row: raise AgentError('NOT_FOUND', 'Command does not exist', 404)
        self._epoch(c, row['project_id'], epoch)
        if row['epoch'] != epoch: raise AgentError('STALE_EPOCH', 'Receipt requires explicit reconciliation')
        return row

    def result(self, command_id, request):
        request = payload('CommandResult', request)
        if command_id != request['command_id']: raise AgentError('COMMAND_CONFLICT', 'Receipt ID mismatch')
        with self.store.tx() as c:
            row = self._command(c, command_id, request['bridge_epoch'])
            if request['payload_hash'] != row['payload_hash']: raise AgentError('HASH_MISMATCH', 'Receipt payload hash mismatch')
            if row['result']:
                if json.loads(row['result']) != request: raise AgentError('RECEIPT_CONFLICT', 'Terminal receipt differs')
                return {'accepted': True, 'id': command_id}
            if row['status'] not in ACTIVE: raise AgentError('COMMAND_STATE', 'Command was never claimed')
            command = json.loads(row['body'])
            if row['kind']!='inspect' and request['status']=='succeeded' and request['before_version'] != command['expected_version']: raise AgentError('STALE_VERSION', 'Receipt starts from unexpected version')
            c.execute('UPDATE commands SET result=?,status=? WHERE id=?', (canonical(request), request['status'],command_id))
            self.store.event(c, command_id, 'result', request)
            if request['status']=='unknown':
                self.store.update_session(c, row['session_id'], state='recovery_required', stop_reason='Editor outcome is unknown')
            return {'accepted': True, 'id': command_id}

    def expire(self, seconds=30, *, restart=False):
        threshold = (datetime.now(timezone.utc)-timedelta(seconds=seconds)).isoformat()
        with self.store.tx() as c:
            rows = c.execute("SELECT * FROM commands WHERE status IN ('claimed','running') AND (? OR heartbeat < ?)", (restart,threshold)).fetchall()
            for row in rows:
                c.execute("UPDATE commands SET status='unknown',cancel_requested=1 WHERE id=?", (row['id'],))
                self.store.update_session(c, row['session_id'], state='recovery_required', stop_reason='Command receipt is missing; automatic replay disabled')
                self.store.event(c, row['id'], 'unknown', {})
            # Any transmitted provider call lost across a service restart retains its reservation.
            if restart: c.execute("UPDATE calls SET status='unknown' WHERE status='sent'")
            return len(rows)

    def change_epoch(self, c, project_id, epoch):
        rows = c.execute("SELECT * FROM commands WHERE project_id=? AND epoch!=? AND status IN ('queued','claimed','running')", (project_id,epoch)).fetchall()
        for row in rows:
            status = 'cancelled' if row['status']=='queued' else 'unknown'
            c.execute('UPDATE commands SET status=?,cancel_requested=1 WHERE id=?', (status,row['id']))
            self.store.update_session(c,row['session_id'],state='recovery_required',stop_reason='Editor epoch changed; receipts must be reconciled')
