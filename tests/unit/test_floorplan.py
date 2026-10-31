from copy import deepcopy
import pytest
from hdrp_agent.domain import AgentError
from hdrp_agent.floorplan import validate_observation, optimize, objective, checkpoint


def fixture():
    rooms=[dict(key='left',bounds=[.05,.1,.5,.9]),dict(key='right',bounds=[.5,.1,.95,.9])]
    objects=[dict(object_key='bed',room_key='right',role='furniture',bounds=[.57,.2,.79,.65],yaw_deg=0,confidence=.9),dict(object_key='cabinet',room_key='right',role='furniture',bounds=[.83,.3,.92,.7],yaw_deg=90,confidence=.9)]
    return dict(projection='overhead_cutaway',envelope=[.05,.1,.95,.9],rooms=rooms,walls=[dict(object_key='partition',start=[.5,.1],end=[.5,.9],rooms=['left','right'])],openings=[dict(key='door',wall_key='partition',kind='door',start=.7,end=.9)],objects=objects,limits=[])


def test_topology_rejects_overlapping_rooms_and_unbound_doors():
    ir=fixture();assert validate_observation(ir,{'bed','cabinet','partition'})==ir
    bad=deepcopy(ir);bad['rooms'][1]['bounds'][0]=.4
    with pytest.raises(AgentError):validate_observation(bad,{'bed','cabinet','partition'})
    bad=deepcopy(ir);bad['openings'][0]['wall_key']='missing'
    with pytest.raises(AgentError):validate_observation(bad,{'bed','cabinet','partition'})


@pytest.mark.parametrize('mirror',[False,True])
def test_optimizer_reduces_errors_without_source_transforms(mirror):
    ir=fixture()
    if mirror:
        for room in ir['rooms']:a,b,c,d=room['bounds'];room['bounds']=[1-c,b,1-a,d]
        for item in ir['objects']:a,b,c,d=item['bounds'];item['bounds']=[1-c,b,1-a,d]
    starts=[{'bed':[.1,.4,.2,.4],'cabinet':[.12,.43,.08,.3]}, {'bed':[.8,.4,.3,.5],'cabinet':[.8,.4,.2,.4]}]
    for initial in starts:
        result=optimize(ir,initial)
        assert result['metrics']['loss']<objective(ir,initial)['loss']
        assert result['metrics']['outside_room']<1e-8
        assert result['metrics']['collisions']<1e-8
        assert result['metrics']['door_clearance']<1e-8
        assert result['history'][-1]['loss']<=result['history'][0]['loss']


def test_checkpoint_refuses_other_evidence(tmp_path):
    path=tmp_path/'checkpoint.json';state=dict(evidence_hash='a',phase='layout',poses={'bed':[.6,.4,.2,.4]})
    checkpoint(path,state)
    assert checkpoint(path,evidence_hash='a')==state
    with pytest.raises(AgentError):checkpoint(path,evidence_hash='b')


def test_native_measurement_does_not_certify_apertures_from_perfect_boxes():
    from hdrp_agent.floorplan import measure_native
    ir=fixture();proof=dict(version='v1',projected_objects=[dict(object_key=o['object_key'],bbox_xyxy=o['bounds']) for o in ir['objects']])
    result=measure_native(ir,proof)
    assert result['bounds_admissible']
    assert not result['composition_qualified']
    assert 'wall_aperture_geometry' in result['unverified']
    proof['projected_objects'].pop()
    result=measure_native(ir,proof)
    assert not result['coverage_complete'] and not result['bounds_admissible']


def test_native_correction_preserves_prefab_pivot_and_reduces_residual():
    import numpy as np
    from hdrp_agent.floorplan import correct_native, pose
    from hdrp_agent.reference_geometry import rotation
    asset=dict(asset_id='asset',bounds_center_m=[-1,0,.3])
    obj=dict(key='bed',asset_id='asset',position_m=[1,0,2],rotation_deg=[0,90,0],scale=[1,1,1])
    measured=dict(coverage_complete=True,per_object=dict(bed=dict(actual_bounds=[.4,.3,.6,.7],target_bounds=[.45,.25,.67,.69],max_edge_error=.05)))
    result=correct_native(dict(objects=[obj]),dict(screen_width_m=10,screen_height_m=8),measured,[asset])['objects'][0]
    rot=rotation(obj['rotation_deg']);old=np.array(obj['position_m'])+rot@np.array(asset['bounds_center_m']);new=np.array(result['position_m'])+rot@(np.array(asset['bounds_center_m'])*result['scale'])
    assert new[0]-old[0]==pytest.approx(.6)
    assert new[2]-old[2]==pytest.approx(.24)
    assert result['asset_id']==obj['asset_id'] and result['rotation_deg']==obj['rotation_deg']
    assert result['scale']==obj['scale'] # Residual correction cannot deform or resize furniture.


def test_floor_covers_occluded_strips_to_wall_not_visible_floor_crop():
    from hdrp_agent.floorplan import room_floor_bounds
    ir=fixture();ir['rooms'][0]['bounds']=[.08,.12,.48,.88]
    ir['walls']+= [dict(object_key='west',start=[.05,.1],end=[.05,.9],rooms=['left']),dict(object_key='north',start=[.05,.1],end=[.5,.1],rooms=['left']),dict(object_key='south',start=[.05,.9],end=[.5,.9],rooms=['left'])]
    assert room_floor_bounds(ir,'left')==[.05,.1,.5,.9]


def test_shared_wall_must_separate_rooms_and_openings_cannot_overlap():
    ir=fixture();ir['walls'][0]['start'][0]=.1;ir['walls'][0]['end'][0]=.1
    with pytest.raises(AgentError):validate_observation(ir,{'bed','cabinet','partition'})
    ir=fixture();ir['openings'].append(dict(key='overlap',wall_key='partition',kind='window',start=.8,end=.95))
    with pytest.raises(AgentError):validate_observation(ir,{'bed','cabinet','partition'})


def test_compilation_preserves_furniture_proportions_on_all_axes():
    from hdrp_agent.floorplan import build_plan
    ir=fixture();ir['objects'].append(dict(object_key='partition',room_key=None,role='wall',bounds=[.49,.1,.51,.9],yaw_deg=90,confidence=1))
    analysis=dict(objects=[dict(key=o['object_key'],asset_id=o['object_key'],support_key=None) for o in ir['objects']])
    catalogue=[dict(asset_id='bed',bounds_size_m=[2,1,1],bounds_center_m=[-1,.5,.5]),dict(asset_id='cabinet',bounds_size_m=[1,2,.5],bounds_center_m=[0,1,0]),dict(asset_id='partition',bounds_size_m=[3,2.8,.1],bounds_center_m=[-1.5,1.4,0])]
    plan,composition=build_plan(ir,optimize(ir),analysis,catalogue,dict(key='plan',model_size=[1000,1000]))
    for obj in plan['objects']:
        if obj['key']=='partition':continue
        assert obj['scale'][0]==obj['scale'][1]==obj['scale'][2]
        assert .8<=obj['scale'][0]<=1.25
    assert composition['architecture']['walls'][0]['partition']
    assert composition['architecture']['walls'][0]['openings'][0]['kind']=='door'


def test_architecture_snaps_joint_without_moving_aperture_to_module_centre():
    from hdrp_agent.floorplan import architecture
    ir=fixture();ir['walls'].append(dict(object_key='north',start=[.05,.1],end=[.505,.1],rooms=['left']))
    result=architecture(ir,10,8)
    assert result['walls'][0]['start_m']==result['walls'][1]['end_m']
    assert result['walls'][0]['openings'][0]['start']==.7


def test_shape_mismatch_is_not_repaired_by_stretching():
    from hdrp_agent.floorplan import correct_native
    plan=dict(objects=[dict(key='bed',scale=[1,1,1],position_m=[0,0,0])])
    measured=dict(coverage_complete=True,per_object=dict(bed=dict(actual_bounds=[.3,.4,.7,.6],target_bounds=[.4,.3,.6,.7],max_edge_error=.1)))
    assert correct_native(plan,dict(screen_width_m=10,screen_height_m=8),measured,[]) is None


def test_native_grid_uses_full_modules_and_does_not_follow_pixel_corrections():
    from hdrp_agent.native_layout import compile_grid, arrange
    from hdrp_agent.floorplan import correct_native
    ir=fixture()
    analysis=dict(objects=[dict(key=o['object_key'],asset_id=o['object_key']) for o in ir['objects']])
    catalogue=[dict(asset_id='bed',bounds_size_m=[2,1,1]),dict(asset_id='cabinet',bounds_size_m=[1,2,.5])]
    grid,width,height=compile_grid(ir,analysis,catalogue,1)
    for room in grid['rooms']:
        b=room['bounds']
        assert (b[2]-b[0])*width==pytest.approx(round((b[2]-b[0])*width))
        assert (b[3]-b[1])*height/3==pytest.approx(round((b[3]-b[1])*height/3))
    fit=arrange(grid,width,height)
    assert fit['metrics']['collisions']==0
    assert fit['metrics']['outside_room']==0
    assert correct_native({},dict(layout_policy='native_prefab_assembly'),{},[]) is None


def test_native_assembly_rejects_impossible_fit_without_shrinking():
    from hdrp_agent.native_layout import arrange
    ir=fixture();ir['objects'][0]['bounds']=[.01,.01,.99,.99]
    with pytest.raises(AgentError,match='native placement'):
        arrange(ir,8,6)


def test_distinct_segments_share_prefab_binding_and_keep_their_openings():
    from hdrp_agent.floorplan import architecture
    ir=fixture()
    ir['walls'][0]['segment_key']='partition-a'
    ir['walls'][0]['end']=[.5,.5]
    ir['walls'].append(dict(object_key='partition',segment_key='partition-b',start=[.5,.5],end=[.5,.9],rooms=['left','right']))
    ir['openings'][0]['wall_key']='partition-b'
    assert validate_observation(ir,{'bed','cabinet','partition'})==ir
    built=architecture(ir,12,10)['walls']
    assert [len(w['openings']) for w in built]==[0,1]
    assert built[0]['segment_key']!=built[1]['segment_key']
    ir['walls'][1]['segment_key']='partition-a'
    with pytest.raises(AgentError,match='segment_key values must be unique'):validate_observation(ir,{'bed','cabinet','partition'})


def test_extraction_repairs_completed_topology_without_replaying_unknown_calls(monkeypatch):
    from hdrp_agent.floorplan import extract
    from hdrp_agent.providers import meta_responses
    from types import SimpleNamespace
    monkeypatch.setattr(meta_responses,'spark_request',lambda prompt,images,schema:prompt)
    good=fixture();good['objects'].append(dict(object_key='partition',room_key=None,role='wall',bounds=[.49,.1,.51,.9],yaw_deg=0,confidence=.9));bad=deepcopy(good);bad['openings'][0]['wall_key']='absent'
    responses=iter([dict(value=bad,call_id='bad'),dict(value=good,call_id='good')]);prompts=[];records=[]
    def send(prompt,schema):prompts.append(prompt);return next(responses)
    result=extract(SimpleNamespace(send=send),SimpleNamespace(read=lambda _:b'image'),[dict(artifact_hash='h')],dict(objects=[dict(key=o['object_key'],asset_id='a') for o in good['objects']]),[],[],'test',on_response=lambda r,e:records.append((r['call_id'],e)))
    assert result['value']==good and len(prompts)==2
    assert 'Rejected observation' in prompts[1] and 'absent' in prompts[1]
    assert len(records)==3 and records[1][1]
