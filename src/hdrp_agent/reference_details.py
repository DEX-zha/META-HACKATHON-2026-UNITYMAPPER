"""Object-linked closeups, with native capture proof or original-resolution crops."""
import io
import math
import struct
from pathlib import Path

from PIL import Image,ImageOps

from .capture_validation import read_capture
from .config import contained
from .domain import AgentError
from .reference_media import bounded_image


def original_crops(analysis,frames,artifacts):
    details=[]
    for item in analysis['objects']:
        for index,box in enumerate(item['view_boxes'][:3]):
            frame=next(f for f in frames if f['key']==box['view_key'])
            raw=artifacts.read(frame.get('original_artifact_hash',frame['artifact_hash']))
            with Image.open(io.BytesIO(raw)) as source:
                source=ImageOps.exif_transpose(source).convert('RGB');w,h=source.size
                rect=box['bbox_xyxy']
                if len(rect)!=4 or any(not math.isfinite(v) or not 0<=v<=1 for v in rect) or rect[2]<=rect[0] or rect[3]<=rect[1]:raise AgentError('INVALID_MEDIA','Invalid detail crop')
                pixels=[max(0,math.floor(rect[0]*w)),max(0,math.floor(rect[1]*h)),min(w,math.ceil(rect[2]*w)),min(h,math.ceil(rect[3]*h))]
                image=source.crop(pixels);out=io.BytesIO();image.save(out,format='PNG');data,transform=bounded_image(out.getvalue())
            details.append(dict(key=f'crop-{len(details):03}',object_key=item['key'],artifact_hash=artifacts.put(data,'image/png'),source_view_key=frame['key'],source_box_xyxy=rect,source_pixels=pixels,acquisition='original_resolution_crop',calibration=None,**transform))
    return details


def native_details(result,analysis,capture_root,source_version,artifacts):
    allowed={item['key'] for item in analysis['objects']};details=[];keys=set()
    if set(result)!={'captures','limits'} or len(result['captures'])>8:raise AgentError('INVALID_MEDIA','Invalid detail capture result')
    for record in result['captures']:
        root=contained(Path(capture_root),Path(record['capture_directory']));checked=read_capture(root)
        if checked['request']['version_id']!=source_version or checked['request']['include_clip']:raise AgentError('STALE_VERSION','Detail frames must belong to the preserved source version')
        poses={view['key']:view for view in checked['request']['plan']['work_views']}
        if len(record['views'])>8:raise AgentError('INVALID_MEDIA','Detail batch exceeds bound')
        for view in record['views']:
            key=view['key'];pose={k:v for k,v in view.items() if k not in {'object_key','angle'}}
            def frozen(value):
                if value is None:return None
                single=lambda n:struct.unpack('!f',struct.pack('!f',n))[0]
                return dict(key=value['key'],position_m=[single(n) for n in value['position_m']],rotation_deg=[single(n) for n in value['rotation_deg']],fov_deg=single(value['fov_deg']))
            if key in keys or view['object_key'] not in allowed or frozen(pose)!=frozen(poses.get(key)) or view['angle'] not in {'front','back','top'}:raise AgentError('STALE_VERSION','Unregistered detail view or association')
            frame=next(f for f in checked['statics'] if f['camera_key']==key);raw=(root/frame['file']).read_bytes();data,transform=bounded_image(raw)
            details.append(dict(key=key,object_key=view['object_key'],angle=view['angle'],artifact_hash=artifacts.put(data,'image/png'),acquisition='native_camera_closeup',calibration=pose,**transform));keys.add(key)
    if len(details)>60:raise AgentError('INVALID_MEDIA','At most sixty native detail views')
    return details
