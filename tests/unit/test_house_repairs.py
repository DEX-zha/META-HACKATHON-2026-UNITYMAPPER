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
