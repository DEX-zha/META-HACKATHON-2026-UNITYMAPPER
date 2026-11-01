import pytest
from pydantic import ValidationError
from hdrp_agent.house_domain import HouseProgram, BuildingIR, AssetSemantics


def program(n=35):
    return dict(id='house',project_id='project',run_id='run',brief='A complete house',rooms=[dict(id='kitchen',floor_id='ground',purpose='kitchen')],requirements=[dict(id=f'need-{i}',scope_id='kitchen',role=f'role-{i}',priority='mandatory',provenance='user') for i in range(n)])


def building():
    return dict(id='building',floors=[dict(id='ground',elevation_m=0,ceiling_height_m=2.8,slab_thickness_m=.2)],rooms=[dict(id='room',floor_id='ground',polygon=[[0,0],[4,0],[4,3],[0,3]])],boundaries=[dict(id='south',floor_id='ground',start=[0,0],end=[4,0],room_ids=['room'])],portals=[dict(id='entry',boundary_id='south',spaces=['room','exterior'],interval_m=[1,2],height_m=2.2)])


def test_exhaustive_program_has_no_flat_twenty_object_cap():
    p=HouseProgram.model_validate(program());assert len(p.requirements)==35
    bad=program();bad['requirements'][1]['id']=bad['requirements'][0]['id']
    with pytest.raises(ValidationError):HouseProgram.model_validate(bad)
    bad=program();bad['requirements'][0]['status']='waived'
    with pytest.raises(ValidationError):HouseProgram.model_validate(bad)


def test_shared_portal_binding_and_interval_are_required():
    assert BuildingIR.model_validate(building()).portals[0].spaces==['room','exterior']
    for key,value in [('boundary_id','absent'),('interval_m',[3,5]),('spaces',['room','missing'])]:
        b=building();b['portals'][0][key]=value
        with pytest.raises(ValidationError):BuildingIR.model_validate(b)


def test_invalid_polygon_and_unqualified_forward_rejected():
    b=building();b['rooms'][0]['polygon']=[[0,0],[4,0],[2,2],[0,3]]
    with pytest.raises(ValidationError):BuildingIR.model_validate(b)
    data=dict(prefab_guid='a'*32,dependency_hash='b'*32,prefab_path='Assets/Chair.prefab',bounds_center=[0,0,0],bounds_size=[1,1,1],front_status='qualified')
    with pytest.raises(ValidationError):AssetSemantics.model_validate(data)
    data.update(front_status='unknown');assert AssetSemantics.model_validate(data).forward is None


def test_room_overlap_and_boundary_detached_from_room_are_rejected():
    b=building();b['rooms'].append(dict(id='overlap',floor_id='ground',polygon=[[2,0],[6,0],[6,3],[2,3]]))
    with pytest.raises(ValidationError):BuildingIR.model_validate(b)
    b=building();b['boundaries'][0]['start']=[0,8];b['boundaries'][0]['end']=[4,8]
    with pytest.raises(ValidationError):BuildingIR.model_validate(b)


def test_reversed_duplicate_walls_and_overlapping_floor_heights_rejected():
    b=building();b['boundaries'].append(dict(b['boundaries'][0],id='duplicate',start=[4,0],end=[0,0]))
    with pytest.raises(ValidationError):BuildingIR.model_validate(b)
    b=building();b['floors'].append(dict(id='upper',elevation_m=2,ceiling_height_m=2.8,slab_thickness_m=.2))
    with pytest.raises(ValidationError):BuildingIR.model_validate(b)


def test_group_scope_has_one_owner():
    p=program();p['rooms'][0]['group_ids']=['same','same']
    with pytest.raises(ValidationError):HouseProgram.model_validate(p)
