from hdrp_agent.house_planning import building_from_outline,place_groups,place_details
from hdrp_agent.domain import payload


def test_wall_and_window_props_cannot_be_placed_on_floor_or_desktop():
    building=building_from_outline(dict(rooms=[dict(id='room',floor_index=0,width_m=6,depth_m=6)]))
    assets={name:dict(prefab_guid=name,dependency_hash='v1',bounds_center=[0,.5,0],bounds_size=[.5,1,.1],front_status='qualified',placement_modes=[mode]) for name,mode in [('poster','wall_mount'),('curtain','window_mount'),('pillow','horizontal_support')]}
    design=dict(room_id='room',groups=[dict(id='decor',recipe='reading',description='Personal decoration',priority='preferred',anchor_m=[3,3],yaw_deg=0,items=[dict(slot=n,asset=n,offset_m=[i,0],yaw_deg=0,support_slot=None) for i,n in enumerate(assets)])],detail_assets=[])
    result=place_groups(building,design,assets)
    assert result['instances']==[] and len(result['requirements'])==3
    assert [d['required_placement_modes'] for d in result['missing']]==[['wall_mount'],['window_mount'],['horizontal_support']]
    missing=[];needs=[];instances=[]
    place_details('room',['poster','curtain'],assets,instances,needs,missing)
    assert not instances and len(missing)==2 and len(needs)==2


def test_unknown_mode_cannot_authorize_floor_placement():
    payload('ModelHouseAssetReview',dict(front='unknown',supports=[],summary='Unclear mount',placement_modes=['unknown']))
    # The mode is explicit uncertainty, never shorthand for all modes.
    from hdrp_agent.house_domain import AssetSemantics
    import pytest
    with pytest.raises(ValueError):
        AssetSemantics(prefab_guid='a'*32,dependency_hash='b'*32,prefab_path='Assets/Object.prefab',bounds_center=[0,0,0],bounds_size=[1,1,1],placement_modes=['unknown','floor'],placement_evidence=['review'])
