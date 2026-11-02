from copy import deepcopy
from hdrp_agent.house_planning import building_from_outline,place_groups
from hdrp_agent.house_layout_feedback import feedback


def setup(size=1.5):
    building=building_from_outline(dict(rooms=[dict(id='room',floor_index=0,width_m=6,depth_m=6)]))
    assets={
        'Carpet_C':dict(prefab_path='Assets/AtmosphericHouse/Prefabs/Props/Carpets/Carpet_C.prefab',prefab_guid='rug',dependency_hash='v1',bounds_size=[size,.01,size],bounds_center=[.2,.005,.1],front_status='unknown'),
        'Interior_plant_B':dict(prefab_path='Assets/AtmosphericHouse/Prefabs/Props/Plants/Interior_plant_B.prefab',prefab_guid='plant',dependency_hash='v1',bounds_size=[.3,.7,.3],bounds_center=[0,.35,0],front_status='not_applicable'),
    }
    group=dict(id='play',recipe='reading',description='Play area',priority='mandatory',anchor_m=[3,3],yaw_deg=90,items=[
        dict(slot='rug',asset='Carpet_C',offset_m=[0,0],yaw_deg=0,support_slot=None),
        dict(slot='plant',asset='Interior_plant_B',offset_m=[.1,.1],yaw_deg=0,support_slot=None),
    ])
    return building,dict(room_id='room',groups=[group],detail_assets=[],unresolved=[]),assets


def test_group_rug_does_not_reject_independent_furniture_or_fake_collision():
    building,design,assets=setup();original=deepcopy(design)
    result=place_groups(building,design,assets)
    assert design==original
    assert {i['id'] for i in result['instances']}=={'room-play-rug','room-play-plant'}
    rug=next(i for i in result['instances'] if i['role']=='floor_covering')
    assert rug['group_id']=='play' and rug['scale']==[1,1,1] and rug['yaw']==90
    assert all(r['priority']=='mandatory' for r in result['requirements'])
    assert not result['missing'] and not feedback(design,result,assets)['internal_group_collisions']


def test_unplaceable_floor_keeps_furniture_and_explicit_requirement():
    building,design,assets=setup(8)
    result=place_groups(building,design,assets)
    assert [i['id'] for i in result['instances']]==['room-play-plant']
    assert result['missing'][0]['id']=='room-play-rug'
    assert result['missing'][0]['priority']=='mandatory'
    assert len(result['requirements'])==2


def test_floor_only_group_keeps_preferred_pose_and_pivot():
    building,design,assets=setup();design['groups'][0]['items'].pop()
    result=place_groups(building,design,assets)
    rug=result['instances'][0]
    assert rug['id']=='room-play-rug' and rug['center']==[3,.006,3]
    assert rug['position']==[2.9,.001,3.2]
    assert not result['missing']


def test_name_alone_or_thick_geometry_cannot_become_walkable():
    for spoof in ('path','height'):
        building,design,assets=setup()
        if spoof=='path':assets['Carpet_C']['prefab_path']='Assets/HouseProps/Prefabs/Carpet_C.prefab'
        else:assets['Carpet_C']['bounds_size'][1]=.4
        result=place_groups(building,design,assets)
        assert not any(i['role']=='floor_covering' for i in result['instances'])
        assert feedback(design,result,assets)['internal_group_collisions']
