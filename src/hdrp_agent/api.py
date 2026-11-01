"""Authenticated loopback service. Unity requests work; the server never runs C#."""
import asyncio
from contextlib import asynccontextmanager, suppress, closing
import fcntl
import json
import secrets

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from pydantic import ValidationError
from starlette.exceptions import HTTPException

from .artifacts import ArtifactStore
from .budget import Budget
from .budget_cli import load_pricing
from .command_queue import CommandQueue
from .config import Settings, contained
from .domain import AgentError, CONTRACTS, canonical, payload
from .logging import configure
from .store import Store
from .orchestrator import Orchestrator
from . import reporting
from .reference_worker import ReferenceWorker
from .reference_commands import ReferenceCommands
from .chat_turns import ChatTurns
from .house_service import HouseService
from .chat_api import attach as attach_chat


def create_app(settings=None):
    settings = settings or Settings.load(CONTRACTS.parents[2])
    store = Store(settings.db_path)
    artifacts = ArtifactStore(contained(settings.state, settings.state/'artifacts'), store)
    queue = CommandQueue(store)
    budget = Budget(store, load_pricing(settings.state/'pricing.json'))
    configure([settings.api_key, settings.token])
    orchestrator=Orchestrator(settings,store,queue,artifacts)
    reference_worker=ReferenceWorker(settings,store,artifacts,orchestrator)
    app_commands=ReferenceCommands(settings,store,queue,artifacts)
    chat_turns=ChatTurns(settings,store,artifacts)
    house_service=HouseService(settings,store,queue,artifacts,orchestrator.shutdown)

    @asynccontextmanager
    async def lifespan(app):
        lock = (settings.state/'service.lock').open('a')
        try: fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            lock.close(); raise RuntimeError('Only one HDRP agent service may own this workspace')
        queue.expire(restart=True)
        orchestrator.recover_startup()
        reference_worker.recover_startup()
        app_commands.recover_startup()
        chat_turns.recover_startup()
        house_service.recover_startup()
        async def monitor():
            while True:
                await asyncio.sleep(1)
                await asyncio.to_thread(queue.expire)
                await asyncio.to_thread(app_commands.reconcile)
        async def worker():
            while not orchestrator.shutdown.is_set():
                house=await asyncio.to_thread(house_service.next_ready)
                if house:
                    await asyncio.to_thread(house_service.run,house)
                    continue
                reference=await asyncio.to_thread(reference_worker.next_ready)
                if reference:
                    await asyncio.to_thread(reference_worker.run,reference)
                    continue
                sid=await asyncio.to_thread(orchestrator.next_created)
                if sid:await asyncio.to_thread(orchestrator.run,sid)
                else:await asyncio.sleep(.25)
        task = asyncio.create_task(monitor())
        worker_task=asyncio.create_task(worker())
        try: yield
        finally:
            orchestrator.shutdown.set()
            await worker_task
            task.cancel()
            with suppress(asyncio.CancelledError): await task
            fcntl.flock(lock, fcntl.LOCK_UN);lock.close()

    app = FastAPI(title='HDRP scene agent', lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings,app.state.store,app.state.queue,app.state.artifacts,app.state.budget = settings,store,queue,artifacts,budget
    app.state.orchestrator=orchestrator
    app.state.reference_worker=reference_worker
    app.state.app_commands=app_commands
    app.state.house_service=house_service
    attach_chat(app,settings,store,artifacts,chat_turns)

    @app.middleware('http')
    async def boundary(request, call_next):
        bearer = request.headers.get('authorization','')
        if not secrets.compare_digest(bearer, 'Bearer '+settings.token):
            return JSONResponse(AgentError('UNAUTHORIZED','Invalid local token',401).as_dict(),status_code=401)
        if request.headers.get('origin'):
            return JSONResponse(AgentError('ORIGIN_DENIED','Browser origins are not enabled',403).as_dict(),status_code=403)
        binary = request.method=='PUT' and request.url.path.startswith('/v1/artifacts/')
        media = request.headers.get('content-type','').split(';')[0]
        limit = (20_000_000 if media in {'video/mp4','application/octet-stream'} else 10_000_000) if binary else 1_000_000
        try:
            size=0;chunks=[]
            async for chunk in request.stream():
                size+=len(chunk)
                if size>limit: return JSONResponse(AgentError('PAYLOAD_TOO_LARGE','Request exceeds route limit',413).as_dict(),status_code=413)
                chunks.append(chunk)
            request._body=b''.join(chunks)
            return await call_next(request)
        except (ValueError, json.JSONDecodeError):
            return JSONResponse(AgentError('INVALID_INPUT','Malformed request',422).as_dict(),status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc): return JSONResponse(AgentError("NOT_FOUND" if exc.status_code==404 else "HTTP_ERROR","Resource or method unavailable",exc.status_code).as_dict(),status_code=exc.status_code)

    @app.exception_handler(AgentError)
    async def agent_error(request, exc): return JSONResponse(exc.as_dict(),status_code=exc.status)
    @app.exception_handler(ValidationError)
    async def validation_error(request, exc): return JSONResponse(AgentError('INVALID_INPUT','Payload does not satisfy the reviewed contract',422).as_dict(),status_code=422)

    async def body(request, name):
        try: return payload(name, await request.json())
        except (ValueError,TypeError): raise AgentError('INVALID_INPUT','Payload does not satisfy the reviewed contract',422)

    @app.get('/health')
    def health():
        with closing(store.connect()) as c: recovery=c.execute("SELECT 1 FROM sessions WHERE state='recovery_required'").fetchone()
        return payload('Health',dict(status='recovery_required' if recovery else 'ready',schema_version='1.0',provider_mode=settings.provider_mode))

    @app.post('/v1/projects/register')
    async def register(request: Request):
        data=await body(request,'ProjectRegister')
        root=settings.project_path(data['project_root'])
        scene_path=contained(root,root/data['working_scene_path'])
        if not scene_path.is_file() or scene_path.suffix!='.unity' or not scene_path.is_relative_to(root/'Assets'):
            raise AgentError('OUT_OF_SCOPE','A saved scene under project Assets is required',422)
        if data['editor_version']!='6000.3.23f1' or data['hdrp_version']!='17.3.0': raise AgentError('UNSUPPORTED_PIPELINE','This adapter is qualified for Unity 6000.3.23f1 and HDRP 17.3.0')
        report=artifacts.put(canonical(data).encode(),'application/json',metadata={'kind':'capabilities'})
        def action(c):
            row=c.execute('SELECT body FROM projects WHERE id=?',(data['project_id'],)).fetchone()
            if row:
                prior=json.loads(row[0])
                if any(prior[k]!=data[k] for k in ['project_root','editor_version','hdrp_version','graphics_api']): raise AgentError('PROJECT_CONFLICT','Registered project identity or versions changed')
                queue.change_epoch(c,data['project_id'],data['bridge_epoch'])
            c.execute('INSERT INTO projects VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET epoch=excluded.epoch,body=excluded.body',(data['project_id'],data['bridge_epoch'],canonical(data)))
            scene=c.execute('SELECT project_id FROM scenes WHERE id=?',(data['scene_id'],)).fetchone()
            if scene and scene[0]!=data['project_id']: raise AgentError('SCENE_CONFLICT','Scene belongs to another project')
            c.execute('INSERT INTO scenes VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET body=excluded.body',(data['scene_id'],data['project_id'],canonical(data)))
            store.event(c,data['project_id'],'registered',data)
            return payload('ProjectRegistered',dict(project_id=data['project_id'],scene_id=data['scene_id'],scene_version=data['scene_version'],capability_report_hash=report))
        return store.idempotent('register',request.headers.get('idempotency-key'),data,action)

    @app.post('/v1/app/actions',status_code=202)
    async def admit_action(request: Request):
        data=await body(request,'AppActionRequest')
        service=house_service if data['kind']=='generate_house' else app_commands
        return await asyncio.to_thread(service.admit,data)

    @app.post('/v1/app/actions/{action_id}/stop',status_code=202)
    async def stop_action(action_id: str,request: Request):
        service=house_service if house_service.owns(action_id) else app_commands
        return await asyncio.to_thread(service.stop,action_id,await body(request,'StopRequest'))

    @app.get('/v1/app/actions/{action_id}')
    def get_action(action_id: str):return (house_service if house_service.owns(action_id) else app_commands).get(action_id)

    @app.get('/v1/app/actions/{action_id}/house')
    def house_progress(action_id: str):return house_service.progress(action_id)

    @app.get('/v1/budget')
    def get_budget(): return payload('Budget',budget.state())

    @app.post('/v1/sessions',status_code=202)
    async def create_session(request: Request):
        return await asyncio.to_thread(orchestrator.create,await body(request,'SessionCreate'),request.headers.get('idempotency-key'))

    @app.get('/v1/sessions/{session_id}/report')
    def report(session_id: str):return reporting.build(store,artifacts,session_id)

    @app.get('/v1/sessions/{session_id}')
    def get_session(session_id: str): return payload('Session',store.get('sessions',session_id))

    @app.post('/v1/sessions/{session_id}/stop',status_code=202)
    async def stop_session(session_id: str,request: Request):
        data=await body(request,'StopRequest')
        def action(c):
            row=c.execute('SELECT body,state FROM sessions WHERE id=?',(session_id,)).fetchone()
            if not row:raise AgentError('NOT_FOUND','Session does not exist',404)
            if row['state'] in {'completed','interrupted','limit_reached'}:return json.loads(row['body'])
            c.execute('UPDATE sessions SET stop_requested=1 WHERE id=?',(session_id,))
            c.execute("UPDATE commands SET cancel_requested=1 WHERE session_id=? AND status IN ('queued','claimed','running','unknown')",(session_id,))
            return payload('Session',store.update_session(c,session_id,stop_reason='Stop requested: '+data['reason']))
        return store.idempotent('stop:'+session_id,request.headers.get('idempotency-key'),data,action)

    @app.post('/v1/budget/reconcile')
    async def reconcile(request: Request):
        data=await body(request,'Reconcile')
        return store.idempotent('reconcile',request.headers.get('idempotency-key'),data,lambda c: budget.reconcile(**data,conn=c))

    @app.post('/v1/bridge/poll')
    async def poll(request: Request): return payload('CommandBatch',queue.poll(await body(request,'Poll')))

    @app.post('/v1/bridge/commands/{command_id}/progress')
    async def progress(command_id: str,request: Request): return payload('CommandControl',queue.progress(command_id,await body(request,'Progress')))

    @app.post('/v1/bridge/commands/{command_id}/result')
    async def result(command_id: str,request: Request):
        data=await body(request,'CommandResult')
        for digest in set(data['artifact_hashes'] + ([data['details_artifact_hash']] if data['details_artifact_hash'] else [])):
            artifacts.read(digest)
        return payload('Ack',queue.result(command_id,data))

    @app.put('/v1/artifacts/{sha256}',status_code=201)
    async def put_artifact(sha256: str,request: Request):
        digest=artifacts.put(await request.body(),request.headers.get('content-type','application/octet-stream').split(';')[0],expected=sha256)
        return payload('Ack',dict(accepted=True,id=digest))

    @app.get('/v1/artifacts/{sha256}')
    def get_artifact(sha256: str): return Response(artifacts.read(sha256),media_type='application/octet-stream')

    # Recovery routes are installed with the explicit operator recovery workflow.
    app.openapi=lambda:json.loads((CONTRACTS/'http-api.openapi.json').read_text())
    return app
