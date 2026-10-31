"""Image-space multi-room layout constraints, independent of Unity source poses.

Coordinates are normalized image pixels (u right, v down). Metric scale is a
separate explicit estimate. This is a rectangular-plan solver, not depth recovery.
"""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
from .domain import AgentError, payload, fingerprint


def area(box):return max(0.,box[2]-box[0])*max(0.,box[3]-box[1])
def overlap(a,b):return area([max(a[0],b[0]),max(a[1],b[1]),min(a[2],b[2]),min(a[3],b[3])])
def rect(p):return [p[0]-p[2]/2,p[1]-p[3]/2,p[0]+p[2]/2,p[1]+p[3]/2]
def pose(b):return [(b[0]+b[2])/2,(b[1]+b[3])/2,b[2]-b[0],b[3]-b[1]]


def wall_id(wall):return wall.get('segment_key',wall['object_key'])


def validate_observation(ir,object_keys):
    reviewed=deepcopy(ir)
    for wall in reviewed['walls']:wall.setdefault('segment_key',wall['object_key'])
    payload('ModelFloorplanObservation',reviewed)
    if ir['projection']!='overhead_cutaway':raise AgentError('UNSUPPORTED_PROJECTION','The composition solver requires an overhead cutaway reference')
    rooms={r['key']:r['bounds'] for r in ir['rooms']};walls={wall_id(w):w for w in ir['walls']}
    if len(rooms)!=len(ir['rooms']):raise AgentError('INVALID_TOPOLOGY','Room keys must be unique')
    if len(walls)!=len(ir['walls']):raise AgentError('INVALID_TOPOLOGY','Wall segment_key values must be unique; object_key may repeat to reuse a prefab')
    boxes=[ir['envelope']]+list(rooms.values())+[o['bounds'] for o in ir['objects']]
    if any(area(b)<=1e-7 for b in boxes):raise AgentError('INVALID_TOPOLOGY','Empty room or object footprint')
    for key,b in rooms.items():
        if area(b)-overlap(b,ir['envelope'])>1e-5:raise AgentError('INVALID_TOPOLOGY','Room escapes the envelope')
        if any(overlap(b,c)>1e-5 for other,c in rooms.items() if other!=key):raise AgentError('INVALID_TOPOLOGY','Room interiors overlap')
    for w in walls.values():
        if w['object_key'] not in object_keys or len(set(w['rooms']))!=len(w['rooms']) or any(r not in rooms for r in w['rooms']):raise AgentError('INVALID_TOPOLOGY','Wall must bind existing objects and rooms')
        delta=np.abs(np.array(w['end'])-w['start'])
        if max(delta)<.005 or min(delta)>.005:raise AgentError('INVALID_TOPOLOGY','Only non-empty axis-aligned walls are supported')
    for wall in walls.values():
        a,b=np.array(wall['start']),np.array(wall['end']);horizontal=abs(b[0]-a[0])>abs(b[1]-a[1]);axis=1 if horizontal else 0
        line=(a[axis]+b[axis])/2;sides=[]
        for room_key in wall['rooms']:
            bounds=rooms[room_key];lo,hi=bounds[axis],bounds[axis+2]
            # Wall thickness is excluded from room interiors; allow a small gap.
            if min(abs(line-lo),abs(line-hi))>.05:raise AgentError('INVALID_TOPOLOGY','Wall is not adjacent to its room boundary')
            sides.append(np.sign((lo+hi)/2-line))
        if len(sides)==2 and sides[0]*sides[1]>=0:raise AgentError('INVALID_TOPOLOGY','Shared wall must separate its two rooms')
    if len({o['key'] for o in ir['openings']})!=len(ir['openings']):raise AgentError('INVALID_TOPOLOGY','Duplicate opening')
    for o in ir['openings']:
        if o['wall_key'] not in walls or o['start']>=o['end']:raise AgentError('INVALID_TOPOLOGY','Opening is not bound to a valid wall interval')
    for i,a in enumerate(ir['openings']):
        for b in ir['openings'][i+1:]:
            if a['wall_key']==b['wall_key'] and min(a['end'],b['end'])>max(a['start'],b['start']):raise AgentError('INVALID_TOPOLOGY','Openings overlap on a wall')
    seen=set()
    for o in ir['objects']:
        if o['object_key'] not in object_keys or o['object_key'] in seen or (o['room_key'] is not None and o['room_key'] not in rooms):raise AgentError('INVALID_TOPOLOGY','Object has no unique source or room binding')
        seen.add(o['object_key'])
        if o['role'] in {'furniture','rug','supported'} and o['room_key'] is None:raise AgentError('INVALID_TOPOLOGY','Furniture must belong to a room')
    return ir


def door_zones(ir):
    walls={wall_id(w):w for w in ir['walls']};zones=[]
    for opening in ir['openings']:
        if opening['kind']!='door':continue
        w=walls[opening['wall_key']];a=np.array(w['start']);d=np.array(w['end'])-a
        p=a+d*opening['start'];q=a+d*opening['end'];depth=max(.025,min(.10,float(np.linalg.norm(q-p))*.7))
        zones.append([float(min(p[0],q[0])- (depth if abs(d[0])<.005 else 0)),float(min(p[1],q[1])-(depth if abs(d[1])<.005 else 0)),float(max(p[0],q[0])+(depth if abs(d[0])<.005 else 0)),float(max(p[1],q[1])+(depth if abs(d[1])<.005 else 0))])
    return zones


def objective(ir,poses):
    rooms={r['key']:r['bounds'] for r in ir['rooms']};obs=[o for o in ir['objects'] if o['role'] in {'furniture','rug','supported'}];zones=door_zones(ir)
    result=dict(reprojection=0.,outside_room=0.,collisions=0.,door_clearance=0.)
    for o in obs:
        p=np.array(poses[o['object_key']]);target=np.array(pose(o['bounds']));b=rect(p)
        result['reprojection']+=float(np.square(p-target).sum())*max(.1,o['confidence'])
        result['outside_room']+=max(0.,area(b)-overlap(b,rooms[o['room_key']]))
        if o['role']=='furniture':result['door_clearance']+=sum(overlap(b,z) for z in zones)
    solid=[o for o in obs if o['role']=='furniture']
    for i,a in enumerate(solid):
        for b in solid[i+1:]:
            if a['room_key']==b['room_key']:result['collisions']+=overlap(rect(poses[a['object_key']]),rect(poses[b['object_key']]))
    result['loss']=result['reprojection']+20*(result['outside_room']+result['collisions']+result['door_clearance'])
    return result


def optimize(ir,initial=None,guard=None):
    targets={o['object_key']:pose(o['bounds']) for o in ir['objects'] if o['role'] in {'furniture','rug','supported'}}
    if not targets:return dict(poses={},metrics=objective(ir,{}),history=[],method='image_space_coordinate_descent')
    initial={k:list((initial or {}).get(k,v)) for k,v in targets.items()};starts=[initial,deepcopy(targets)]
    rng=np.random.default_rng(17)
    for _ in range(2):starts.append({k:[v[0]+float(rng.uniform(-.04,.04)),v[1]+float(rng.uniform(-.04,.04)),v[2],v[3]] for k,v in targets.items()})
    best=deepcopy(initial);score=objective(ir,best);history=[dict(loss=score['loss'],source='initial')]
    for index,start in enumerate(starts):
        current=deepcopy(start);value=objective(ir,current)
        for step in [.04,.02,.01,.005,.002,.001]:
            for sweep in range(8):
                if guard:guard()
                changed=False
                for key in current:
                    for axis in range(4):
                        for direction in [-1,1]:
                            trial=deepcopy(current);trial[key][axis]+=direction*step
                            if axis>=2 and not .7*targets[key][axis]<=trial[key][axis]<=1.3*targets[key][axis]:continue
                            candidate=objective(ir,trial)
                            if candidate['loss']<value['loss']-1e-12:current,value=trial,candidate;changed=True
                if not changed:break
        if value['loss']<score['loss']:
            best,score=current,value;history.append(dict(loss=score['loss'],source=f'start-{index}'))
    return dict(poses=best,metrics=score,history=history,method='image_space_coordinate_descent',source_transforms_used=False)


def checkpoint(path,state=None,*,evidence_hash=None):
    path=Path(path)
    if state is not None:
        temporary=path.with_suffix('.writing');temporary.write_text(json.dumps(state,allow_nan=False));temporary.replace(path);return state
    value=json.loads(path.read_text())
    if value.get('evidence_hash')!=evidence_hash:raise AgentError('STALE_EVIDENCE','Checkpoint belongs to different reference evidence')
    return value


def extract(provider,artifacts,frames,analysis,catalogue,segments,brief,*,on_response=None,guard=None):
    from .providers.meta_responses import spark_request
    from .domain import canonical
    if len(frames)!=1:raise AgentError('UNSUPPORTED_PROJECTION','First composition release accepts one overhead image')
    assets={a['asset_id']:a for a in catalogue}
    objects=[dict(o,asset_name=assets.get(o['asset_id'],{}).get('name')) for o in analysis['objects']]
    context=dict(brief=brief,objects=objects,segmentation=[dict(object_key=s['object_key'],bbox=s.get('selection',{}).get('bbox_xyxy') if s.get('selection') else None) for s in segments])
    instruction='Extract a normalized 2D architectural layout from this overhead cutaway drawing. Coordinates u right, v down, normalized to the WHOLE supplied image. Return unsupported for non-plan perspective photographs. Rooms are disjoint axis-aligned rectangular interior footprints, excluding wall thickness, within envelope. Include every supplied object_key exactly once in objects; use no new object keys. Exclude drawn text labels from geometry. Furniture bounds describe footprint rather than shadow. Choose cardinal Unity yaw (0 faces image top, 90 faces image right) from visible evidence; room keys are your IDs. Walls reference actual supplied structural object keys and image start/end centreline points; assign one room for perimeter walls, two for partitions. Openings are ordered fractional intervals ALONG a wall from its start toward end; door denotes a passage, window denotes glazing. Do not invent unseen doors. A floor may cover several rooms: its room_key can be null. Rugs are rug, table-supported small objects are supported. Ceilings may exist but are hidden in this cutaway reference; use room or envelope bounds and role ceiling. For openings with separate door-leaf objects use role opening and visible bounds. Keep uncertainty in limits. Do not copy source world poses or metric dimensions.'
    instruction+=' Each wall has a globally unique segment_key, separate from object_key. object_key binds an existing structural object/prefab and MAY repeat across distinct segments. Every opening.wall_key MUST equal exactly one wall.segment_key; never invent an unmatched alias. A segment touching more than two rooms must be split into uniquely named segments. Room keys and opening keys must also be unique.'
    prompt=instruction+'\nReference metadata:\n'+canonical(context)
    seen=set();repairs=[]
    while True:
        if guard:guard()
        response=provider.send(spark_request(prompt,[artifacts.read(frames[0]['artifact_hash'])],'ModelFloorplanObservation'),'ModelFloorplanObservation')
        if on_response:on_response(response,None)
        try:
            ir=validate_observation(response['value'],{o['key'] for o in analysis['objects']})
            if {o['object_key'] for o in ir['objects']}!={o['key'] for o in analysis['objects']}:raise AgentError('INVALID_TOPOLOGY','Every selected object requires a floorplan observation')
            response['topology_repairs']=repairs
            return response
        except AgentError as error:
            if error.code!='INVALID_TOPOLOGY':raise
            if on_response:on_response(response,str(error))
            rejected=fingerprint(response['value'])
            if rejected in seen:raise AgentError('INVALID_TOPOLOGY','Repeated invalid topology with no correction: '+str(error))
            seen.add(rejected);repairs.append(dict(call_id=response.get('call_id'),reason=str(error)))
            prompt=instruction+'\nReference metadata:\n'+canonical(context)+'\nCorrect this completed but invalid extraction. Keep physical segments; repair their IDs, bindings and topology. Return the entire corrected observation. Validation error: '+str(error)+'\nRejected observation:\n'+canonical(response['value'])


def build_plan(ir,fit,analysis,catalogue,frame):
    """Compile image-space constraints to connected-prefab poses and a fixed camera."""
    import math
    from .reference_geometry import rotation
    from .native_layout import fit_functional_layout
    source_observed={o['object_key']:deepcopy(o) for o in ir['objects']}
    ir,width,height,fit=fit_functional_layout(ir,analysis,catalogue,frame['model_size'][0]/frame['model_size'][1])
    assets={a['asset_id']:a for a in catalogue};identified={o['key']:o for o in analysis['objects']};observed={o['object_key']:o for o in ir['objects']};walls={w['object_key']:w for w in ir['walls']};rooms={r['key']:r['bounds'] for r in ir['rooms']}
    wall_height=2.8 # Coherent interior modules and ceiling underside.
    def world(u,v):return [(u-.5)*width,(.5-v)*height]
    objects=[]
    for source in analysis['objects']:
        key=source['key'];o=observed[key];asset=assets[source['asset_id']];size=np.asarray(asset['bounds_size_m'],float);offset=np.asarray(asset['bounds_center_m'],float)
        b=rect(fit['poses'][key]) if key in fit['poses'] else o['bounds']
        if o['role']=='floor' and o['room_key']:b=room_floor_bounds(ir,o['room_key'])
        if o['role']=='ceiling' and walls:
            endpoints=[p for wall in walls.values() for p in (wall['start'],wall['end'])]
            b=[min(p[0] for p in endpoints),min(p[1] for p in endpoints),max(p[0] for p in endpoints),max(p[1] for p in endpoints)]
        u,v,w,h=pose(b);yaw=o['yaw_deg'];y=0.
        if key in walls:
            wall=walls[key];start,end=np.array(wall['start']),np.array(wall['end']);u,v=(start+end)/2
            horizontal=abs(end[0]-start[0])>abs(end[1]-start[1])
            room=pose(rooms[wall['rooms'][0]]);yaw=(0 if v<room[1] else 180) if horizontal else (270 if u<room[0] else 90)
        else:
            if o['role']=='ceiling':y=wall_height
        scale=[1.,1.,1.]
        r=rotation([0,yaw,0]);shift=r@(offset*scale);x,z=world(u,v)
        # Resolve ground height from local bounds, then let native contacts establish actual support.
        pos=[float(x-shift[0]),float(y+(size[1]/2-offset[1])*scale[1]),float(z-shift[2])]
        objects.append(dict(key=key,asset_id=source['asset_id'],primitive=None,position_m=pos,rotation_deg=[0.,float(yaw),0.],scale=scale,base_color_rgba=None))
    by_key={o['key']:o for o in objects}
    for source in analysis['objects']:
        key=source['key'];support=source['support_key']
        if observed[key]['role']=='supported' and support in by_key:
            a=assets[by_key[support]['asset_id']];by_key[key]['position_m'][1]+=by_key[support]['position_m'][1]+(a['bounds_center_m'][1]+a['bounds_size_m'][1]/2)*by_key[support]['scale'][1]
            parent=by_key[support];child=by_key[key];own=assets[child['asset_id']]
            pr=rotation(parent['rotation_deg']);cr=rotation(child['rotation_deg'])
            pc=np.array(parent['position_m'])+pr@(np.array(a['bounds_center_m'])*parent['scale'])
            cc=np.array(child['position_m'])+cr@(np.array(own['bounds_center_m'])*child['scale'])
            ph=np.abs(pr)@(np.array(a['bounds_size_m'])*parent['scale'])/2
            ch=np.abs(cr)@(np.array(own['bounds_size_m'])*child['scale'])/2
            # Preserve relative placement on a moved support, rather than leaving
            # a plate/TV at the nearest edge after furniture was rearranged.
            original_child=pose(source_observed[key]['bounds']);original_parent=pose(source_observed[support]['bounds'])
            desired=pc.copy()
            for image_axis,world_axis in ((0,0),(1,2)):
                fraction=(original_child[image_axis]-original_parent[image_axis])/max(1e-6,original_parent[image_axis+2])
                desired[world_axis]+=fraction*2*ph[world_axis]*(1 if world_axis==0 else -1)
            # Native feet decide the final vertical contact.
            for axis in (0,2):
                margin=min(ch[axis],ph[axis]*.8)
                corrected=float(np.clip(desired[axis],pc[axis]-ph[axis]+margin,pc[axis]+ph[axis]-margin))
                child['position_m'][axis]+=corrected-cc[axis]

    # Persist the assembled target separately from the original reference evidence.
    for obj in objects:
        observed_obj=observed[obj['key']]
        if observed_obj['role'] not in {'furniture','rug','supported'}:continue
        asset=assets[obj['asset_id']];rot=rotation(obj['rotation_deg'])
        centre=np.array(obj['position_m'])+rot@np.array(asset['bounds_center_m'])
        extent=np.abs(rot)@np.array(asset['bounds_size_m'])/2
        observed_obj['bounds']=[float(.5+(centre[0]-extent[0])/width),float(.5-(centre[2]+extent[2])/height),float(.5+(centre[0]+extent[0])/width),float(.5-(centre[2]-extent[2])/height)]

    camera_height=40.;fov=float(math.degrees(2*math.atan(height/(2*camera_height))))
    plan=dict(objects=objects,lights=[dict(type='directional',position_m=[0.,8.,0.],rotation_deg=[45.,45.,0.],intensity=700.,color_rgb=[1.,.98,.95],spot_angle_deg=90.)],estimated_views=[dict(key=frame['key'],position_m=[0.,camera_height,0.],rotation_deg=[90.,0.,0.],fov_deg=max(5.,fov))],exposure_ev=8.,sky_color_rgb=[.5,.5,.5],fog_mean_free_path_m=None,notes=['Image-space constrained composition; room dimensions snapped to whole native modules, not observed depth.','Ceilings remain in the scene and are excluded only from the explicit cutaway capture.'])
    plan['lights'] += [dict(type='directional',position_m=[0.,8.,0.],rotation_deg=[float(pitch),float(yaw),0.],intensity=float(lux),color_rgb=[1.,1.,1.],spot_angle_deg=90.) for pitch,yaw,lux in ((45,225,700),(-45,135,450),(-45,315,450))]
    camera=dict(width=frame['model_size'][0],height=frame['model_size'][1],orthographic_size=height/2,cutaway=True,object_keys=[o['key'] for o in objects],ceiling_keys=[o['object_key'] for o in ir['objects'] if o['role']=='ceiling'])
    return plan,dict(schema_version='1.0',camera=camera,screen_width_m=width,screen_height_m=height,scale_estimated=True,architecture=native_architecture(ir,width,height),layout_policy='native_prefab_assembly',layout_observation=ir,roles={o['object_key']:o['role'] for o in ir['objects']},solver=fit)


def room_floor_bounds(ir, room_key):
    """Extend visible floor to wall centrelines, including occluded perimeter strips."""
    room=next(r['bounds'] for r in ir['rooms'] if r['key']==room_key)
    result=list(room);cx,cy,_,_=pose(room)
    for wall in ir['walls']:
        if room_key not in wall['rooms']:continue
        a,b=wall['start'],wall['end']
        if abs(a[1]-b[1])<.005:
            result[1 if a[1]<cy else 3]=(a[1]+b[1])/2
        else:result[0 if a[0]<cx else 2]=(a[0]+b[0])/2
    return result


def measure_native(ir, proof):
    """Measure actual Unity bounds; apertures/silhouettes remain separate evidence.

    This deliberately cannot certify composition from bounding boxes alone.
    """
    observed={p['object_key']:p['bbox_xyxy'] for p in proof['projected_objects']}
    keys={o['object_key'] for o in ir['objects'] if o['role'] in {'furniture','rug','supported'}}
    missing=sorted(keys-observed.keys());rows={}
    for o in ir['objects']:
        key=o['object_key']
        if key not in keys or key not in observed:continue
        actual=observed[key];target=o['bounds'];union=area(actual)+area(target)-overlap(actual,target)
        rows[key]=dict(actual_bounds=actual,target_bounds=target,iou=overlap(actual,target)/max(1e-12,union),max_edge_error=max(abs(a-b) for a,b in zip(actual,target)),clipped=any(v<0 or v>1 for v in actual))
    values=objective(ir,{k:pose(observed[k]) for k in keys}) if not missing else None
    return dict(method='native_projected_bounds',version=proof['version'],coverage_complete=not missing,missing_objects=missing,per_object=rows,objective=values,bounds_admissible=not missing and all(r['max_edge_error']<=.01 and not r['clipped'] for r in rows.values()) and all(values[k]<1e-5 for k in ('outside_room','collisions','door_clearance')),composition_qualified=False,unverified=['wall_aperture_geometry','visible_silhouette_match','asset_identity','hidden_surfaces'])


def correct_native(plan, composition, measurement, catalogue):
    """Translate measured residuals; never deform furniture to match a rectangle."""
    if composition.get('layout_policy')=='native_prefab_assembly':return None
    if not measurement['coverage_complete']:return None
    result=deepcopy(plan);changed=False
    for obj in result['objects']:
        if composition.get('roles',{}).get(obj['key'])=='supported':continue
        row=measurement['per_object'].get(obj['key'])
        if not row or row['max_edge_error']<=.002:continue
        before=pose(row['actual_bounds']);target=pose(row['target_bounds'])
        delta=[target[i]-before[i] for i in (0,1)]
        if max(abs(v) for v in delta)<1e-5:continue
        obj['position_m'][0]+=delta[0]*composition['screen_width_m']
        obj['position_m'][2]-=delta[1]*composition['screen_height_m']
        changed=True
    return result if changed else None


def composition_rank(metrics):
    m=metrics['composition'];obj=m['objective']
    return (not m['coverage_complete'],not m.get('circulation',{'passed':True})['passed'],not metrics['contacts']['passed'],not m.get('structural_admissible',False),not m['bounds_admissible'],obj['loss'] if obj else float('inf'))


def architecture(ir,width,height):
    """Snap adjacent wall joints and describe apertures independently of wall prefabs."""
    walls=deepcopy(ir['walls'])
    for axis in (0,1):
        lines=[w for w in walls if abs(w['start'][axis]-w['end'][axis])<.005]
        for wall in walls:
            for endpoint in ('start','end'):
                near=[(w['start'][axis]+w['end'][axis])/2 for w in lines if abs(wall[endpoint][axis]-(w['start'][axis]+w['end'][axis])/2)<.015]
                if near:wall[endpoint][axis]=float(np.mean(near))
    result=[]
    for w in walls:
        start=[(w['start'][0]-.5)*width,0.,(.5-w['start'][1])*height]
        end=[(w['end'][0]-.5)*width,0.,(.5-w['end'][1])*height]
        room_center=pose(next(r['bounds'] for r in ir['rooms'] if r['key']==w['rooms'][0]))
        horizontal=abs(w['start'][1]-w['end'][1])<.005
        yaw=(0 if w['start'][1]<room_center[1] else 180) if horizontal else (270 if w['start'][0]<room_center[0] else 90)
        result.append(dict(object_key=w['object_key'],segment_key=wall_id(w),rotation_deg=[0.,float(yaw),0.],start_m=start,end_m=end,partition=len(w['rooms'])==2,openings=[dict(key=o['key'],kind=o['kind'],start=o['start'],end=o['end']) for o in ir['openings'] if o['wall_key']==wall_id(w)]))
    return dict(walls=result,height_m=2.8,thickness_m=.2,lighting='neutral_construction')


def native_architecture(ir,width,height):
    result=architecture(ir,width,height)
    surfaces=[]
    for obj in ir['objects']:
        if obj['role'] not in {'floor','ceiling'}:continue
        rooms=[r for r in ir['rooms'] if obj['room_key'] is None or r['key']==obj['room_key']]
        for room in rooms:
            b=room_floor_bounds(ir,room['key'])
            surfaces.append(dict(object_key=obj['object_key'],kind=obj['role'],min_m=[(b[0]-.5)*width,(.5-b[3])*height],size_m=[(b[2]-b[0])*width,(b[3]-b[1])*height]))
    result['surfaces']=surfaces
    return result
