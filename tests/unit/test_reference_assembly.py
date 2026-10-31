import json
from copy import deepcopy
from hdrp_agent.reference_assembly import fit_building_perimeter


def room():
    cat=[dict(asset_id='floor',name='Floor_6x3',bounds_center_m=[-3,0,1.5],bounds_size_m=[6,0,3])]
    cat += [dict(asset_id='wall',name='WallOut_3x',path='Assets/AtmosphericHouse/Prefabs/Building/WallOut_3x.prefab',bounds_center_m=[-1.5,1.5,.1],bounds_size_m=[3,3,0])]
    def obj(key,asset,pos,yaw=0,scale=1):return dict(key=key,asset_id=asset,position_m=pos,rotation_deg=[0,yaw,0],scale=[scale,1,1])
    plan=dict(objects=[obj('floor','floor',[3,0,-1.5]),obj('n1','wall',[0,0,1.5]),obj('n2','wall',[3,0,1.5]),obj('s','wall',[3,0,-1.5],scale=2),obj('w','wall',[-3,0,1.5],90),obj('e','wall',[3,0,1.5],270)])
    return plan,cat


def test_wrong_facing_and_pivot_are_fixed_and_stable():
    plan,cat=room();original=deepcopy(plan);fixed,proof=fit_building_perimeter(plan,cat)
    assert plan==original and proof[0]['status']=='fitted'
    objects={o['key']:o for o in fixed['objects']}
    assert objects['w']['rotation_deg']==[0,270,0]
    assert abs(objects['w']['position_m'][2]-1.5)<1e-6
    assert objects['e']['rotation_deg']==[0,90,0]
    assert abs(objects['e']['position_m'][2]+1.5)<1e-6
    assert objects['s']['rotation_deg']==[0,180,0]
    again,_=fit_building_perimeter(fixed,cat)
    assert json.dumps(again)==json.dumps(fixed)


def test_incomplete_envelope_and_nonrectangular_floor_are_not_invented():
    plan,cat=room();plan['objects']=[o for o in plan['objects'] if o['key']!='e'];fixed,proof=fit_building_perimeter(plan,cat)
    assert fixed==plan and proof[0]['status']=='incomplete_side_coverage'
    plan,cat=room();plan['objects'][0]['rotation_deg'][1]=45
    assert fit_building_perimeter(plan,cat)==(plan,[])


def test_external_progress_does_not_freeze_on_unaligned_object_crops():
    from hdrp_agent.reference_worker import accept_external_candidate
    def candidate(score,misses):return dict(metrics=dict(score=score,contacts=dict(checks=[dict(status='unresolved') for _ in range(misses)])))
    assert accept_external_candidate(candidate(.34,2),candidate(.38,2))
    assert not accept_external_candidate(candidate(.56,0),candidate(.38,2))
    assert not accept_external_candidate(candidate(.2,3),candidate(.38,2))
    assert accept_external_candidate(candidate(.39,0),candidate(.38,2))
