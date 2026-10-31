"""Internal chat routes; browser requests remain confined to the Go server."""
from contextlib import closing
from datetime import datetime,timezone,timedelta
import asyncio,io,json
from PIL import Image
from fastapi import Request
from .domain import AgentError

def attach(app,settings,store,artifacts,turns):
    @app.get('/v1/projects')
    def projects():
        result=[]
        with closing(store.connect()) as c:rows=c.execute('SELECT body,projects.epoch,project_presence.epoch AS presence_epoch,last_seen FROM projects LEFT JOIN project_presence ON projects.id=project_presence.project_id ORDER BY projects.id LIMIT 100').fetchall()
        for row in rows:
            p=json.loads(row[0])
            try:root=settings.project_path(p['project_root'])
            except (AgentError,KeyError):continue
            connected=bool(row['last_seen'] and row['epoch']==row['presence_epoch'] and datetime.fromisoformat(row['last_seen'].replace('Z','+00:00')) >= datetime.now(timezone.utc)-timedelta(seconds=15))
            result.append(dict(connected=connected,id=p['project_id'],label=root.name,canonical_root=str(root),scene_version=p['scene_version'],scene_path=p['working_scene_path'],capabilities=p['capabilities'],bridge_epoch=p['bridge_epoch']))
        return result

    @app.post('/v1/chat/attachments')
    async def bind_attachment(request:Request):
        data=await request.json()
        if not isinstance(data,dict) or set(data)!={'project_id','artifact_hash'}:raise AgentError('INVALID_INPUT','Attachment identity required',422)
        project=store.get('projects',data['project_id']);settings.project_path(project['project_root'])
        raw=artifacts.read(data['artifact_hash'])
        if len(raw)>10_000_000:raise AgentError('PAYLOAD_TOO_LARGE','Image exceeds 10 MB',413)
        try:
            with Image.open(io.BytesIO(raw)) as im:
                if im.format not in {'PNG','JPEG'} or im.width*im.height>40_000_000:raise ValueError()
                im.verify()
        except Exception:raise AgentError('INVALID_MEDIA','This chat release accepts PNG/JPEG images only',422)
        with store.tx() as c:c.execute('INSERT OR IGNORE INTO app_artifacts VALUES(?,?)',(data['project_id'],data['artifact_hash']))
        return dict(artifact_hash=data['artifact_hash'])

    @app.post('/v1/chat/turns')
    async def send_turn(request:Request):return await asyncio.to_thread(turns.send,await request.json())

    @app.get('/v1/chat/turns/{turn_id}')
    def get_turn(turn_id:str):return turns.get(turn_id)
