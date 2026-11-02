"""Verified visual pages for asset browsing; previews never qualify geometry or fronts."""
import hashlib
import io
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
from .domain import AgentError


def family(asset):
    return asset['prefab_path'].split('/Prefabs/')[-1].rsplit('/', 1)[0]


def load_previews(directory, assets):
    directory = Path(directory).resolve()
    path = directory / 'manifest.json'
    if not path.is_file():
        return {}, list(assets)
    records = json.loads(path.read_text())
    by_guid = {}
    for record in records:
        guid = record['prefab_guid']
        if guid in by_guid:
            raise AgentError('INVALID_INPUT', 'Duplicate visual catalogue identity')
        by_guid[guid] = record
    ready, unavailable = {}, []
    for name, asset in assets.items():
        record = by_guid.get(asset['prefab_guid'])
        if not record or record.get('status') != 'ready':
            unavailable.append(name)
            continue
        if record['dependency_hash'] != asset['dependency_hash'] or record['path'] != asset['prefab_path']:
            unavailable.append(name)
            continue
        filename = record['file']
        image_path = directory / filename
        if Path(filename).name != filename or image_path.is_symlink() or not image_path.is_file():
            raise AgentError('OUT_OF_SCOPE', 'Catalogue preview must be an owned regular file')
        data = image_path.read_bytes()
        if hashlib.sha256(data).hexdigest() != record['sha256']:
            raise AgentError('STALE_EVIDENCE', 'Catalogue preview hash changed')
        with Image.open(io.BytesIO(data)) as image:
            if image.size != (1280, 640):
                raise AgentError('INVALID_MEDIA', 'Expected two-angle prefab preview')
            image.verify()
        ready[name] = dict(record, data=data, family=family(asset), size_m=asset['bounds_size'])
    return ready, unavailable


def pages(previews, names=None):
    """Page all requested assets without silently dropping overflow or unreadable IDs."""
    selected = sorted(previews if names is None else names)
    unknown = set(selected) - previews.keys()
    if unknown:
        raise AgentError('INVALID_INPUT', 'Requested preview unavailable: ' + ', '.join(sorted(unknown)))
    font = ImageFont.load_default(size=18)
    for start in range(0, len(selected), 4):
        keys = selected[start:start + 4]
        canvas = Image.new('RGB', (1280, 720), '#17212b')
        draw = ImageDraw.Draw(canvas)
        records = []
        for index, name in enumerate(keys):
            record = previews[name]
            x, y = (index % 2) * 640, (index // 2) * 360
            with Image.open(io.BytesIO(record['data'])) as image:
                image = image.convert('RGB')
                image.thumbnail((624, 300))
                canvas.paste(image, (x + (640-image.width)//2, y))
            # A numeric key remains readable even for long prefab names.
            key = str(start + index + 1)
            draw.text((x+10, y+304), key + ': ' + name[:48], font=font, fill='white')
            draw.text((x+10, y+332), ' x '.join(f'{v:.2f}' for v in record['size_m'])+' m', font=font, fill='#bdcddd')
            records.append(dict(key=key, asset_id=name, prefab_guid=record['prefab_guid'], dependency_hash=record['dependency_hash'], image_sha256=record['sha256'], family=record['family'], size_m=record['size_m']))
        stream = io.BytesIO()
        canvas.save(stream, format='PNG')
        yield dict(image=stream.getvalue(), assets=records, semantic_qualified=False)
