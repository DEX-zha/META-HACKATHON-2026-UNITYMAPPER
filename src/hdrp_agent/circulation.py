"""Conservative 2D walking clearance, independent of image similarity scores."""
from collections import deque
import math
import numpy as np

WALK_WIDTH=.8
DOOR_DEPTH=1.3


def service_points(box,yaw,asset_name=''):
    """Front access; bed also needs both sides. Tables can be approached on any side."""
    a,b,c,d=box;cx,cy=(a+c)/2,(b+d)/2
    points=[(cx,b-.5),(c+.5,cy),(cx,d+.5),(a-.5,cy)]
    front=round(yaw/90)%4
    if asset_name.lower().startswith('bed_'):
        return [points[front],points[(front+1)%4],points[(front-1)%4]]
    if asset_name.lower().startswith('table_'):return [points[front]]
    return [points[front]]


def check(ir,poses,width,height,names=None):
    """Flood-fill room free space after inflating furniture by pedestrian radius.

    A cell is valid only if its entire square fits: half-diagonal is added to the
    inflation. Four-connected movement cannot cut diagonally through corners.
    """
    from .floorplan import rect
    names=names or {};scale=np.array([width,height,width,height]);reports=[]
    walls={w['object_key']:w for w in ir['walls']}
    radius=WALK_WIDTH/2;step=.1;pad=radius+step*math.sqrt(2)/2
    for room in ir['rooms']:
        bounds=np.array(room['bounds'])*scale;a,b,c,d=bounds
        xs=np.arange(a+pad,c-pad+1e-8,step);ys=np.arange(b+pad,d-pad+1e-8,step)
        xx,yy=np.meshgrid(xs,ys);free=np.ones(xx.shape,dtype=bool)
        furniture=[o for o in ir['objects'] if o['role']=='furniture' and o['room_key']==room['key']]
        services=[];obstacles=[]
        for o in furniture:
            box=np.array(rect(poses[o['object_key']]))*scale;obstacles.append(box);x0,y0,x1,y1=box
            free&=~((xx>=x0-pad)&(xx<=x1+pad)&(yy>=y0-pad)&(yy<=y1+pad))
            services.extend((o['object_key'],p) for p in service_points(box,o['yaw_deg'],names.get(o['object_key'],'')))
        entrances=[];blocked_doors=[]
        for opening in ir['openings']:
            wall=walls[opening['wall_key']]
            if opening['kind']!='door' or room['key'] not in wall['rooms']:continue
            start=np.array(wall['start'])*[width,height];delta=(np.array(wall['end'])-wall['start'])*[width,height]
            p=start+delta*(opening['start']+opening['end'])/2
            lo=np.minimum(start+delta*opening['start'],start+delta*opening['end'])
            hi=np.maximum(start+delta*opening['start'],start+delta*opening['end'])
            normal=0 if abs(delta[0])<.005 else 1;lo[normal]-=DOOR_DEPTH;hi[normal]+=DOOR_DEPTH
            if any(min(x1,hi[0])-max(x0,lo[0])>1e-6 and min(y1,hi[1])-max(y0,lo[1])>1e-6 for x0,y0,x1,y1 in obstacles):blocked_doors.append(opening['key'])
            # Place the pedestrian centre just inside the wall boundary.
            if abs(wall['start'][0]-wall['end'][0])<.005:p[0]+=.55 if p[0]<(a+c)/2 else -.55
            else:p[1]+=.55 if p[1]<(b+d)/2 else -.55
            entrances.append((opening['key'],p))
        def cell(p):
            if len(xs)==0 or len(ys)==0:return None
            j=int(round((p[0]-xs[0])/step));i=int(round((p[1]-ys[0])/step))
            candidates=[]
            for ni in range(i-1,i+2):
                for nj in range(j-1,j+2):
                    if not(0<=ni<len(ys) and 0<=nj<len(xs) and free[ni,nj]):continue
                    distance=(xs[nj]-p[0])**2+(ys[ni]-p[1])**2
                    if distance>.12**2:continue
                    # Connect the exact service point to the grid without crossing
                    # the pedestrian-inflated rectangles, including between samples.
                    segment=np.linspace(p,[xs[nj],ys[ni]],16)
                    if any(px<a+radius or px>c-radius or py<b+radius or py>d-radius or any(x0-radius<=px<=x1+radius and y0-radius<=py<=y1+radius for x0,y0,x1,y1 in obstacles) for px,py in segment):continue
                    candidates.append((distance,(ni,nj)))
            return min(candidates)[1] if candidates else None
        points=entrances+services
        if not entrances:
            reports.append(dict(room_key=room['key'],passed=False,reason='room_has_no_observed_door'));continue
        origin=cell(entrances[0][1]);visited=set();parents={}
        if origin is not None:
            queue=deque([origin]);visited.add(origin)
            while queue:
                i,j=queue.popleft()
                for ni,nj in ((i-1,j),(i+1,j),(i,j-1),(i,j+1)):
                    nxt=(ni,nj)
                    if 0<=ni<len(ys) and 0<=nj<len(xs) and free[ni,nj] and nxt not in visited:
                        visited.add(nxt);parents[nxt]=(i,j);queue.append(nxt)
        unreachable=[key for key,p in points if cell(p) not in visited]+blocked_doors
        paths=[]
        if not unreachable:
            for key,p in points:
                node=cell(p);path=[]
                while node is not None:
                    i,j=node;path.append([float(xs[j]),float(ys[i])]);node=parents.get(node)
                paths.append(dict(target=key,points_m=path[::-1]))
        reports.append(dict(room_key=room['key'],passed=not unreachable,unreachable=unreachable,paths=paths,reachable_area_m2=len(visited)*step*step))
    return dict(passed=all(r['passed'] for r in reports),method='inflated_footprint_four_connected_grid',walking_width_m=WALK_WIDTH,door_clearance_depth_m=DOOR_DEPTH,cell_size_m=step,rooms=reports,scope='Planned footprints and furniture access; not a native mesh collision or accessibility certificate')
