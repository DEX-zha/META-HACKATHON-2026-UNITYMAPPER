from hdrp_agent.house_repairs import propose
from hdrp_agent.house_planning import building_from_outline


def test_repair_moves_whole_group_but_never_accepts_wall_intersection():
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    a=dict(id='desk',room_id='office',group_id='work',center=[3,.5,3],position=[3,0,3],bounds_size=[1,1,1],yaw=0,support_id=None)
    b=dict(a,id='screen',center=[3,1.2,3],position=[3,1,3],support_id='desk')
    manifest=dict(building=building,instances=[a,b])
    observation=dict(instance_id='desk',suggested_action='move',translation_m=[1,0,0],yaw_delta=0,message='Improve composition')
    output,patch=propose(manifest,[observation],set())
    assert output['instances'][0]['position'][0]==4 and output['instances'][1]['position'][0]==4
    assert manifest['instances'][0]['position'][0]==3
    assert propose(manifest,[dict(observation,translation_m=[6,0,0])],set()) is None
    assert propose(manifest,[observation],{patch['signature']}) is None


def test_adjust_item_moves_bedside_subtree_without_moving_bed_or_plant():
    from copy import deepcopy
    building=building_from_outline(dict(rooms=[dict(id='bedroom',floor_index=0,width_m=9,depth_m=6)]))
    def item(id,x,z,support=None,group='sleep',y=0,size=None):
        return dict(id=id,room_id='bedroom',group_id=group,center=[x,y+.25,z],position=[x,y,z],bounds_size=size or [.4,.5,.4],yaw=0,support_id=support)
    bed=item('bed',4,4,size=[1.2,.5,2]);bed['yaw']=180;table=item('nightstand',2,4)
    lamp=item('lamp',2.1,4,'nightstand',group='decoration',y=.5)
    shade=item('shade',2.1,4,'lamp',group='details',y=1)
    plant=item('plant',7,3)
    manifest=dict(building=building,instances=[bed,table,lamp,shade,plant]);original=deepcopy(manifest)
    observation=dict(instance_id='nightstand',suggested_action='adjust_item',translation_m=[.6,0,0],yaw_delta=-90,message='Bring bedside table closer to bed')
    result,patch=propose(manifest,[observation],set())
    by_id={i['id']:i for i in result['instances']}
    assert manifest==original and by_id['bed']==bed and by_id['plant']==plant
    assert by_id['nightstand']['position']==[2.6,0,4]
    assert abs(by_id['lamp']['position'][0]-2.6)<1e-9 and abs(by_id['lamp']['position'][2]-4.1)<1e-9
    assert by_id['shade']['position'][1]==1
    assert patch['kind']=='transform_item' and set(patch['affected_instance_ids'])=={'nightstand','lamp','shade'}
    assert propose(manifest,[dict(observation,translation_m=[2,0,0])],set()) is None  # Bed collision.
    assert propose(manifest,[dict(observation,translation_m=[-4,0,0])],set()) is None  # Outside room.
    assert propose(manifest,[dict(observation,instance_id='lamp')],set()) is None  # Cannot detach support.
    assert propose(manifest,[observation],{patch['signature']}) is None


def test_adjust_item_contract_and_floor_covering_exclusion():
    from hdrp_agent.domain import payload
    observation=dict(instance_id='rug',kind='composition',severity='warning',message='Move rug',suggested_action='adjust_item',translation_m=[1,0,0],yaw_delta=0)
    payload('ModelHouseInspection',dict(room_id='room',summary='Inspect',observations=[observation]))
    manifest=dict(instances=[dict(id='rug',role='floor_covering',support_id=None)])
    assert propose(manifest,[observation],set()) is None
