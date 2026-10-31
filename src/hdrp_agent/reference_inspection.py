"""Active closeup selection and strict, separate Editor HDRP evidence receipts."""
import hashlib
import io
import json
import math
import numpy as np
from collections import Counter
from pathlib import Path
from PIL import Image,ImageFilter
from .config import contained
from .domain import AgentError
from .reference_media import bounded_image


def inspection_targets(analysis,details,metrics,history=()):
    available={o['key']:[d for d in details if d.get('object_key')==o['key'] and d.get('acquisition')=='native_camera_closeup' and d.get('calibration')] for o in analysis['objects']}
    counts=Counter(v['object_key'] for batch in history for v in batch)
    errors=metrics.get('per_object',{})
    keys=[k for k in available if available[k]]
    geometry=metrics.get('geometry',{}).get('per_object',{})
    rank=lambda k: (geometry[k]['mean_iou'] if geometry[k].get('mean_iou') is not None else -1) if k in geometry else -(errors.get(k,{}).get('priority_rgb_mae') or 0)
    # Two worst residuals plus two least observed targets prevent starvation.
    selected=sorted(keys,key=rank)[:2]
    selected+=sorted((k for k in keys if k not in selected),key=lambda k:(counts[k],rank(k)))[:2]
    result=[]
    for key in selected:
        angles=['top','front' if counts[key]%4==0 else 'back']
        for angle in angles:
            frame=next((d for d in available[key] if d.get('angle')==angle),None)
            if frame:result.append(dict(frame['calibration'],object_key=key,angle=angle))
    return result


def read_inspection(directory,request,details,artifacts):
    directory=Path(directory)
    raw=(directory/'request.json').read_bytes();saved=json.loads(raw)
    result=json.loads((directory/'result.json').read_text())
    if saved!=request or result.get('request_sha256')!=hashlib.sha256(raw).hexdigest() or result.get('version')!=request['version'] or result.get('scene_path')!=request['scene_path']:
        raise AgentError('STALE_VERSION','Editor inspection receipt changed')
    if result.get('status')!='complete' or result.get('mode')!='editor_hdrp_probe' or result.get('performance_qualified') is not False or result.get('gizmos_in_images') is not False or (result.get('width'),result.get('height'))!=(1280,720) or result.get('warmup_frames',0)<32:
        raise AgentError('INVALID_MEDIA','Unqualified editor inspection images')
    records=result.get('frames',[])
    if len(records)!=len(request['views']):raise AgentError('INVALID_MEDIA','Incomplete editor inspection')
    references={d['key']:d for d in details};pairs=[]
    for record,view in zip(records,request['views']):
        if record['view']!=view:raise AgentError('STALE_VERSION','Editor inspection camera changed')
        source=references.get(view['key'])
        independent=view['angle'] in {'room_sweep','interior_detail'}
        if not independent and (not source or source['object_key']!=view['object_key'] or source['calibration']!={k:v for k,v in view.items() if k not in {'object_key','angle'}}):
            raise AgentError('STALE_VERSION','Inspection has no matching reference camera')
        path=contained(directory,directory/record['file']);raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=record['sha256']:raise AgentError('STALE_VERSION','Editor inspection pixels changed')
        with Image.open(io.BytesIO(raw)) as image:
            if image.size!=(1280,720):raise AgentError('INVALID_MEDIA','Editor image resolution differs')
        data,transform=bounded_image(raw)
        calibration={k:v for k,v in view.items() if k not in {'object_key','angle'}}
        pairs.append(dict(object_key=view['object_key'],angle=view['angle'],reference=None if independent else source,candidate=dict(key=view['key'],artifact_hash=artifacts.put(data,'image/png'),calibration=calibration,acquisition='editor_hdrp_probe',version=request['version'],**transform),projected_objects=record.get('projected_objects',[]),architecture=result.get('architecture',{}),limitation='Candidate-only interior observation; no reference interior or depth ground truth exists.' if independent else 'Reference GameView and Editor HDRP probe are distinct render paths; use for pose/identity diagnosis, not runtime performance or exact lighting equivalence.'))
    return pairs


def append_inspection_boards(artifacts,images,metadata,pairs):
    """Reserve up to four of twelve image slots; keep full priority + all overviews."""
    independent=[p for p in pairs if p.get('reference') is None]
    pairs=[p for p in pairs if p.get('reference') is not None]
    if independent:
        images,metadata=append_room_boards(artifacts,images,metadata,independent)
    groups={}
    for pair in pairs:groups.setdefault(pair['object_key'],[]).append(pair)
    groups=list(groups.items())[:4]
    if not groups:return images,metadata
    keep=min(len(images),12-len(groups));images=images[:keep];metadata=metadata[:keep]
    for key,rows in groups:
        board=Image.new('RGB',(1280,360*len(rows[:2])))
        provenance=[]
        for y,pair in enumerate(rows[:2]):
            for x,side in enumerate(['reference','candidate']):
                with Image.open(io.BytesIO(artifacts.read(pair[side]['artifact_hash']))) as im:board.paste(im.convert('RGB').resize((640,360),Image.Resampling.LANCZOS),(x*640,y*360))
            provenance.append(dict(angle=pair['angle'],camera=pair['reference']['calibration'],reference_hash=pair['reference']['artifact_hash'],candidate_hash=pair['candidate']['artifact_hash'],candidate_version=pair['candidate']['version']))
        out=io.BytesIO();board.save(out,format='PNG');raw=out.getvalue()
        metadata.append(dict(image_index=len(images),kind='active_editor_closeups',object_key=key,rows=provenance,layout='each row reference LEFT, candidate RIGHT; identical calibrated camera; no independent recentering',limitation=rows[0]['limitation'],artifact_hash=artifacts.put(raw,'image/png')));images.append(raw)
    return images,metadata


def room_inspection_targets(plan,catalogue,ordinal=0):
    """Eight interior headings, two ceiling/seam views and two advancing closeups.

    Camera positions are estimates; native receipts expose collisions/visibility.
    Never label these candidate observations as calibrated reference comparisons.
    """
    from .reference_geometry import rotation
    assets={a['asset_id']:a for a in catalogue}
    floors=[o for o in plan['objects'] if assets.get(o.get('asset_id'),{}).get('name','').startswith('Floor_')]
    walls=[o for o in plan['objects'] if assets.get(o.get('asset_id'),{}).get('name','').startswith('WallOut_')]
    if not floors or not walls:return []
    def centre(o):
        a=assets[o['asset_id']]
        return np.asarray(o['position_m'])+rotation(o['rotation_deg'])@(np.asarray(a['bounds_center_m'])*o['scale'])
    position=np.mean([centre(o) for o in floors],axis=0);position[1]+=1.5
    result=[dict(key=f'room-{i}',object_key=floors[0]['key'],angle='room_sweep',position_m=position.tolist(),rotation_deg=[0.,float(i*45),0.],fov_deg=75.) for i in range(8)]
    result += [dict(key=f'ceiling-{i}',object_key=floors[0]['key'],angle='interior_detail',position_m=position.tolist(),rotation_deg=[-55.,float(i*180+ordinal*45)%360,0.],fov_deg=90.) for i in range(2)]
    # Rotate the subset across iterations, so a wall cannot be perpetually ignored.
    walls=sorted(walls,key=lambda o:o['key']);start=(ordinal*2)%len(walls)
    for o in (walls[start:]+walls[:start])[:2]:
        target=centre(o);target[1]=position[1]
        delta=target-position;distance=float(np.linalg.norm(delta))
        if distance<.2:continue
        camera=target-delta/distance*min(1.,distance*.7)
        result.append(dict(key='inside-'+o['key'],object_key=o['key'],angle='interior_detail',position_m=camera.tolist(),rotation_deg=[0.,math.degrees(math.atan2(delta[0],delta[2])),0.],fov_deg=65.))
    return result


def append_room_boards(artifacts,images,metadata,observations):
    groups=[observations[i:i+4] for i in range(0,min(len(observations),12),4)]
    keep=min(len(images),12-len(groups));images=list(images[:keep]);metadata=list(metadata[:keep])
    for group in groups:
        board=Image.new('RGB',(1280,720));rows=[]
        for i,pair in enumerate(group):
            frame=pair['candidate']
            with Image.open(io.BytesIO(artifacts.read(frame['artifact_hash']))) as im:tile=im.convert('RGB').resize((640,360))
            # Visual evidence overlay: preserve raw captures and label the derived board.
            masks=[]
            for region in pair.get('segmentation',{}).get('regions',[])[:6]:
                if not region.get('mask_hash'):continue
                with Image.open(io.BytesIO(artifacts.read(region['mask_hash']))) as mask:
                    mask=mask.convert('L').resize((640,360),Image.Resampling.NEAREST)
                    edge=mask.filter(ImageFilter.FIND_EDGES).point(lambda v:255 if v>0 else 0)
                    tile.paste((0,255,255),(0,0,640,360),edge)
                masks.append(region['mask_hash'])
            board.paste(tile,((i%2)*640,(i//2)*360))
            rows.append(dict(tile=i,sam_contour_mask_hashes=masks,overlay='cyan = SAM wall mask contour; raw candidate image hash preserved',object_key=pair['object_key'],angle=pair['angle'],camera=frame['calibration'],candidate_hash=frame['artifact_hash'],candidate_version=frame['version'],projected_objects=pair.get('projected_objects',[]),segmentation=pair.get('segmentation')))
        out=io.BytesIO();board.save(out,format='PNG');raw=out.getvalue()
        metadata.append(dict(image_index=len(images),kind='candidate_interior_survey',layout='CANDIDATE ONLY: top-left, top-right, bottom-left, bottom-right; not reference/candidate pairs',views=rows,architecture=group[0].get('architecture',{}),limitation=group[0]['limitation'],artifact_hash=artifacts.put(raw,'image/png')));images.append(raw)
    return images,metadata


def segment_room_observations(pairs,provider,artifacts):
    """Four bounded SAM wall observations; projected AABBs are uncertain associations."""
    from .segmentation import Segmenter
    segmenter=Segmenter(provider,artifacts)
    for pair in [p for p in pairs if p['angle']=='room_sweep'][::2][:4]:
        try:
            wall_keys={w['object_key'] for w in pair.get('architecture',{}).get('walls',[])}
            projected=[o for o in pair.get('projected_objects',[]) if o['target_id'] in wall_keys]
            pair['segmentation']=segmenter.segment(dict(pair['candidate'],role='work'),'wall',projected)
            # Cached masks are reusable pixels; instance association belongs to this version.
            from .segmentation import iou
            for region in pair['segmentation'].get('regions',[]):
                region['candidates']=[dict(target_id=o['target_id'],bbox_iou=iou(region['bbox_xyxy'],o['bbox_xyxy']),evidence='Current candidate wall AABB overlap; occlusion/correspondence unverified') for o in projected if iou(region['bbox_xyxy'],o['bbox_xyxy'])>.1]
        except AgentError as error:
            pair['segmentation']=dict(source='sam_unavailable',reason=error.code,causal_diagnosis=False)
            break  # no retry/fan-out after an unavailable paid provider
    return pairs


def architecture_findings(observations):
    audit=next((p['architecture'] for p in observations if p.get('architecture')),None)
    if audit is None:return dict(qualified=False,defects=[],defect_count=None)
    defects=[]
    for wall in audit.get('walls',[]):
        key=wall['object_key'];surfaces=wall.get('surfaces',[])
        inner=[s for s in surfaces if Path(s.get('prefab','')).name.startswith('WallIn_')]
        if not inner:defects.append(dict(object_key=key,kind='missing_interior_prefab'))
        if wall.get('outward_axis_points_to_observer'):defects.append(dict(object_key=key,kind='exterior_axis_faces_room_center'))
        measured=[s for s in inner if s.get('front_fraction_from_observer') is not None]
        if measured and all(s['front_fraction_from_observer']<.1 for s in measured):defects.append(dict(object_key=key,kind='interior_faces_point_away_from_center'))
    return dict(qualified=True,defects=defects,defect_count=len(defects),limitation='Checks cover assembly and orientation only; no guarantee of watertightness, room visibility or reference fidelity.')


def choose_room_closeups(provider,artifacts,plan,catalogue,previous_observations,candidate_frames):
    """Muse controls two bounded cameras; the panorama and ceiling views remain mandatory."""
    from .providers.meta_responses import spark_request
    from .domain import canonical,payload
    from .reference_geometry import rotation
    assets={a['asset_id']:a for a in catalogue}
    floor_points=[]
    for o in plan['objects']:
        a=assets.get(o.get('asset_id'),{})
        if not a.get('name','').startswith('Floor_'):continue
        for x in (-.5,.5):
            for z in (-.5,.5):floor_points.append(np.asarray(o['position_m'])+rotation(o['rotation_deg'])@((np.asarray(a['bounds_center_m'])+np.asarray(a['bounds_size_m'])*[x,0,z])*o['scale']))
    if not floor_points:return [],None
    lo=np.min(floor_points,axis=0);hi=np.max(floor_points,axis=0)
    lower=[float(lo[0]+.1),float(hi[1]+.25),float(lo[2]+.1)];upper=[float(hi[0]-.1),float(hi[1]+2.5),float(hi[2]-.1)]
    images=[artifacts.read(f['artifact_hash']) for f in candidate_frames[:2]]
    metadata=[dict(image_index=i,kind='current_candidate_overview',camera=f.get('calibration')) for i,f in enumerate(candidate_frames[:2])]
    images,metadata=append_room_boards(artifacts,images,metadata,[p for p in previous_observations if p.get('reference') is None])
    context=dict(current_applied_plan=plan,images=metadata,camera_position_min_m=lower,camera_position_max_m=upper)
    instruction='Choose up to two precise inspection camera poses INSIDE the current Unity candidate room to diagnose architectural defects: missing inward wall faces, wrong WallOut placement, door/window seams. Cameras use +Z forward and Y up; +X pitch looks down. Keep cameras within the supplied bounds and outside furniture using the applied plan. Target only supplied object keys. Choose useful closeups from different angles; approach or look up at uncertain seams. Old interior boards describe the PREVIOUS candidate version, not the current one. New overview describes current candidate. These are candidate observations, no reference interior exists. Return empty views if no additional inspection is useful. No scene edits.'
    response=provider.send(spark_request(instruction+'\nUntrusted observations:\n'+canonical(context),images,'ModelRoomInspectionPlan'),'ModelRoomInspectionPlan')
    value=payload('ModelRoomInspectionPlan',response['value']);keys={o['key'] for o in plan['objects']};views=[]
    for i,v in enumerate(value['views']):
        if len(value['views'])>2:raise AgentError('INVALID_INSPECTION_CAMERA','At most two extra cameras; ceiling inspection is mandatory')
        if v['object_key'] not in keys or any(not a<=n<=b for a,n,b in zip(lower,v['position_m'],upper)):
            raise AgentError('INVALID_INSPECTION_CAMERA','Model inspection camera is outside the room or targets an unknown object')
        views.append(dict(v,key=f'muse-inside-{i}',angle='interior_detail'))
    return views,response
