"""Paired, spatially registered crops for pose correction, never source transforms."""
import io
import math
import numpy as np
from PIL import Image
from .reference_geometry import rotation


def projected_box(item,asset,frame):
    view=frame.get('calibration')
    if not view:return None
    corners=np.array([[x,y,z] for x in [-.5,.5] for y in [-.5,.5] for z in [-.5,.5]])*asset['bounds_size_m']+asset['bounds_center_m']
    world=(corners*item['scale'])@rotation(item['rotation_deg']).T+item['position_m']
    p=(world-view['position_m'])@rotation(view['rotation_deg'])
    if np.any(p[:,2]<=.05):return None
    t=math.tan(math.radians(view['fov_deg'])/2);aspect=frame['model_size'][0]/frame['model_size'][1]
    uv=np.column_stack([.5+p[:,0]/p[:,2]/(2*t*aspect),.5-p[:,1]/p[:,2]/(2*t)])
    return [*uv.min(axis=0),*uv.max(axis=0)]


def correction_boards(artifacts,analysis,frames,candidates,plan,catalogue,*,segments=(),priority_view='work-top-front',metrics=None):
    """Two whole-view pairs + <=10 object boards, each with <=2 camera pairs.

    Left reference/right candidate, identical crop rectangle and scale. Includes
    projected candidate bounds so a displacement cannot disappear by recentering.
    Coordinates below always refer to the original frames, not board pixels.
    """
    by_key={f['key']:f for f in frames if not f['key'].startswith('control-')};by_candidate={f['key']:f for f in candidates if not f['key'].startswith('control-')}
    assets={a['asset_id']:a for a in catalogue};objects={o['key']:o for o in plan['objects']};images=[];metadata=[]
    def read(frame):
        with Image.open(io.BytesIO(artifacts.read(frame['artifact_hash']))) as image:return image.convert('RGB')
    def emit(pairs,info):
        width=max(a.width+b.width for a,b in pairs);height=sum(max(a.height,b.height) for a,b in pairs)
        board=Image.new('RGB',(width,height),(24,24,24));y=0
        for a,b in pairs:board.paste(a,(0,y));board.paste(b,(a.width,y));y+=max(a.height,b.height)
        if board.width>1280 or board.height>720:board.thumbnail((1280,720),Image.Resampling.LANCZOS)
        data=io.BytesIO();board.save(data,format='PNG');raw=data.getvalue();images.append(raw)
        metadata.append(dict(image_index=len(images)-1,artifact_hash=artifacts.put(raw,'image/png'),layout='each row: reference LEFT, candidate RIGHT; same original crop on both sides',**info))
    available=[key for key in by_key if key in by_candidate]
    # The requested priority is supplied at original resolution as two images,
    # rather than reduced to a small row of an overview board.
    if priority_view in available:
        for side,frame in [('REFERENCE',by_key[priority_view]),('CANDIDATE',by_candidate[priority_view])]:
            data=artifacts.read(frame['artifact_hash']);images.append(data)
            metadata.append(dict(image_index=len(images)-1,artifact_hash=frame['artifact_hash'],kind='priority_full_frame',side=side,view_key=priority_view))
        available.remove(priority_view)
    for offset in range(0,len(available),4):
        pairs=[];keys=available[offset:offset+4]
        for key in keys:
            a=read(by_key[key]);b=read(by_candidate[key]);b=b.resize(a.size,Image.Resampling.LANCZOS)
            a.thumbnail((640,360),Image.Resampling.LANCZOS);b=b.resize(a.size,Image.Resampling.LANCZOS);pairs.append((a,b))
        emit(pairs,dict(kind='whole_view_pairs',view_keys=keys))
    # Largest region discrepancy first when more than ten objects are visible.
    ranked=[]
    for observed in analysis['objects']:
        item=objects[observed['key']];asset=assets.get(item['asset_id']);pairs=[];rows=[];errors=[]
        boxes=list(observed['view_boxes'])
        priority_mask=next((s['selection'] for s in segments if s['object_key']==observed['key'] and s['view_key']==priority_view and s.get('selection')),None)
        priority_box=priority_mask['bbox_xyxy'] if priority_mask else next((b['bbox_xyxy'] for b in boxes if b['view_key']==priority_view),None)
        if priority_box is None and asset and priority_view in by_key:
            priority_box=projected_box(item,asset,by_key[priority_view])
        if priority_box is not None:
            boxes=[dict(view_key=priority_view,bbox_xyxy=priority_box,region_source='reference_mask' if priority_mask else 'reference_box_or_candidate_projection')]+[b for b in boxes if b['view_key']!=priority_view]
        chosen=[]
        for box in sorted(boxes,key=lambda b:b['view_key']!=priority_view):
            key=box['view_key']
            if key in by_candidate and key in by_key:chosen.append(box)
            if len(chosen)==2:break
        for box in chosen:
            key=box['view_key'];a=read(by_key[key]);b=read(by_candidate[key]);b=b.resize(a.size,Image.Resampling.LANCZOS)
            bounds=box['bbox_xyxy'];predicted=projected_box(item,asset,by_key[key]) if asset else None
            x0,y0,x1,y1=bounds
            if predicted:x0=min(x0,predicted[0]);y0=min(y0,predicted[1]);x1=max(x1,predicted[2]);y1=max(y1,predicted[3])
            dx=max(.025,(x1-x0)*.2);dy=max(.025,(y1-y0)*.2)
            rect=[max(0,int((x0-dx)*a.width)),max(0,int((y0-dy)*a.height)),min(a.width,math.ceil((x1+dx)*a.width)),min(a.height,math.ceil((y1+dy)*a.height))]
            if rect[0]>=rect[2] or rect[1]>=rect[3]:continue
            ca,cb=a.crop(rect),b.crop(rect);pairs.append((ca,cb));errors.append(float(np.abs(np.asarray(ca,dtype=float)-np.asarray(cb,dtype=float)).mean()))
            rows.append(dict(view_key=key,reference_hash=by_key[key]['artifact_hash'],candidate_hash=by_candidate[key]['artifact_hash'],original_size=list(a.size),crop_xyxy_px=rect,reference_visible_box=bounds,region_source=box.get('region_source','reference_box'),candidate_projected_full_bounds=predicted,camera=by_key[key]['calibration']))
        if pairs:
            error=float(np.mean(errors));geometry=(metrics or {}).get('geometry',{}).get('per_object',{}).get(observed['key'])
            priority=(2. if geometry['mean_iou'] is None else 1-geometry['mean_iou']) if geometry else error/255
            ranked.append((priority,observed['key'],pairs,rows,error))
    for priority,key,pairs,rows,error in sorted(ranked,key=lambda r:-r[0])[:max(0,12-len(images))]:emit(pairs,dict(kind='object_pose_pairs',object_key=key,rows=rows,region_rgb_mae=error/255,inspection_priority=priority))
    return images,metadata
