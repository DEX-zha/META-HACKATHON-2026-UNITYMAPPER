"""Optional calibrated placement from image regions; no source scene geometry."""
import math
from itertools import combinations
import numpy as np


def rotation(euler):
    x,y,z=np.radians(euler);cx,sx,cy,sy,cz,sz=np.cos(x),np.sin(x),np.cos(y),np.sin(y),np.cos(z),np.sin(z)
    return np.array([[cy,0,sy],[0,1,0],[-sy,0,cy]])@np.array([[1,0,0],[0,cx,-sx],[0,sx,cx]])@np.array([[cz,-sz,0],[sz,cz,0],[0,0,1]])


def rotation_euler(matrix):
    """Inverse of Unity's Y-X-Z Euler composition, including gimbal lock."""
    m=np.asarray(matrix,dtype=float);x=math.asin(float(np.clip(-m[1,2],-1,1)))
    if abs(math.cos(x))>1e-8:y,z=math.atan2(m[0,2],m[2,2]),math.atan2(m[1,0],m[1,1])
    else:y,z=math.atan2(-m[2,0],m[0,0]),0.
    return np.degrees([x,y,z]).tolist()


def ray(view,box,aspect):
    x=(box[0]+box[2])/2;y=(box[1]+box[3])/2;t=math.tan(math.radians(view['fov_deg'])/2)
    direction=rotation(view['rotation_deg'])@np.array([(x*2-1)*aspect*t,(1-y*2)*t,1.])
    return np.asarray(view['position_m'],dtype=float),direction/np.linalg.norm(direction)


def triangulate(observations):
    if len(observations)<2:return None
    rays=[ray(view,box,aspect) for view,box,aspect in observations]
    if max(np.linalg.norm(np.cross(a[1],b[1])) for a in rays for b in rays)<math.sin(math.radians(1)):return None
    matrices=[np.eye(3)-np.outer(d,d) for o,d in rays]
    a=sum(matrices);b=sum(m@o for m,(o,d) in zip(matrices,rays))
    if np.linalg.cond(a)>10000:return None
    point=np.linalg.solve(a,b)
    for view,box,aspect in observations:
        p=rotation(view['rotation_deg']).T@(point-np.array(view['position_m']))
        if not .05<p[2]<100:return None
        t=math.tan(math.radians(view['fov_deg'])/2);uv=np.array([.5+p[0]/p[2]/(2*aspect*t),.5-p[1]/p[2]/(2*t)])
        if np.linalg.norm(uv-np.array([(box[0]+box[2])/2,(box[1]+box[3])/2]))>.025:return None
    return point


def robust_triangulate(observations):
    point=triangulate(observations)
    if point is not None:return point
    best=None;rank=None
    for pair in combinations(observations,2):
        point=triangulate(pair)
        if point is None:continue
        errors=[]
        for view,box,aspect in observations:
            p=rotation(view['rotation_deg']).T@(point-np.array(view['position_m']))
            if p[2]<=.05:errors.append(100.);continue
            t=math.tan(math.radians(view['fov_deg'])/2);uv=np.array([.5+p[0]/p[2]/(2*aspect*t),.5-p[1]/p[2]/(2*t)])
            errors.append(float(np.linalg.norm(uv-np.array([(box[0]+box[2])/2,(box[1]+box[3])/2]))))
        quality=(sum(e<.025 for e in errors),-float(np.median(errors)))
        if quality[0]>=2 and (rank is None or quality>rank):best=point;rank=quality
    return best


def fit_initial_positions(plan,analysis,frames,catalogue,segments):
    from copy import deepcopy
    output=deepcopy(plan);fits=[]
    by_asset={a['asset_id']:a for a in catalogue};by_frame={f['key']:f for f in frames}
    for item in output['objects']:
        if item['asset_id'] is None:continue
        observed=next((o for o in analysis['objects'] if o['key']==item['key']),None);observations=[]
        if observed is None:continue
        for box in observed['view_boxes']:
            frame=by_frame[box['view_key']]
            if frame['calibration'] is None:continue
            selected=next((s['selection'] for s in segments if s['object_key']==item['key'] and s['view_key']==frame['key'] and s['selection']),None)
            bounds=selected['bbox_xyxy'] if selected else box['bbox_xyxy']
            observations.append((frame['calibration'],bounds,frame['model_size'][0]/frame['model_size'][1]))
        point=robust_triangulate(observations)
        if point is None:continue
        asset=by_asset[item['asset_id']];offset=rotation(item['rotation_deg'])@(np.array(asset['bounds_center_m'])*np.array(item['scale']))
        position=point-offset
        if np.any(np.abs(position)>100):continue
        previous=item['position_m'];item['position_m']=[round(float(x),4) for x in position]
        fits.append(dict(object_key=item['key'],previous_position_m=previous,position_m=item['position_m'],method='calibrated_region_rays_with_outlier_rejection',observations=len(observations),limitation='Visible box centres approximate geometric centres; occlusion and depth remain uncertain.'))
    return output,fits


def region_centres(analysis,frames,segments):
    by_frame={frame['key']:frame for frame in frames};output=[]
    for item in analysis['objects']:
        observations=[]
        for box in item['view_boxes']:
            frame=by_frame[box['view_key']]
            if frame['calibration'] is None:continue
            selected=next((s['selection'] for s in segments if s['object_key']==item['key'] and s['view_key']==frame['key'] and s['selection']),None)
            observations.append((frame['calibration'],selected['bbox_xyxy'] if selected else box['bbox_xyxy'],frame['model_size'][0]/frame['model_size'][1]))
        point=robust_triangulate(observations)
        if point is not None:output.append(dict(object_key=item['key'],approximate_visible_centre_world_m=[round(float(v),4) for v in point],source='calibrated image-region rays, not engine object transforms',limitation='Visible box centre is not necessarily the mesh centre; occlusion can bias this estimate.'))
    return output


def size_evidence(group,frames,segments):
    observed=dict(objects=[dict(key=group['object_key'],view_boxes=group['reference_boxes'])])
    centres=region_centres(observed,frames,segments)
    if not centres:return []
    centre=np.array(centres[0]['approximate_visible_centre_world_m']);by_frame={frame['key']:frame for frame in frames};scores=[]
    for asset in group['candidates']:
        size=np.array(asset['bounds_size_m']);best=float('inf')
        for yaw in [0,45,90,135]:
            corners=np.array([[x,y,z] for x in [-.5,.5] for y in [-.5,.5] for z in [-.5,.5]])*size
            points=corners@rotation([0,yaw,0]).T+centre;errors=[]
            for item in group['reference_boxes']:
                frame=by_frame[item['view_key']];view=frame['calibration']
                if view is None:continue
                p=(points-np.array(view['position_m']))@rotation(view['rotation_deg'])
                if np.any(p[:,2]<=.05):continue
                t=math.tan(math.radians(view['fov_deg'])/2);aspect=frame['model_size'][0]/frame['model_size'][1]
                uv=np.column_stack([.5+p[:,0]/p[:,2]/(2*t*aspect),.5-p[:,1]/p[:,2]/(2*t)])
                predicted=uv.max(axis=0)-uv.min(axis=0)
                selected=next((s['selection'] for s in segments if s['object_key']==group['object_key'] and s['view_key']==frame['key'] and s['selection']),None)
                box=selected['bbox_xyxy'] if selected else item['bbox_xyxy'];measured=np.array([box[2]-box[0],box[3]-box[1]])
                errors.append(float(np.abs(predicted-measured).mean()))
            if errors:best=min(best,float(np.mean(errors)))
        if np.isfinite(best):scores.append(dict(asset_id=asset['asset_id'],unit_scale_bbox_extent_error=round(best,5),limitation='Approximate projected intrinsic bounds at scale 1; occlusion and non-default asset scaling remain possible.'))
    return sorted(scores,key=lambda item:item['unit_scale_bbox_extent_error'])


def project_points(points,view,size):
    """Unity +Z forward, Y up; image coordinates have Y down. No clipping."""
    points=np.asarray(points,dtype=float)
    p=(points-np.asarray(view['position_m'],dtype=float))@rotation(view['rotation_deg'])
    w,h=size;t=math.tan(math.radians(view['fov_deg'])/2)
    safe=np.where(np.abs(p[:,2])>1e-12,p[:,2],np.nan)
    uv=np.column_stack([(0.5+p[:,0]/safe/(2*t*w/h))*w,(0.5-p[:,1]/safe/(2*t))*h])
    return uv,p[:,2]


def native_pose_precision(plan):
    """Explicit 1e-12 pose serialization, below the strict scene tolerances.

    Remove matrix cancellation residue before hashing, not during validation.
    The rounded proposal and its actual post-contact result remain separate.
    """
    from copy import deepcopy
    result=deepcopy(plan)
    for item in result['objects']:
        for field in ['position_m','rotation_deg','scale']:
            item[field]=[round(float(v),12)+0.0 for v in item[field]]
    return result


def orient_empty_estimated_views(plan, catalogue):
    """Repair only inferred cameras facing away from all candidate centres.

    Uses candidate bounds, never source scene poses. Recorded views are untouched.
    """
    from copy import deepcopy
    views = plan.get('estimated_views')
    if not views:
        return plan, []
    assets = {a['asset_id']: a for a in catalogue}
    centres = []
    for item in plan['objects']:
        centre = assets.get(item.get('asset_id'), {}).get('bounds_center_m', [0, 0, 0])
        centres.append(np.asarray(item['position_m']) + rotation(item['rotation_deg']) @ (np.asarray(centre) * item['scale']))
    if not centres:
        return plan, []
    points = np.asarray(centres)
    target = (points.min(axis=0) + points.max(axis=0)) / 2
    result = deepcopy(plan)
    fixes = []
    for view in result['estimated_views']:
        eye = np.asarray(view['position_m'])
        forward = rotation(view['rotation_deg'])[:, 2]
        if np.any((points-eye) @ forward > .01):
            continue
        direction = target-eye
        if np.linalg.norm(direction) < .01:
            continue
        before = list(view['rotation_deg'])
        horizontal = math.hypot(direction[0], direction[2])
        view['rotation_deg'] = [-math.degrees(math.atan2(direction[1], horizontal)), math.degrees(math.atan2(direction[0], direction[2])) if horizontal > 1e-6 else before[1], 0.]
        fixes.append(dict(method='empty_estimated_view_orientation', view_key=view['key'], before_rotation_deg=before, after_rotation_deg=view['rotation_deg'], source_transforms_used=False))
    return result, fixes
