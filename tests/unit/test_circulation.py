from hdrp_agent.circulation import check
from hdrp_agent.floorplan import pose


def room_with_barrier(gap):
    ir=dict(rooms=[dict(key='room',bounds=[0,0,1,1])],walls=[
        dict(object_key='west',start=[0,0],end=[0,1],rooms=['room']),
        dict(object_key='east',start=[1,0],end=[1,1],rooms=['room'])],openings=[
        dict(key='entry',wall_key='west',kind='door',start=.35,end=.65),
        dict(key='exit',wall_key='east',kind='door',start=.35,end=.65)],objects=[
        dict(object_key='cabinet',room_key='room',role='furniture',yaw_deg=90)])
    return ir,{'cabinet':pose([.45,gap/4,.55,1-gap/4])}


def test_nonoverlapping_furniture_can_still_block_circulation():
    ir,poses=room_with_barrier(.6)
    report=check(ir,poses,4,4)
    assert not report['passed']
    assert 'exit' in report['rooms'][0]['unreachable']


def test_door_routes_and_furniture_service_access_share_free_space():
    ir,poses=room_with_barrier(1.3)
    report=check(ir,poses,4,4)
    assert report['passed']
    assert {p['target'] for p in report['rooms'][0]['paths']}=={'entry','exit','cabinet'}
    assert report['walking_width_m']==.8


def test_closed_room_cannot_be_certified_without_an_entrance():
    ir,poses=room_with_barrier(1.3);ir['openings']=[]
    assert not check(ir,poses,4,4)['passed']


def test_bed_requires_side_access_not_only_a_point_at_the_foot():
    ir,poses=room_with_barrier(1.3)
    ir['objects'][0].update(object_key='bed',yaw_deg=180)
    poses={'bed':pose([.03,.05,.53,.55])}
    assert not check(ir,poses,4,4,{'bed':'Bed_king'})['passed']


def test_apartment_expands_whole_modules_and_connects_all_furniture_access():
    import json
    from pathlib import Path
    from hdrp_agent.native_layout import fit_functional_layout
    data=json.loads((Path(__file__).parents[1]/'fixtures/native_apartment.json').read_text())
    ir,w,h,fit=fit_functional_layout(data['observation'],data['analysis'],data['catalogue'],data['aspect'])
    assert fit['rejected_layouts'] # The compact, unusable arrangement is rejected.
    assert fit['circulation']['passed']
    for room in ir['rooms']:
        b=room['bounds'];assert (b[2]-b[0])*w==6
        assert (b[3]-b[1])*h==4
    destinations=[p['target'] for r in fit['circulation']['rooms'] for p in r['paths']]
    assert destinations.count('double_bed')==3
    assert {'door_entrance','door_interior','tv_cabinet','sofa','wardrobe'}<=set(destinations)
