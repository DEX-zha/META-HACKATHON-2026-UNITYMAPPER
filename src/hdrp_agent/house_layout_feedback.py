"""Explain rejected native-size layouts before constructing an incomplete room."""
from .house_planning import box,overlap


def feedback(design,placement,assets):
    collisions=[]
    for group in design['groups']:
        ground=[i for i in group.get('items',[]) if i['support_slot'] is None and i['asset'] in assets]
        for index,item in enumerate(ground):
            a=box(assets[item['asset']],*item['offset_m'],item['yaw_deg'])
            for other in ground[index+1:]:
                b=box(assets[other['asset']],*other['offset_m'],other['yaw_deg'])
                if overlap(a,b):
                    collisions.append(dict(group_id=group['id'],slots=[item['slot'],other['slot']],assets=[item['asset'],other['asset']],footprints_in_group=[a,b],reason='Items overlap inside their own group; translating or rotating the entire group cannot separate them. Change local offsets/orientations or split the functional group.'))
    return dict(missing=placement['missing'],internal_group_collisions=collisions,placed_instances=[{k:i[k] for k in ('id','group_id','position','yaw','bounds_size','support_id')} for i in placement['instances']])
