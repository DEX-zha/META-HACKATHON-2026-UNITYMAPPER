"""Fit rectangular reference topology to whole metre/three-metre pack modules.

Image dimensions are evidence of relative placement, never a licence to scale assets.
"""
from copy import deepcopy
import numpy as np
from .domain import AgentError
from .reference_geometry import rotation


def compile_grid(ir, analysis, catalogue, aspect, *, grow_x=0, grow_y=0, rotated_tiles=False):
    from .floorplan import architecture, room_floor_bounds, pose
    assets={a['asset_id']:a for a in catalogue}
    selected={o['key']:assets[o['asset_id']] for o in analysis['objects']}
    # Infer scale from furniture, not an arbitrarily selected floor tile.
    estimates=[]
    for o in ir['objects']:
        if o['role']!='furniture':continue
        size=np.abs(rotation([0,o['yaw_deg'],0]))@np.array(selected[o['object_key']]['bounds_size_m'])
        b=o['bounds']
        estimates.extend([size[0]/(b[2]-b[0]),size[2]*aspect/(b[3]-b[1])])
    width=float(np.clip(np.median(estimates) if estimates else 8.,4.,24.))
    height=width/aspect
    snapped=architecture(ir,width,height)
    axes=[]
    for axis,world_axis in ((0,0),(1,2)):
        values=sorted(set(round((p[world_axis]/width+.5) if axis==0 else (.5-p[world_axis]/height),5) for w in snapped['walls'] for p in (w['start_m'],w['end_m'])))
        # Include room bounds when a partial observation has no perimeter walls.
        if len(values)<2:
            values=sorted(set(r['bounds'][axis+i] for r in ir['rooms'] for i in (0,2)))
        unit=(3 if axis==0 else 1) if rotated_tiles else (1 if axis==0 else 3)
        metric=width if axis==0 else height
        lengths=[max(6 if axis==0 else 3,np.ceil((b-a)*metric/unit)*unit) if rotated_tiles else max(4 if axis==0 else 3,(np.ceil((b-a)*width) if axis==0 else round((b-a)*height/unit)*unit)) for a,b in zip(values,values[1:])]
        lengths=[v+(grow_x if axis==0 else grow_y)*unit for v in lengths]
        coords=np.r_[0,np.cumsum(lengths)].astype(float);coords-=coords[-1]/2
        axes.append((np.array(values),coords))
    # Keep a margin around the actual apartment in the fixed top capture.
    screen_w=max(np.ptp(axes[0][1])+1,(np.ptp(axes[1][1])+1)*aspect)
    screen_h=screen_w/aspect
    def mapped(value,axis):
        xs,ys=axes[axis]
        near=int(np.argmin(abs(xs-value)))
        metric=ys[near] if abs(xs[near]-value)<.025 else np.interp(value,xs,ys)
        return float(.5+metric/(screen_w if axis==0 else screen_h))
    out=deepcopy(ir)
    for room in out['rooms']:
        bounds=room_floor_bounds(ir,room['key'])
        room['bounds']=[mapped(v,i%2) for i,v in enumerate(bounds)]
    rooms={r['key']:r['bounds'] for r in out['rooms']}
    for wall in out['walls']:
        for endpoint in ('start','end'):wall[endpoint]=[mapped(v,i) for i,v in enumerate(wall[endpoint])]
    for o in out['objects']:
        asset=selected[o['object_key']]
        if asset.get('name','').startswith('Table_coffee'):
            source=o['bounds'];ratio=(source[2]-source[0])*aspect/(source[3]-source[1])
            def error(yaw):
                size=np.abs(rotation([0,yaw,0]))@np.array(asset['bounds_size_m'])
                return abs(np.log(size[0]/size[2]/ratio))
            if error((o['yaw_deg']+90)%360)<error(o['yaw_deg']):o['yaw_deg']=(o['yaw_deg']+90)%360
    original_objects={o['object_key']:o for o in ir['objects']}
    original_rooms={r['key']:r['bounds'] for r in ir['rooms']}
    for o in out['objects']:
        o['bounds']=[mapped(v,i%2) for i,v in enumerate(o['bounds'])]
        if o['role'] not in {'furniture','rug','supported','opening'}:continue
        size=np.abs(rotation([0,o['yaw_deg'],0]))@np.array(selected[o['object_key']]['bounds_size_m'])
        cx,cy,_,_=pose(o['bounds']);hx,hz=size[0]/screen_w/2,size[2]/screen_h/2
        if o['room_key'] and o['role']!='supported':
            b=rooms[o['room_key']];mx,mz=.12/screen_w,.12/screen_h
            if 2*hx+2*mx>b[2]-b[0] or 2*hz+2*mz>b[3]-b[1]:
                raise AgentError('NATIVE_LAYOUT_INCOMPATIBLE',f"Native prefab {o['object_key']} does not fit its room; select another prefab or enlarge the room")
            original=original_objects[o['object_key']]['bounds'];old_room=original_rooms[o['room_key']]
            if o['role']=='furniture':
                # Preserve observed wall attachment instead of floating furniture at
                # image-relative centres when a room needs additional walking space.
                for axis in (0,1):
                    low=(original[axis]-old_room[axis])/(old_room[axis+2]-old_room[axis])
                    high=(old_room[axis+2]-original[axis+2])/(old_room[axis+2]-old_room[axis])
                    if min(low,high)<.12:
                        half=(hx,hz)[axis];margin=(mx,mz)[axis]
                        value=b[axis]+half+margin if low<high else b[axis+2]-half-margin
                        if axis==0:cx=value
                        else:cy=value
            cx=float(np.clip(cx,b[0]+hx+mx,b[2]-hx-mx));cy=float(np.clip(cy,b[1]+hz+mz,b[3]-hz-mz))
        o['bounds']=[cx-hx,cy-hz,cx+hx,cy+hz]
    # Openings move with their complete 3 m module, never retain a pixel-sized gap.
    walls={w.get('segment_key',w['object_key']):w for w in out['walls']}
    for opening in out['openings']:
        wall=walls[opening['wall_key']];a=np.array(wall['start']);b=np.array(wall['end'])
        length=float(np.linalg.norm((b-a)*[screen_w,screen_h]))
        slot=float(np.clip(round((opening['start']+opening['end'])/2*length-1.5),0,length-3))
        half=.6
        opening['start']=(slot+1.5-half)/length;opening['end']=(slot+1.5+half)/length
    out['envelope']=[min(r['bounds'][i] for r in out['rooms']) if i<2 else max(r['bounds'][i] for r in out['rooms']) for i in range(4)]
    return out,float(screen_w),float(screen_h)


def arrange(ir,width,height,*,names=None,require_circulation=False):
    """Place native footprints without crossing walls, furniture or door clearances.

    Beam search retains alternatives rather than accepting a penetrated best-effort pose.
    This is conservative footprint clearance, not a mesh collision certificate.
    """
    from .floorplan import pose, rect, overlap, objective
    from .circulation import service_points, check, DOOR_DEPTH
    names=names or {}
    rooms={r['key']:r['bounds'] for r in ir['rooms']}
    walls={w.get('segment_key',w['object_key']):w for w in ir['walls']}
    doors=[]
    for o in ir['openings']:
        if o['kind']!='door':continue
        w=walls[o['wall_key']];a=np.array(w['start']);d=np.array(w['end'])-a
        p=a+d*o['start'];q=a+d*o['end']
        margin=np.array([DOOR_DEPTH/width,0]) if abs(d[0])<.005 else np.array([0,DOOR_DEPTH/height])
        doors.append([*(np.minimum(p,q)-margin),*(np.maximum(p,q)+margin)])
    solids=sorted((o for o in ir['objects'] if o['role']=='furniture'),key=lambda o:-(o['bounds'][2]-o['bounds'][0])*(o['bounds'][3]-o['bounds'][1]))
    def access(key,p):
        if not require_circulation:return []
        obj=next(o for o in solids if o['object_key']==key)
        return service_points(np.array(rect(p))*[width,height,width,height],obj['yaw_deg'],names.get(key,''))
    def blocks(p,point):
        box=np.array(rect(p))*[width,height,width,height];x,y=point
        return box[0]-.42<x<box[2]+.42 and box[1]-.42<y<box[3]+.42
    states=[(0.,{})]
    for o in solids:
        target=pose(o['bounds']);b=rooms[o['room_key']];hx,hz=target[2]/2,target[3]/2
        xs=np.unique(np.r_[np.linspace(b[0]+hx+.12/width,b[2]-hx-.12/width,max(2,int((b[2]-b[0])*width/.1))),target[0]])
        zs=np.unique(np.r_[np.linspace(b[1]+hz+.12/height,b[3]-hz-.12/height,max(2,int((b[3]-b[1])*height/.1))),target[1]])
        candidates=[]
        for x in xs:
            for z in zs:
                p=[float(x),float(z),target[2],target[3]];box=rect(p)
                if box[0]<b[0]+.1/width or box[2]>b[2]-.1/width or box[1]<b[1]+.1/height or box[3]>b[3]-.1/height:continue
                if any(overlap(box,d)>1e-9 for d in doors):continue
                if require_circulation:
                    points=access(o['object_key'],p)
                    if any(not(b[0]*width+.48<=px<=b[2]*width-.48 and b[1]*height+.48<=py<=b[3]*height-.48) for px,py in points):continue
                candidates.append((((x-target[0])*width)**2+((z-target[1])*height)**2,p))
        candidates.sort(key=lambda c:c[0]);next_states=[]
        for cost,placed in states:
            accepted=0
            for delta,p in candidates:
                box=rect(p);padded=[box[0]-.04/width,box[1]-.04/height,box[2]+.04/width,box[3]+.04/height]
                if any(overlap(padded,rect(other))>1e-9 for other in placed.values()):continue
                if require_circulation and any(any(blocks(other,point) for point in access(o['object_key'],p)) or any(blocks(p,point) for point in access(key,other)) for key,other in placed.items()):continue
                next_states.append((cost+delta,dict(placed,**{o['object_key']:p})));accepted+=1
                if accepted>=64:break
        if not next_states:raise AgentError('NATIVE_LAYOUT_INCOMPATIBLE',f"No collision-free native placement for {o['object_key']}; room or asset selection must change")
        states=sorted(next_states,key=lambda x:x[0])[:128]
    poses={o['object_key']:pose(o['bounds']) for o in ir['objects'] if o['role'] in {'furniture','rug','supported'}}
    circulation=None
    if require_circulation:
        for _,placed in states:
            trial=dict(poses,**placed);report=check(ir,trial,width,height,names)
            if report['passed']:poses=trial;circulation=report;break
        if circulation is None:raise AgentError('NATIVE_LAYOUT_INCOMPATIBLE','No 80 cm route to: '+', '.join(sorted({key for room in report['rooms'] for key in room.get('unreachable',[])})))
    else:poses.update(states[0][1])
    return dict(circulation=circulation,poses=poses,metrics=objective(ir,poses),history=[],method='native_footprint_clearance_search',source_transforms_used=False,door_clearance_m=DOOR_DEPTH)


def fit_functional_layout(ir,analysis,catalogue,aspect):
    """Try progressively larger whole-module layouts; never shrink furniture."""
    assets={a['asset_id']:a for a in catalogue}
    names={o['key']:assets[o['asset_id']].get('name','') for o in analysis['objects']}
    candidates=[];failures=[]
    for rotated in (False,True):
        for gx in range(4):
            for gy in range(3):
                try:
                    grid,w,h=compile_grid(ir,analysis,catalogue,aspect,grow_x=gx,grow_y=gy,rotated_tiles=rotated)
                    area=sum((r['bounds'][2]-r['bounds'][0])*w*(r['bounds'][3]-r['bounds'][1])*h for r in grid['rooms'])
                    candidates.append((area,gx,gy,rotated,grid,w,h))
                except AgentError as error:
                    if error.code!='NATIVE_LAYOUT_INCOMPATIBLE':raise
    for _,gx,gy,rotated,grid,w,h in sorted(candidates,key=lambda c:c[0]):
        try:
            fit=arrange(grid,w,h,names=names,require_circulation=True)
            fit=harmonize_seating(grid,fit,w,h,names,analysis)
            fit['rejected_layouts']=failures;fit['module_growth']=dict(width_steps=gx,depth_steps=gy,rotated_tiles=rotated)
            return grid,w,h,fit
        except AgentError as error:
            if error.code!='NATIVE_LAYOUT_INCOMPATIBLE':raise
            failures.append(dict(grow_x=gx,grow_y=gy,rotated_tiles=rotated,reason=str(error)))
    raise AgentError('NATIVE_LAYOUT_INCOMPATIBLE','No functional whole-module layout found; revise room topology or asset selection')


def harmonize_seating(ir,fit,width,height,names,analysis):
    """Keep a usable sofa/table/TV group while retaining a verified walking route."""
    from .floorplan import rect,overlap
    from .circulation import check
    objects={o['object_key']:o for o in ir['objects']}
    supports={o['key']:o['support_key'] for o in analysis['objects']}
    sofas=[k for k,n in names.items() if n.startswith('Sofa_')]
    tables=[k for k,n in names.items() if n.startswith('Table_coffee')]
    televisions=[supports[k] for k,n in names.items() if n.startswith('TV_') and supports.get(k)]
    poses=deepcopy(fit['poses']);relations=[]
    for sofa in sofas:
        room=objects[sofa]['room_key'];table=next((k for k in tables if objects[k]['room_key']==room),None)
        tv=next((k for k in televisions if objects[k]['room_key']==room),None)
        if table is None or tv is None:continue
        yaw=np.deg2rad(objects[sofa]['yaw_deg']);direction=np.array([np.sin(yaw),-np.cos(yaw)])
        target=np.array(poses[tv][:2])*[width,height]
        half_sofa=float(np.dot(abs(direction),np.array(poses[sofa][2:])*[width,height]/2))
        half_table=float(np.dot(abs(direction),np.array(poses[table][2:])*[width,height]/2))
        room_bounds=next(r['bounds'] for r in ir['rooms'] if r['key']==room)
        tangent=np.array([-direction[1],direction[0]])
        lateral_axis=int(np.argmax(abs(tangent)))
        extent=max(poses[k][lateral_axis+2]*(width,height)[lateral_axis]/2 for k in (sofa,table,tv))
        target[lateral_axis]=np.clip(target[lateral_axis],room_bounds[lateral_axis]*(width,height)[lateral_axis]+extent+.12,room_bounds[lateral_axis+2]*(width,height)[lateral_axis]-extent-.12)
        choices=[]
        for distance in np.arange(2.5,4.01,.25):
            centre=target-direction*distance
            for gap in (.5,.65,.8,.95,1.1):
                candidate=deepcopy(poses);candidate[tv][:2]=(target/[width,height]).tolist();candidate[sofa][:2]=(centre/[width,height]).tolist()
                candidate[table][:2]=((centre+direction*(half_sofa+half_table+gap))/[width,height]).tolist()
                boxes={k:rect(p) for k,p in candidate.items() if objects[k]['role']=='furniture'}
                if any(b[0]<room_bounds[0]+.1/width or b[2]>room_bounds[2]-.1/width or b[1]<room_bounds[1]+.1/height or b[3]>room_bounds[3]-.1/height for k,b in boxes.items() if k in (sofa,table)):continue
                if any(overlap(boxes[k],b)>1e-9 for k in (sofa,table) for other,b in boxes.items() if other!=k):continue
                report=check(ir,candidate,width,height,names)
                if not report['passed']:continue
                choices.append(((distance-3)**2+(gap-.6)**2,candidate,report,float(distance),gap))
        if not choices:raise AgentError('NATIVE_LAYOUT_INCOMPATIBLE','Seating group cannot retain furniture access and connected walking routes')
        _,poses,report,distance,gap=min(choices,key=lambda c:c[0])
        # Keep the observed rug with its seating group, at native size.
        for key in poses:
            if objects[key]['role']=='rug' and objects[key]['room_key']==room:poses[key][:2]=poses[table][:2].copy()
        relations.append(dict(sofa=sofa,table=table,tv_support=tv,sofa_tv_centres_m=distance,sofa_table_edge_gap_m=gap))
    fit['poses']=poses;fit['seating_groups']=relations
    fit['circulation']=check(ir,poses,width,height,names)
    return fit
