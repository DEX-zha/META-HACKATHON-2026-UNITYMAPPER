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


def test_enrichment_preserves_existing_poses_and_avoids_overlap():
    from copy import deepcopy
    from hdrp_agent.house_planning import box,overlap
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    old=dict(id='existing',room_id='office',group_id='work',role='desk',prefab_guid='desk',center=[3,.5,3],position=[3,0,3],bounds_size=[1,1,1],yaw=0,support_id=None)
    before=deepcopy(old)
    plant=dict(prefab_guid='plant',dependency_hash='a'*32,bounds_center=[0,.5,0],bounds_size=[.4,1,.4],front_status='not_applicable',surfaces=[],support_regions=[])
    design=dict(room_id='office',groups=[dict(id='extra',recipe='plant',priority='preferred',description='greenery')],detail_assets=[])
    result=place_groups(building,design,{'Interior_plant_A':plant},existing=[old],access_points=[[3,4.2]])
    assert old==before and len(result['instances'])==1
    new=result['instances'][0]
    assert new['id']!='existing'
    assert not overlap(box(old,3,3,0),box(new,new['center'][0],new['center'][2],new['yaw']))


def test_books_spread_across_free_shelf_compartments():
    from hdrp_agent.house_planning import place_details
    triangles=lambda y:[[[0,y,0],[1,y,0],[1,y,1]],[[0,y,0],[1,y,1],[0,y,1]]]
    shelf=dict(prefab_guid='shelf',bounds_center=[.5,.5,.5],bounds_size=[1,1,1],surfaces=[dict(id='low',triangles=triangles(.2)),dict(id='high',triangles=triangles(.8))],support_regions=[dict(surface_id=s,rectangle_xz=[0,0,1,1],roles=['books']) for s in ['low','high']])
    book=dict(prefab_guid='books',dependency_hash='a'*32,front_status='qualified',bounds_center=[0,.1,0],bounds_size=[.2,.2,.2])
    instances=[dict(id='shelf',room_id='office',group_id='library',role='bookshelf',prefab_guid='shelf',position=[0,0,0],center=[.5,.5,.5],bounds_size=[1,1,1],yaw=0)]
    place_details('office',['Book_set_A','Book_set_A'],{'Bookshelf':shelf,'Book_set_A':book},instances,[],[])
    assert [round(i['position'][1],2) for i in instances[1:]]==[.2,.8]


def test_floor_decoration_uses_native_prefab_clear_of_doors_and_furniture():
    from hdrp_agent.house_planning import box,overlap
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    def asset(name,path,size):return dict(prefab_guid=name,dependency_hash='v',prefab_path=path,bounds_size=size,bounds_center=[.2,.02,.1],front_status='unknown')
    assets={'Carpet_C':asset('rug','Assets/AtmosphericHouse/Prefabs/Props/Carpets/Carpet_C.prefab',[1.8,.008,1.3]),'Decal_papers_G':asset('papers','Assets/AtmosphericHouse/Prefabs/Decals/Decal_papers_G.prefab',[1.6,.014,.86])}
    desk=dict(id='desk',room_id='office',group_id='work',role='desk',prefab_guid='desk',center=[3,.4,1],position=[3,0,1],bounds_size=[1.8,.8,.8],yaw=0,support_id=None)
    design=dict(room_id='office',groups=[],detail_assets=['Carpet_C','Decal_papers_G'])
    result=place_groups(building,design,assets,existing=[desk])
    assert len(result['instances'])==2 and not result['missing']
    for i in result['instances']:
        assert i['role']=='floor_covering' and i['scale']==[1,1,1] and i['support_id'] is None
        assert abs(i['center'][1]-i['bounds_size'][1]/2-.001)<1e-8
        footprint=box(i,i['center'][0],i['center'][2],i['yaw'])
        assert not any(overlap(footprint,r) for r in result['door_reservations'])
        assert not overlap(footprint,box(desk,3,1,0))
    assets['Carpet_C']['bounds_size'][1]=1
    result=place_groups(building,design,assets,existing=[desk])
    assert len(result['instances'])==1 and any('unsupported' in m['reason'] for m in result['missing'])
