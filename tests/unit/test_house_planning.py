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


def test_explicit_model_layout_changes_furniture_and_position_without_template():
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    def asset(guid):return dict(prefab_guid=guid,dependency_hash='v',bounds_center=[0,.4,0],bounds_size=[1.2,.8,.6],front_status='unknown',surfaces=[],support_regions=[])
    assets={'HouseProps/Desk_office':asset('desk-a'),'Workdesk':asset('desk-b')}
    def design(name,anchor,yaw):return dict(room_id='office',groups=[dict(id='work',recipe='office',priority='mandatory',description='custom work zone',anchor_m=anchor,yaw_deg=yaw,items=[dict(slot='desk',asset=name,offset_m=[0,0],yaw_deg=0,support_slot=None)])],detail_assets=[])
    first=place_groups(building,design('HouseProps/Desk_office',[2,2],0),assets)
    second=place_groups(building,design('Workdesk',[4,4],90),assets)
    assert len(first['instances'])==len(second['instances'])==1
    assert first['instances'][0]['prefab_guid']=='desk-a' and first['instances'][0]['center']==[2,.4,2]
    assert second['instances'][0]['prefab_guid']=='desk-b' and second['instances'][0]['center']==[4,.4,4]
    assert second['instances'][0]['yaw']==90
    # No kitchen chair, screen or old fixed wall arrangement gets injected.
    invalid=place_groups(building,design('Workdesk',[100,100],0),assets)
    assert invalid['instances'] and not invalid['missing']
    assert all(0 < v < 6 for v in invalid['instances'][0]['center'][::2])


def test_explicit_chair_slot_name_does_not_create_impossible_standing_access():
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    def asset(guid,size):return dict(prefab_guid=guid,dependency_hash='v',bounds_center=[0,size[1]/2,0],bounds_size=size,front_status='unknown',surfaces=[],support_regions=[])
    assets={'HouseProps/Desk_office':asset('desk',[1.8,.78,.78]),'HouseProps/Chair_office':asset('chair',[.71,1.07,.69])}
    items=[dict(slot='desk_island',asset='HouseProps/Desk_office',offset_m=[0,0],yaw_deg=180,support_slot=None),dict(slot='chair_main',asset='HouseProps/Chair_office',offset_m=[0,1.05],yaw_deg=180,support_slot=None)]
    design=dict(room_id='office',groups=[dict(id='work',recipe='office',priority='mandatory',description='island',anchor_m=[3,2.6],yaw_deg=0,items=items)],detail_assets=[])
    result=place_groups(building,design,assets)
    assert len(result['instances'])==2 and not result['missing']


def test_explicit_props_cannot_overlap_each_other_on_support():
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    table=dict(prefab_guid='desk',dependency_hash='v',bounds_center=[0,.4,0],bounds_size=[2,.8,1],front_status='qualified',support_regions=[dict(surface_id='top',rectangle_xz=[-1,-.5,1,.5])],surfaces=[dict(id='top',triangles=[[[-1,.8,-.5],[1,.8,-.5],[1,.8,.5]],[[-1,.8,-.5],[1,.8,.5],[-1,.8,.5]]])])
    screen=dict(prefab_guid='screen',dependency_hash='v',bounds_center=[0,.2,0],bounds_size=[.5,.4,.2],front_status='qualified')
    items=[dict(slot='desk',asset='desk',offset_m=[0,0],yaw_deg=0,support_slot=None)]+[dict(slot='screen'+str(i),asset='screen',offset_m=[0,0],yaw_deg=0,support_slot='desk') for i in range(2)]
    group=dict(id='work',recipe='office',priority='mandatory',description='work',anchor_m=[3,3],yaw_deg=0,items=items)
    result=place_groups(building,dict(room_id='office',groups=[group],detail_assets=[]),{'desk':table,'screen':screen})
    assert len(result['instances'])==2
    assert any('intersects existing' in m['reason'] for m in result['missing'])
    table['surfaces'].append(dict(id='upper',triangles=[[[-1,1,-.5],[1,1,-.5],[1,1,.5]],[[-1,1,-.5],[1,1,.5],[-1,1,.5]]]))
    result=place_groups(building,dict(room_id='office',groups=[group],detail_assets=[]),{'desk':table,'screen':screen})
    assert len(result['instances'])==1
    assert all('upper surface' in m['reason'] for m in result['missing'])


@pytest.mark.parametrize('parents', [('books','books'),('book2','book1')])
def test_invalid_supports_keep_needs_without_aborting_independent_furniture(parents):
    building=building_from_outline(dict(rooms=[dict(id='office',floor_index=0,width_m=6,depth_m=6)]))
    asset=dict(prefab_guid='shelf',dependency_hash='v',bounds_center=[0,.5,0],bounds_size=[1,1,.4],front_status='qualified',surfaces=[],support_regions=[])
    items=[dict(slot='shelf',asset='shelf',offset_m=[0,0],yaw_deg=0,support_slot=None)]
    items.extend(dict(slot='book'+str(i+1),asset='book',offset_m=[0,0],yaw_deg=0,support_slot=parent) for i,parent in enumerate(parents))
    design=dict(room_id='office',groups=[dict(id='library',recipe='library',priority='mandatory',anchor_m=[3,3],yaw_deg=0,items=items)],detail_assets=[])
    result=place_groups(building,design,{'shelf':asset})
    assert len(result['instances'])==1
    assert len(result['requirements'])==3
    assert len(result['missing'])==2
    assert all(m['reason']=='Unknown or cyclic support slot' for m in result['missing'])


@pytest.mark.parametrize('forward,yaw,expected',[
    ([0,0,1],0,(0,1.15)),([0,0,-1],0,(0,-1.15)),
    ([1,0,0],0,(1.65,0)),([1,0,0],90,(0,-1.65)),
])
def test_access_uses_reviewed_native_front_and_rotated_depth(forward,yaw,expected):
    from hdrp_agent.house_planning import access_offset
    asset=dict(front_status='qualified',forward=forward,bounds_size=[2,1,1])
    assert access_offset(asset,yaw)==pytest.approx(expected)


def test_wardrobe_cannot_claim_access_from_its_side_when_front_faces_wall():
    from hdrp_agent.house_planning import rotate
    building=building_from_outline(dict(rooms=[dict(id='bedroom',floor_index=0,width_m=6,depth_m=6)]))
    asset=dict(prefab_guid='wardrobe',dependency_hash='v1',bounds_center=[0,1,0],bounds_size=[1,2,1],front_status='qualified',forward=[1,0,0],surfaces=[],support_regions=[])
    design=dict(room_id='bedroom',groups=[dict(id='storage',recipe='storage',priority='mandatory',description='clothes',anchor_m=[5.4,3],yaw_deg=0,items=[dict(slot='wardrobe',asset='Wardrobe',offset_m=[0,0],yaw_deg=0,support_slot=None)])],detail_assets=[])
    result=place_groups(building,design,{'Wardrobe':asset})
    assert len(result['instances'])==1
    item=result['instances'][0];front=rotate(1,0,item['yaw']);point=result['access_points'][-1]
    delta=[point[0]-item['center'][0],point[1]-item['center'][2]]
    assert sum(a*b for a,b in zip(front,delta))==pytest.approx(1.15)
    assert item['center'][0]!=pytest.approx(5.4) or item['yaw']!=0


def test_explicit_slot_names_do_not_send_library_books_to_bedside_or_another_room():
    from copy import deepcopy
    from hdrp_agent.house_planning import place_details
    triangles=[[[0,.5,0],[1,.5,0],[1,.5,1]],[[0,.5,0],[1,.5,1],[0,.5,1]]]
    shelf=dict(prefab_guid='shelf',bounds_center=[.5,.5,.5],bounds_size=[1,1,1],surfaces=[dict(id='s',triangles=triangles)],support_regions=[dict(surface_id='s',rectangle_xz=[0,0,1,1],roles=['books'])])
    table=deepcopy(shelf);table.update(prefab_guid='table');table['support_regions'][0]['roles']=['decor']
    book=dict(prefab_guid='books',dependency_hash='a'*32,front_status='qualified',bounds_center=[0,.1,0],bounds_size=[.2,.2,.2])
    def support(id,room,guid,x):return dict(id=id,room_id=room,group_id=id,role=id,prefab_guid=guid,position=[x,0,0],center=[x+.5,.5,.5],bounds_size=[1,1,1],yaw=0)
    instances=[support('foreignShelf','other','shelf',10),support('bedside01','bedroom','table',3),support('shelf01','bedroom','shelf',0)]
    assets={'Bookshelf':shelf,'Nightstand':table,'Book_set_A':book}
    place_details('bedroom',['Book_set_A'],assets,instances,[],[])
    assert instances[-1]['support_id']=='shelf01'
    only_foreign=instances[:1];missing=[]
    place_details('bedroom',['Book_set_A'],assets,only_foreign,[],missing)
    assert len(only_foreign)==1 and len(missing)==1


def test_enrichment_identity_survives_rejected_and_unplaced_details():
    from hdrp_agent.house_planning import namespace_enrichment
    placed=dict(requirements=[dict(id='room-detail-0',role='book'),dict(id='room-detail-1',role='lamp')],instances=[dict(id='room-detail-0',support_id='existing-shelf',position=[1,2,3])],missing=[dict(id='room-detail-1',reason='No support')])
    first=namespace_enrichment(placed,'request-a')
    other=namespace_enrichment(placed,'request-b')
    assert first==namespace_enrichment(placed,'request-a')
    assert {r['id'] for r in first['requirements']}.isdisjoint(r['id'] for r in other['requirements'])
    assert first['instances'][0]['id']==first['requirements'][0]['id']
    assert first['missing'][0]['id']==first['requirements'][1]['id']
    assert first['instances'][0]['support_id']=='existing-shelf'
    assert first['instances'][0]['position']==[1,2,3]
    assert placed['requirements'][0]['id']=='room-detail-0'
