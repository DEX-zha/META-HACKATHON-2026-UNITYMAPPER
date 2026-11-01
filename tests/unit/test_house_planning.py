import pytest
from hdrp_agent.house_planning import building_from_outline, place_groups
from hdrp_agent.domain import AgentError


def outline():
    return dict(title='Home',unresolved=[],rooms=[dict(id='office',purpose='office',floor_index=0,width_m=6,depth_m=6,brief='work'),dict(id='kitchen',purpose='kitchen',floor_index=0,width_m=6,depth_m=3,brief='cook')])


def test_rooms_have_single_shared_boundary_and_connected_portals():
    building=building_from_outline(outline())
    assert len(building['rooms'])==2
    shared=[b for b in building['boundaries'] if len(b['room_ids'])==2]
    assert len(shared)==1
    assert any(p['boundary_id']==shared[0]['id'] for p in building['portals'])
    assert any('exterior' in p['spaces'] for p in building['portals'])


def test_unimplemented_vertical_access_is_not_silently_dropped():
    data=outline();data['rooms'][1]['floor_index']=1
    with pytest.raises(AgentError,match='stair'):building_from_outline(data)


def test_placements_keep_native_scale_and_protect_door_corridor():
    building=building_from_outline(outline())
    # Artificial measured geometry, no provider or Unity claims.
    assets={name:dict(prefab_guid=str(i).zfill(32),dependency_hash='a'*32,prefab_path='Assets/'+name+'.prefab',bounds_center=[0,.5,0],bounds_size=[1,1,1],forward=[0,0,1],front_status='qualified',support_regions=[],surfaces=[]) for i,name in enumerate(['Workdesk','Chair_kitchen','Computer_screen','Computer_keyboard','Computer_mouse'])}
    result=place_groups(building,dict(room_id='office',groups=[dict(id='work',recipe='office',priority='mandatory',description='desk')],detail_assets=[],unresolved=[]),assets)
    assert result['instances']
    assert all(i['scale']==[1,1,1] for i in result['instances'])
    assert result['missing'] # Fake desk has no qualified top: monitor cannot be fabricated as satisfied.


def test_details_use_support_pivot_and_keep_equipment_clear():
    from hdrp_agent.house_planning import place_details, box, overlap
    # Offset renderer centre catches the common pivot/centre confusion.
    table=dict(prefab_guid='table',dependency_hash='v1',bounds_center=[1,.5,0],bounds_size=[2,1,1],front_status='qualified',support_regions=[dict(surface_id='top',rectangle_xz=[0,-.5,2,.5])],surfaces=[dict(id='top',triangles=[[[0,1,-.5],[2,1,-.5],[2,1,.5]],[[0,1,-.5],[2,1,.5],[0,1,.5]]])])
    prop=dict(prefab_guid='cup',dependency_hash='v1',bounds_center=[0,.1,0],bounds_size=[.2,.2,.2],front_status='qualified',support_regions=[],surfaces=[])
    parent=dict(id='desk',group_id='work',room_id='office',prefab_guid='table',position=[10,0,10],center=[11,.5,10],bounds_size=[2,1,1],yaw=0)
    instances=[parent];requirements=[];missing=[]
    place_details('office',['cup','cup','absent'],{'table':table,'cup':prop},instances,requirements,missing)
    assert len(instances)==3 and len(requirements)==3
    assert missing[0]['id']=='office-detail-2'
    a,b=instances[1:]
    assert 10<a['center'][0]<12 and a['position'][1]==1
    assert a['support_id']=='desk' and a['scale']==[1,1,1]
    assert not overlap(box(prop,a['center'][0],a['center'][2],0),box(prop,b['center'][0],b['center'][2],0),.025)


def test_optional_decor_never_displaces_primary_function():
    from hdrp_agent.house_planning import RECIPES
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    names={s[1] for key in ['office','library','plant'] for s in RECIPES[key]}
    assets={name:dict(prefab_guid=name,dependency_hash='a'*32,bounds_center=[0,.5,0],bounds_size=[1,1,1],front_status='qualified',surfaces=[],support_regions=[]) for name in names}
    assets['Bookshelf']['bounds_size']=[8,3,8]  # Must be omitted, never shrunk.
    groups=[dict(id='extra',recipe='library',priority='preferred',description='storage'),dict(id='primary',recipe='office',priority='mandatory',description='work'),dict(id='green',recipe='plant',priority='optional',description='greenery')]
    placed=place_groups(building,dict(room_id='office',groups=groups,detail_assets=[]),assets)
    assert placed['instances'][0]['group_id']=='primary'
    assert any(i['role']=='plant' for i in placed['instances'])
    assert not any(i['prefab_guid']=='Bookshelf' for i in placed['instances'])
    assert next(m for m in placed['missing'] if m['id']=='office-extra-bookshelf')['priority']=='preferred'
    assert all(i['scale']==[1,1,1] for i in placed['instances'])


def test_books_prefer_library_and_cannot_intersect_shelf_above():
    from hdrp_agent.house_planning import place_details
    triangles=lambda y:[[[0,y,0],[1,y,0],[1,y,1]],[[0,y,0],[1,y,1],[0,y,1]]]
    shelf=dict(prefab_guid='shelf',bounds_center=[.5,.5,.5],bounds_size=[1,1,1],surfaces=[dict(id='s',triangles=triangles(.2)),dict(id='ceiling',triangles=triangles(.5))],support_regions=[dict(surface_id='s',rectangle_xz=[0,0,1,1],roles=['books'])])
    prop=dict(prefab_guid='books',dependency_hash='a'*32,front_status='qualified',bounds_center=[0,.2,0],bounds_size=[.2,.4,.2])
    instance=dict(id='shelf',room_id='office',group_id='library',role='bookshelf',prefab_guid='shelf',position=[0,0,0],center=[.5,.5,.5],bounds_size=[1,1,1],yaw=0)
    instances=[instance];requirements=[];missing=[]
    place_details('office',['Book_set_A'],{'Bookshelf':shelf,'Book_set_A':prop},instances,requirements,missing)
    assert len(instances)==1 and len(missing)==1
    prop['bounds_size'][1]=.2;prop['bounds_center'][1]=.1
    place_details('office',['Book_set_A'],{'Bookshelf':shelf,'Book_set_A':prop},instances,[],[])
    assert len(instances)==2 and instances[-1]['support_id']=='shelf'
