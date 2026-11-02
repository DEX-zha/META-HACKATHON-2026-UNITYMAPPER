"""Metric house layout and prefab recipe placement. No source-scene poses are used."""
from collections import deque
from math import ceil, cos, sin, radians
from .domain import AgentError
from .house_domain import BuildingIR
from .house_supports import footprint_supported
from .house_floor_details import floor_detail, place_floor_details

# Relative functional relations, refined by measured bounds. Fourth field is
# orientation toward the user; support names refer to slots in the same group.
RECIPES = {
 'office': [('desk','Workdesk',0,0,0,None),('chair','Chair_kitchen',0,1.05,180,None),('screen','Computer_screen',0,-.12,0,'desk'),('keyboard','Computer_keyboard',0,.20,0,'desk'),('mouse','Computer_mouse',.42,.20,0,'desk')],
 'kitchen': [('counter','Kitchen_counter_A',0,0,0,None),('sink','Kitchen_counter_sink',1.35,0,0,None),('stove','Stove',-1.3,0,0,None),('fridge','Fridge',-2.4,0,0,None)],
 'bedroom': [('bed','Bed_king',0,0,0,None),('left-table','Side_table_E',-1.5,-.65,0,None),('right-table','Side_table_E',1.5,-.65,0,None)],
 'living': [('sofa','Sofa_3seat',0,0,0,None),('table','Table_coffee',0,1.25,0,None),('tv-stand','Dresser_C',0,2.8,180,None),('tv','TV_off',0,0,0,'tv-stand')],
 'bathroom': [('sink','Bathroom_sink',0,0,0,None),('toilet','Toilet',1.3,0,0,None)],
 'dining': [('table','Table_A',0,0,0,None),('chair-a','Chair_kitchen',0,.9,180,None),('chair-b','Chair_kitchen',0,-.9,0,None)],
 'library': [('bookshelf','Bookshelf',0,0,0,None)],
 'reading': [('seat','Sofa_1seat',0,0,0,None),('side-table','Side_table_E',1,0,0,None)],
 'lounge': [('sofa','Sofa_3seat',0,0,0,None),('table','Table_coffee',0,1.25,0,None)],
 'plant': [('plant','Interior_plant_A',0,0,0,None)],
 'storage': [('wardrobe','Wardrobe',0,0,0,None)],
}


def building_from_outline(outline):
    rooms=outline['rooms']
    if not rooms:raise AgentError('INVALID_TOPOLOGY','House needs rooms')
    if any(r['floor_index']!=0 for r in rooms):raise AgentError('VERTICAL_ACCESS_UNQUALIFIED','A qualified stair connection is required for additional floors')
    result=dict(id='building',floors=[dict(id='ground',elevation_m=0,ceiling_height_m=2.8,slab_thickness_m=.2)],rooms=[],boundaries=[],portals=[],vertical_connections=[])
    x=0;segments={}
    for room in rooms:
        w=max(3,ceil(room['width_m']/3)*3);d=max(3,ceil(room['depth_m']/3)*3)
        polygon=[[x,0],[x+w,0],[x+w,d],[x,d]]
        result['rooms'].append(dict(id=room['id'],floor_id='ground',polygon=polygon))
        for a,b in zip(polygon,polygon[1:]+polygon[:1]):
            axis=0 if a[1]==b[1] else 1;fixed=a[1-axis]
            for start in range(int(min(a[axis],b[axis])),int(max(a[axis],b[axis]))):segments.setdefault((axis,fixed,start),[]).append(room['id'])
        x+=w
    merged=[]
    for (axis,fixed,start),owners in sorted(segments.items()):
        owners=sorted(owners)
        if merged and merged[-1][:2]==[axis,fixed] and merged[-1][3]==start and merged[-1][4]==owners:merged[-1][3]+=1
        else:merged.append([axis,fixed,start,start+1,owners])
    for i,(axis,fixed,start,end,owners) in enumerate(merged):
        a=[start,fixed] if axis==0 else [fixed,start];b=[end,fixed] if axis==0 else [fixed,end]
        boundary=dict(id=f'wall-{i}',floor_id='ground',start=a,end=b,room_ids=owners);result['boundaries'].append(boundary)
        entry=axis==0 and fixed==0 and owners==[rooms[0]['id']]
        shared=len(owners)==2
        if end-start>=3 and (entry or shared):
            result['portals'].append(dict(id=f'door-{i}',boundary_id=boundary['id'],spaces=owners if shared else owners+['exterior'],interval_m=[.9,2.1],height_m=2.2,kind='door'))
        elif end-start>=3 and len(owners)==1 and axis==0 and fixed>0:
            result['portals'].append(dict(id=f'window-{i}',boundary_id=boundary['id'],spaces=owners+['exterior'],interval_m=[.95,2.05],height_m=2.3,kind='window'))
    return BuildingIR.model_validate(result).model_dump(mode='json')


def rotate(x,z,yaw):
    a=radians(yaw);return x*cos(a)+z*sin(a),-x*sin(a)+z*cos(a)


def box(asset,x,z,yaw):
    sx,_,sz=asset['bounds_size'];a=radians(yaw)
    w=abs(cos(a))*sx+abs(sin(a))*sz;d=abs(sin(a))*sx+abs(cos(a))*sz
    return [x-w/2,z-d/2,x+w/2,z+d/2]


def overlap(a,b,margin=0):
    return a[0]<b[2]+margin and a[2]>b[0]-margin and a[1]<b[3]+margin and a[3]>b[1]-margin


def room_bounds(room):
    return [min(p[0] for p in room['polygon']),min(p[1] for p in room['polygon']),max(p[0] for p in room['polygon']),max(p[1] for p in room['polygon'])]


def access_check(bounds,obstacles,points,width=.8):
    """Conservative 2D proposal gate; native triangle traversal is still required."""
    step=.2;half=width/2
    nx=int((bounds[2]-bounds[0])/step);nz=int((bounds[3]-bounds[1])/step)
    def world(cell):return bounds[0]+(cell[0]+.5)*step,bounds[1]+(cell[1]+.5)*step
    def valid(cell):
        x,z=world(cell)
        return 0<=cell[0]<nx and 0<=cell[1]<nz and not any(overlap([x-half,z-half,x+half,z+half],b) for b in obstacles)
    def nearest(p):
        cells=[(x,z) for x in range(nx) for z in range(nz) if valid((x,z)) and (world((x,z))[0]-p[0])**2+(world((x,z))[1]-p[1])**2<.36]
        return min(cells,key=lambda c:(world(c)[0]-p[0])**2+(world(c)[1]-p[1])**2) if cells else None
    targets=[nearest(p) for p in points]
    if not targets or any(p is None for p in targets):return False
    reached={targets[0]};queue=deque(reached)
    while queue:
        x,z=queue.popleft()
        for cell in [(x+1,z),(x-1,z),(x,z+1),(x,z-1)]:
            if cell not in reached and valid(cell):reached.add(cell);queue.append(cell)
    return all(p in reached for p in targets)


def door_reservations(building,room):
    rect=room_bounds(room);boxes=[];points=[]
    walls={w['id']:w for w in building['boundaries']}
    for p in building['portals']:
        if p['kind']!='door' or room['id'] not in p['spaces']:continue
        w=walls[p['boundary_id']];axis=0 if w['start'][1]==w['end'][1] else 1
        mid=(p['interval_m'][0]+p['interval_m'][1])/2
        x=w['start'][0]+(mid if axis==0 else 0);z=w['start'][1]+(mid if axis==1 else 0)
        inward=(1 if abs((z if axis==0 else x)-rect[1 if axis==0 else 0])<.01 else -1)
        px=x+(0 if axis==0 else inward*.75);pz=z+(inward*.75 if axis==0 else 0)
        boxes.append([min(x,px)-(.75 if axis==0 else .1),min(z,pz)-(.1 if axis==0 else .75),max(x,px)+(.75 if axis==0 else .1),max(z,pz)+(.1 if axis==0 else .75)])
        points.append([px,pz])
    return boxes,points


def place_groups(building,design,assets,*,existing=(),access_points=(),detail_offset=0):
    room=next(r for r in building['rooms'] if r['id']==design['room_id']);rect=room_bounds(room)
    reservations,entry=door_reservations(building,room)
    instances=[dict(i) for i in existing if i['room_id']==room['id']];initial=len(instances)
    missing=[];occupied=[box(i,i['center'][0],i['center'][2],i['yaw']) for i in instances if i['support_id'] is None];uses=list(entry)+list(access_points);requirements=[]
    for group in sorted(design['groups'],key=lambda g:{'mandatory':0,'preferred':1,'optional':2}[g['priority']]):
        recipe=RECIPES.get(group['recipe'])
        if recipe is None:
            missing.append(dict(id=group['id'],reason='No qualified recipe for '+group['description']));continue
        slots=[]
        for role,name,x,z,yaw,support in recipe:
            key=room['id']+'-'+group['id']+'-'+role
            requirements.append(dict(id=key,scope_id=room['id'],role=name,quantity=1,priority=group['priority'],provenance='inferred'))
            asset=assets.get(name)
            if asset is None or asset['front_status'] not in {'qualified','not_applicable'}:
                missing.append(dict(id=key,reason='Prefab or functional semantics unavailable: '+name,priority=group['priority']));continue
            slots.append(dict(id=key,role=role,asset=asset,x=x,z=z,yaw=yaw,support=support))
        ground=[s for s in slots if s['support'] is None]
        if not ground:continue
        best=None
        for yaw in (0,90,180,270):
            local=[]
            for s in ground:
                x,z=rotate(s['x'],s['z'],yaw);local.append(box(s['asset'],x,z,s['yaw']+yaw))
            lo=[min(b[0] for b in local),min(b[1] for b in local),max(b[2] for b in local),max(b[3] for b in local)]
            for fraction in (.25,.5,.75):
                if yaw==0:anchor=[rect[0]+(rect[2]-rect[0])*fraction,rect[1]-lo[1]+.12]
                elif yaw==180:anchor=[rect[0]+(rect[2]-rect[0])*fraction,rect[3]-lo[3]-.12]
                elif yaw==90:anchor=[rect[0]-lo[0]+.12,rect[1]+(rect[3]-rect[1])*fraction]
                else:anchor=[rect[2]-lo[2]-.12,rect[1]+(rect[3]-rect[1])*fraction]
                footprints=[[b[0]+anchor[0],b[1]+anchor[1],b[2]+anchor[0],b[3]+anchor[1]] for b in local]
                if any(b[0]<rect[0]+.1 or b[1]<rect[1]+.1 or b[2]>rect[2]-.1 or b[3]>rect[3]-.1 for b in footprints):continue
                if any(overlap(b,o,.08) for b in footprints for o in occupied+reservations):continue
                if any(overlap(b,o) for i,b in enumerate(footprints) for o in footprints[i+1:]):continue
                access=[]
                for s,b in zip(ground,footprints):
                    if s['role'] in {'chair','plant'}:continue
                    candidates=[]
                    for side in (0,-1,1):
                        x,z=rotate(side*(s['asset']['bounds_size'][0]/2+.5),s['asset']['bounds_size'][2]/2+.65,s['yaw']+yaw)
                        point=[(b[0]+b[2])/2+x,(b[1]+b[3])/2+z]
                        if rect[0]+.4<point[0]<rect[2]-.4 and rect[1]+.4<point[1]<rect[3]-.4 and not any(overlap([point[0]-.4,point[1]-.4,point[0]+.4,point[1]+.4],o) for o in occupied+footprints):candidates.append(point)
                    if not candidates:break
                    access.append(candidates[0])
                else:
                    if access_check(rect,occupied+footprints,uses+access):
                        score=sum((p[0]-(rect[0]+rect[2])/2)**2+(p[1]-(rect[1]+rect[3])/2)**2 for p in access)
                        if best is None or score<best[0]:best=(score,yaw,anchor,footprints,access)
                continue
        if best is None:
            missing.extend(dict(id=s['id'],reason='No arrangement preserves access at native size',priority=group['priority']) for s in slots);continue
        _,yaw,anchor,footprints,access=best;occupied.extend(footprints);uses.extend(access)
        placed={}
        for s in slots:
            a=s['asset'];local_y=0;angle=s['yaw']+yaw
            if s['support']:
                parent=placed.get(s['support'])
                if parent is None:missing.append(dict(id=s['id'],reason='Supporting slot unavailable'));continue
                support=next(p['asset'] for p in slots if p['role']==s['support'])
                region=next(iter(support.get('support_regions',[])),None)
                if region is None:missing.append(dict(id=s['id'],reason='Supporting surface not qualified'));continue
                surface=next(p for p in support['surfaces'] if p['id']==region['surface_id'])
                local_box=box(a,s['x'],s['z'],s['yaw'])
                if not footprint_supported(surface['triangles'],local_box):missing.append(dict(id=s['id'],reason='Object exceeds actual support'));continue
                px,pz=rotate(s['x'],s['z'],parent['yaw']);x=parent['center'][0]+px;z=parent['center'][2]+pz
                local_y=parent['position'][1]+sum(v[1] for t in surface['triangles'] for v in t)/(3*len(surface['triangles']))
                angle=parent['yaw']+s['yaw']
            else:
                x,z=rotate(s['x'],s['z'],yaw);x+=anchor[0];z+=anchor[1]
            cx,cy,cz=a['bounds_center'];sx,sy,sz=a['bounds_size'];rx,rz=rotate(cx,cz,angle)
            value=dict(id=s['id'],room_id=room['id'],group_id=group['id'],prefab_guid=a['prefab_guid'],dependency_hash=a['dependency_hash'],position=[x-rx,local_y-cy+sy/2,z-rz],yaw=angle,scale=[1,1,1],center=[x,local_y+sy/2,z],bounds_size=[sx,sy,sz],support_id=placed[s['support']]['id'] if s['support'] else None,role=s['role'])
            instances.append(value);placed[s['role']]=value
    details=design.get('detail_assets',[])
    floors=[(i,n) for i,n in enumerate(details) if n.startswith(('Carpet_','Decal_papers_'))]
    for i,name in enumerate(details):
        if not name.startswith(('Carpet_','Decal_papers_')):place_details(room['id'],[name],assets,instances,requirements,missing,offset=detail_offset+i)
    place_floor_details(room,floors,assets,instances,requirements,missing,reservations,detail_offset)
    return dict(instances=instances[initial:],requirements=requirements,missing=missing,access_points=uses,door_reservations=reservations)


def place_details(room_id,names,assets,instances,requirements,missing,*,offset=0):
    """Pack native-sized props on qualified mesh patches, retaining every need.

    Work in support prefab coordinates (not renderer-centre coordinates). Check
    existing children in world space so decoration never overlaps equipment.
    """
    by_guid={a['prefab_guid']:a for a in assets.values()}
    supports=[i for i in instances if i.get('role')!='floor_covering']
    for index,name in enumerate(names,offset):
        key=f'{room_id}-detail-{index}'
        requirements.append(dict(id=key,scope_id=room_id,role=name,quantity=1,priority='preferred',provenance='creative'))
        asset=assets.get(name);placed=False
        if asset and asset['front_status'] in {'qualified','not_applicable'}:
            candidates=sorted(supports,key=lambda i:0 if name.startswith('Book_') and i['role']=='bookshelf' else 1)
            for parent in candidates:
                support=by_guid[parent['prefab_guid']]
                def occupancy(region):
                    surface=next(s for s in support['surfaces'] if s['id']==region['surface_id'])
                    ts=surface['triangles'];height=parent['position'][1]+sum(v[1] for t in ts for v in t)/(3*len(ts))
                    x0,z0,x1,z1=region['rectangle_xz'];count=0
                    for child in instances:
                        if child.get('support_id')!=parent['id']:continue
                        x,z=rotate(child['center'][0]-parent['position'][0],child['center'][2]-parent['position'][2],-parent['yaw'])
                        if x0<=x<=x1 and z0<=z<=z1 and abs(child['center'][1]-child['bounds_size'][1]/2-height)<.03:count+=1
                    return count
                for region in sorted(support.get('support_regions',[]),key=occupancy):
                    if region.get('roles')==['books'] and not name.startswith('Book_'):continue
                    surface=next(s for s in support['surfaces'] if s['id']==region['surface_id'])
                    triangles=surface['triangles']
                    x0,z0,x1,z1=region['rectangle_xz']
                    for ix in range(1,10):
                        for iz in range(1,10):
                            x=x0+(x1-x0)*ix/10;z=z0+(z1-z0)*iz/10
                            local=box(asset,x,z,0)
                            if local[0]-.015<x0 or local[1]-.015<z0 or local[2]+.015>x1 or local[3]+.015>z1:continue
                            if not footprint_supported(triangles,[local[0]-.015,local[1]-.015,local[2]+.015,local[3]+.015]):continue
                            surface_y=sum(v[1] for t in triangles for v in t)/(3*len(triangles))
                            # Reject props that would intersect an upper shelf. Raw measured
                            # patches supply a conservative overhead check, not semantic approval.
                            blocked=False
                            for other in support['surfaces']:
                                for triangle in other.get('triangles',[]):
                                    low=min(v[1] for v in triangle)
                                    if surface_y+.02<low<surface_y+asset['bounds_size'][1]+.04 and overlap(local,[min(v[0] for v in triangle),min(v[2] for v in triangle),max(v[0] for v in triangle),max(v[2] for v in triangle)]):blocked=True;break
                                if blocked:break
                            if blocked:continue
                            y=parent['position'][1]+surface_y
                            dx,dz=rotate(x,z,parent['yaw']);wx=parent['position'][0]+dx;wz=parent['position'][2]+dz
                            bounds=box(asset,wx,wz,parent['yaw'])
                            sy=asset['bounds_size'][1]
                            if any(i['id']!=parent['id'] and i['center'][1]+i['bounds_size'][1]/2>y+.001 and i['center'][1]-i['bounds_size'][1]/2<y+sy and overlap(bounds,box(by_guid[i['prefab_guid']],i['center'][0],i['center'][2],i['yaw']),.025) for i in instances):continue
                            cx,cy,cz=asset['bounds_center'];rx,rz=rotate(cx,cz,parent['yaw'])
                            instances.append(dict(id=key,room_id=room_id,group_id=parent['group_id'],prefab_guid=asset['prefab_guid'],dependency_hash=asset['dependency_hash'],position=[wx-rx,y-cy+sy/2,wz-rz],yaw=parent['yaw'],scale=[1,1,1],center=[wx,y+sy/2,wz],bounds_size=asset['bounds_size'],support_id=parent['id'],role='detail'))
                            placed=True;break
                        if placed:break
                    if placed:break
                if placed:break
        if not placed:missing.append(dict(id=key,reason='No qualified, unoccupied support for detail: '+name,priority='preferred'))
