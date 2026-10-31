"""Image-derived initialization for explicit overhead room plans.

Metric scale remains an estimate; SAM regions are image measurements, not depth.
"""
from copy import deepcopy
import math
import numpy as np
from .reference_geometry import rotation


def fit_overhead_plan(plan, analysis, frames, catalogue, segments):
    if len(frames)!=1 or frames[0].get('calibration') is not None:
        return plan, []
    assets={a['asset_id']:a for a in catalogue}
    items={o['key']:o for o in analysis['objects']}
    floors=[o for o in plan['objects'] if assets.get(o.get('asset_id'),{}).get('name','').startswith('Floor_')]
    if len(floors)!=1:return plan, []
    def box(key):
        segment=next((s.get('selection') for s in segments if s['object_key']==key and s['view_key']==frames[0]['key'] and s.get('selection')),None)
        if segment:return segment['bbox_xyxy']
        return next((b['bbox_xyxy'] for b in items[key]['view_boxes'] if b['view_key']==frames[0]['key']),None)
    f=floors[0];fb=box(f['key'])
    if not fb or fb[2]-fb[0]<.3 or fb[3]-fb[1]<.3:return plan, []
    if abs(f['rotation_deg'][1])>.01:return plan, []
    result=deepcopy(plan);objects={o['key']:o for o in result['objects']};floor=objects[f['key']];asset=assets[f['asset_id']]
    aspect=frames[0]['model_size'][0]/frames[0]['model_size'][1]
    width=asset['bounds_size_m'][0]*floor['scale'][0]
    screen_width=width/(fb[2]-fb[0]);screen_height=screen_width/aspect
    centre=np.asarray(floor['position_m'])+np.asarray(asset['bounds_center_m'])*floor['scale']
    floor['scale'][2]=screen_height*(fb[3]-fb[1])/asset['bounds_size_m'][2]
    floor['position_m']=(centre-np.asarray(asset['bounds_center_m'])*floor['scale']).tolist()
    # A narrow-FOV perspective approximates the drawing without changing camera schema.
    height=min(70.,screen_height/(2*math.tan(math.radians(10)/2)))
    fov=max(10.,math.degrees(2*math.atan(screen_height/(2*height))))
    camera=[float(centre[0]-((fb[0]+fb[2])/2-.5)*screen_width),float(centre[1]+height),float(centre[2]+((fb[1]+fb[3])/2-.5)*screen_height)]
    result['estimated_views']=[dict(key=frames[0]['key'],position_m=camera,rotation_deg=[90.,0.,0.],fov_deg=fov)]
    changed=[]
    # Semantic facing for seating/TV comes from their relationship, not copied room poses.
    sofa=next((o for o in result['objects'] if assets[o['asset_id']]['name'].startswith('Sofa_')),None)
    tv=next((o for o in result['objects'] if assets[o['asset_id']]['name'].startswith('TV_')),None)
    if sofa and tv and box(sofa['key']) and box(tv['key']):
        a,b=box(sofa['key']),box(tv['key']);dx=(b[0]+b[2]-a[0]-a[2])*aspect;dz=-(b[1]+b[3]-a[1]-a[3])
        yaw=round(math.degrees(math.atan2(dx,dz))/90)*90
        sofa['rotation_deg']=[0.,float(yaw),0.];tv['rotation_deg']=[0.,float((yaw+180)%360),0.]
    for obj in result['objects']:
        asset=assets[obj['asset_id']];b=box(obj['key'])
        if not b or asset['name'].startswith(('Floor_','Wall')):continue
        r=rotation(obj['rotation_deg']);size=np.asarray(asset['bounds_size_m']);offset=np.asarray(asset['bounds_center_m'])
        old_centre=np.asarray(obj['position_m'])+r@(offset*obj['scale'])
        perspective=max(.8,(camera[1]-old_centre[1])/height)
        target=np.array([(b[2]-b[0])*screen_width*perspective,(b[3]-b[1])*screen_height*perspective])
        # Solve planar scale from rotated intrinsic bounds. Leave vertical size estimated.
        footprint=np.abs(r)[np.ix_([0,2],[0,2])]*size[[0,2]][None,:]
        if abs(np.linalg.det(footprint))>.001:
            scales=np.linalg.solve(footprint,target)
            if np.all((scales>=.2)&(scales<=6)):
                obj['scale'][0],obj['scale'][2]=map(float,scales)
                if asset['name'].startswith(('Interior_plant','Plate_','Pillow_')):obj['scale'][1]=float(math.sqrt(scales[0]*scales[1]))
        centre_x=camera[0]+((b[0]+b[2])/2-.5)*screen_width*perspective
        centre_z=camera[2]+(.5-(b[1]+b[3])/2)*screen_height*perspective
        shifted=r@(offset*obj['scale'])
        obj['position_m'][0]=float(centre_x-shifted[0]);obj['position_m'][2]=float(centre_z-shifted[2])
        changed.append(obj['key'])
    return result,[dict(method='overhead_image_regions',source_transforms_used=False,metric_dimensions_estimated=True,floor_region=fb,objects=changed,camera_fov_deg=fov)]


def luminance_stats(image, box):
    a=np.asarray(image.convert('RGB'),dtype=float)/255
    h,w=a.shape[:2];x0,y0,x1,y1=[round(v*d) for v,d in zip(box,[w,h,w,h])]
    a=a[max(0,y0):min(h,y1),max(0,x0):min(w,x1)]
    if not a.size:return None
    l=a@np.array([.2126,.7152,.0722])
    return dict(median=float(np.median(l)),bright_fraction=float((l>.97).mean()),dark_fraction=float((l<.035).mean()))


def exposure_probe(attempts):
    """Bracket EV against actual renders; freeze light geometry/intensity while probing."""
    if not attempts:return None
    last=attempts[-1];stats=last.get('metrics',{}).get('plan_photometry')
    if not stats:return None
    current,target=stats['candidate'],stats['reference'];ev=last['applied_plan']['exposure_ev']
    if abs(current['median']-target['median'])<.07 and current['bright_fraction']<target['bright_fraction']+.15:return None
    delta=2. if current['bright_fraction']>target['bright_fraction']+.15 else -2. if current['median']<.05 else float(np.clip(2.2*math.log2(max(.01,current['median'])/max(.01,target['median'])),-2,2))
    lights=last['applied_plan']['lights'];bright=[];dark=[]
    for attempt in attempts:
        s=attempt.get('metrics',{}).get('plan_photometry');p=attempt.get('applied_plan',{})
        if not s or p.get('lights')!=lights:continue
        (bright if s['candidate']['median']>s['reference']['median'] else dark).append(p['exposure_ev'])
    next_ev=(max(bright)+min(dark))/2 if bright and dark else ev+delta
    if abs(next_ev-ev)<.05:return None
    proposal=deepcopy(last['applied_plan']);proposal['exposure_ev']=float(np.clip(next_ev,-20,30))
    return proposal
