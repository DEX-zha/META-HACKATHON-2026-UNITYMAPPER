"""Validate native house reference evidence and make a browsable, honest atlas."""
import hashlib
import html
import json
from pathlib import Path
from PIL import Image
from .domain import AgentError, canonical


def inspect_atlas(directory):
    directory=Path(directory).resolve()
    source=json.loads((directory/'atlas.json').read_text())
    if source.get('schema_version')!='house-atlas.v1':raise AgentError('INVALID_INPUT','Unknown native atlas schema')
    captures=[]
    for record in source.get('captures',[]):
        file=record.get('file','');path=directory/file
        if Path(file).name!=file or path.is_symlink() or not path.is_file():raise AgentError('OUT_OF_SCOPE','Atlas capture must be an owned regular file')
        data=path.read_bytes()
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if image.size!=(1280,720):raise AgentError('INVALID_MEDIA','Unexpected atlas dimensions')
        captures.append(dict(record,sha256=hashlib.sha256(data).hexdigest()))
    groups={}
    for row in source.get('instances',[]):groups.setdefault(row.get('room') or 'Structure / shared',[]).append(row)
    result=dict(schema_version='house-atlas-index.v1',status=source['status'],source_sha256=source['source_sha256'],source_unchanged=source.get('source_unchanged',False),resolved_prefab_roots=len(source.get('instances',[])),rooms=[dict(r,instances=len(groups.get(r['name'],[])),captures=[c for c in captures if c['key'].startswith(r['name']+'-')]) for r in source.get('rooms',[])],captures=captures,visual_qualified=False,limitations=['These are captured observations, not a qualified traversal or proof of final reference lighting.','Functional prefab fronts and support surfaces still need explicit evidence.'])
    (directory/'index.json').write_text(canonical(result))
    esc=html.escape
    cards=[]
    for room in result['rooms']:
        photos=''.join(f'<figure><a href="{esc(c["file"],quote=True)}"><img loading="lazy" src="{esc(c["file"],quote=True)}" alt="{esc(c["key"],quote=True)}"></a><figcaption>{esc(c["key"])} · cadrage à qualifier</figcaption></figure>' for c in room['captures'])
        cards.append(f'<section><h2>{esc(room["name"])} · {room["instances"]} racines prefab</h2><div class="views">{photos}</div></section>')
    room_keys={c['key'] for room in result['rooms'] for c in room['captures']}
    transitions=[c for c in captures if c['key'] not in room_keys]
    if transitions:
        photos=''.join(f'<figure><a href="{esc(c["file"],quote=True)}"><img loading="lazy" src="{esc(c["file"],quote=True)}" alt="{esc(c["key"],quote=True)}"></a><figcaption>{esc(c["key"])} · cadrage à qualifier</figcaption></figure>' for c in transitions)
        cards.append(f'<section><h2>Escaliers et transitions</h2><div class="views">{photos}</div></section>')
    page='''<!doctype html><html lang="fr"><meta charset="utf-8"><title>Atlas de référence — House worn night</title><style>body{font:16px system-ui;background:#10151d;color:#edf2fa;margin:32px}h1{font-size:30px}p{max-width:1000px;line-height:1.6;color:#b8c4d6}.views{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}figure{margin:0}img{width:100%;border-radius:10px}figcaption{font-size:13px;padding:8px;color:#b8c4d6}section{margin:32px 0}a{color:#90baff}</style><h1>House_worn_night · atlas natif</h1>'''
    page+=f'<p>{result["resolved_prefab_roots"]} racines de prefabs résolues · {len(captures)} captures · source inchangée : {result["source_unchanged"]}. Scène chargée dans une preview isolée. Ces vues documentent la référence ; elles ne certifient pas encore les supports, les orientations fonctionnelles ou les parcours.</p>'+''.join(cards)
    (directory/'index.html').write_text(page+'</html>')
    return result
