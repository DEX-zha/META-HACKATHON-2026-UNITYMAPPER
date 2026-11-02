"""Whole flat floor prefabs placed by measured bounds, independent of furniture fronts."""
from math import isfinite


def floor_detail(name,asset):
    if not asset:return False
    path=asset.get('prefab_path','')
    approved=(path.startswith('Assets/AtmosphericHouse/Prefabs/Props/Carpets/') and name.startswith('Carpet_')) or (path.startswith('Assets/AtmosphericHouse/Prefabs/Decals/') and name.startswith('Decal_papers_'))
    size=asset['bounds_size']
    return approved and all(isfinite(v) and v>=0 for v in size) and 0<size[0]<10 and 0<size[2]<10 and size[1]<=.05


def place_floor_details(room,names,assets,instances,requirements,missing,reservations,offset):
    from .house_planning import room_bounds,rotate,box,overlap
    rect=room_bounds(room)
    for index,name in names:
        key=f"{room['id']}-detail-{offset+index}"
        requirements.append(dict(id=key,scope_id=room['id'],role=name,quantity=1,priority='preferred',provenance='creative'))
        a=assets.get(name)
        if not floor_detail(name,a):
            missing.append(dict(id=key,reason='Floor prefab not measured or unsupported: '+name,priority='preferred'));continue
        carpet=name.startswith('Carpet_');anchors=[i for i in instances if i['role'] in (('sofa','seat','table') if carpet else ('desk','bookshelf'))]
        target=anchors[0]['center'] if anchors else [(rect[0]+rect[2])/2,0,(rect[1]+rect[3])/2]
        best=None
        occupied=[box(i,i['center'][0],i['center'][2],i['yaw']) for i in instances if i.get('support_id') is None]
        for yaw in (0,90,180,270):
            for ix in range(1,20):
                for iz in range(1,20):
                    x=rect[0]+(rect[2]-rect[0])*ix/20;z=rect[1]+(rect[3]-rect[1])*iz/20;b=box(a,x,z,yaw)
                    if b[0]<rect[0]+.12 or b[1]<rect[1]+.12 or b[2]>rect[2]-.12 or b[3]>rect[3]-.12:continue
                    if any(overlap(b,o,.06) for o in occupied+reservations):continue
                    score=(x-target[0])**2+(z-target[2])**2
                    if best is None or score<best[0]:best=(score,x,z,yaw)
        if best is None:
            missing.append(dict(id=key,reason='No clear floor area for native-sized '+name,priority='preferred'));continue
        _,x,z,yaw=best;cx,cy,cz=a['bounds_center'];sx,sy,sz=a['bounds_size'];rx,rz=rotate(cx,cz,yaw)
        instances.append(dict(id=key,room_id=room['id'],group_id='floor-decoration',prefab_guid=a['prefab_guid'],dependency_hash=a['dependency_hash'],position=[x-rx,-cy+sy/2+.001,z-rz],yaw=yaw,scale=[1,1,1],center=[x,sy/2+.001,z],bounds_size=[sx,sy,sz],support_id=None,role='floor_covering'))
