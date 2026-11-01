"""Typed, bounded local group changes with geometric non-regression preflight."""
from copy import deepcopy
from math import hypot,isfinite
from .domain import fingerprint
from .house_planning import rotate,box,overlap,room_bounds,door_reservations,access_check


def propose(manifest,observations,attempted):
    objects={i['id']:i for i in manifest['instances']}
    for observation in observations:
        target=objects.get(observation.get('instance_id'))
        if target is None or observation['suggested_action'] not in {'move','rotate'}:continue
        delta=observation['translation_m'];angle=observation['yaw_delta']
        if len(delta)!=3 or not all(isfinite(v) for v in delta+[angle]) or abs(delta[1])>.001 or hypot(delta[0],delta[2])>6 or abs(angle)>180:continue
        if hypot(delta[0],delta[2])<.01 and abs(angle)<.1:continue
        result=deepcopy(manifest);group=[i for i in result['instances'] if i['room_id']==target['room_id'] and i['group_id']==target['group_id']]
        anchor=list(next((i for i in group if i['support_id'] is None),target)['center'])
        for item in group:
            for key in ('position','center'):
                x,z=rotate(item[key][0]-anchor[0],item[key][2]-anchor[2],angle)
                item[key][0]=anchor[0]+x+delta[0];item[key][2]=anchor[2]+z+delta[2]
            item['yaw']+=angle
        signature=fingerprint(result['instances'])
        if signature in attempted:continue
        rooms={r['id']:r for r in result['building']['rooms']};valid=True
        for room_id,room in rooms.items():
            bounds=room_bounds(room);reservations,points=door_reservations(result['building'],room)
            ground=[i for i in result['instances'] if i['room_id']==room_id and i['support_id'] is None]
            footprints=[box(i,i['center'][0],i['center'][2],i['yaw']) for i in ground]
            if any(b[0]<bounds[0]+.08 or b[1]<bounds[1]+.08 or b[2]>bounds[2]-.08 or b[3]>bounds[3]-.08 or any(overlap(b,r,.05) for r in reservations) for b in footprints):valid=False;break
            if any(overlap(b,c) for n,b in enumerate(footprints) for c in footprints[n+1:]):valid=False;break
            for item,b in zip(ground,footprints):
                if item.get('role') in {'chair','plant'}:continue
                choices=[]
                for side in (0,-1,1):
                    dx,dz=rotate(side*(item['bounds_size'][0]/2+.5),item['bounds_size'][2]/2+.65,item['yaw'])
                    p=[item['center'][0]+dx,item['center'][2]+dz]
                    if bounds[0]+.4<p[0]<bounds[2]-.4 and bounds[1]+.4<p[1]<bounds[3]-.4 and not any(overlap([p[0]-.4,p[1]-.4,p[0]+.4,p[1]+.4],o) for o in footprints):choices.append(p)
                if not choices:valid=False;break
                points.append(choices[0])
            if not valid or not access_check(bounds,footprints,points):valid=False;break
            entries=result.setdefault('access',[])
            entry=next((a for a in entries if a['room_id']==room_id),None)
            if entry is None:entries.append(dict(room_id=room_id,points=points))
            else:entry['points']=points
        if valid:return result,dict(kind='transform_group',scope_id=target['room_id'],group_id=target['group_id'],translation_m=delta,yaw_delta=angle,reason=observation['message'],signature=signature)
    return None
