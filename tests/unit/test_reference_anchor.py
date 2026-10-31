from copy import deepcopy
import hashlib
import io
import numpy as np
import pytest
from PIL import Image
from hdrp_agent.reference_metrics import SceneRaster,GeometryEvaluator,primitive_mesh
from hdrp_agent.reference_pose import fit_global_anchor
from hdrp_agent.reference_schedule import default_policy


class Images:
    def __init__(self):self.data={}
    def put(self,data):key=hashlib.sha256(data).hexdigest();self.data[key]=data;return key
    def read(self,key):return self.data[key]


def fixture(height=0):
    verts,tris=primitive_mesh('cube')[0];verts=verts*np.array([3,.1,3]);geometry=[dict(asset_id='floor-asset',meshes=[dict(vertices=verts.tolist(),triangles=tris.flatten().tolist())])]
    truth=dict(objects=[dict(key='platform',asset_id='floor-asset',primitive=None,position_m=[0,height,0],rotation_deg=[0,0,0],scale=[1,1,1]),dict(key='prop',asset_id=None,primitive='cube',position_m=[.7,height+.55,.2],rotation_deg=[0,0,0],scale=[.3,1,.3])])
    cameras=[([-4,3,-4],[25,45,0]),([4,3,-4],[25,-45,0]),([0,5,-4],[48,0,0])];frames=[];segments=[];artifacts=Images();raster=SceneRaster(geometry)
    for index,(p,r) in enumerate(cameras):
        view=dict(key=f'view-{index}',position_m=p,rotation_deg=r,fov_deg=50);frame=dict(key=view['key'],calibration=view,model_size=[320,240]);ids,_=raster.render(truth,view,(320,240));mask=ids==0;y,x=np.where(mask);rect=[x.min(),y.min(),x.max()+1,y.max()+1];cropped=Image.fromarray((mask*255).astype('uint8')).crop(rect);out=io.BytesIO();cropped.save(out,format='PNG')
        frames.append(frame);segments.append(dict(object_key='platform',view_key=view['key'],selection=dict(bbox_xyxy=[v/d for v,d in zip(rect,[320,240,320,240])],confidence=1,mask_hash=artifacts.put(out.getvalue()))))
    evaluator=GeometryEvaluator(frames,segments,geometry,artifacts,width=320)
    evaluator.fixture_inputs=(frames,segments,geometry,artifacts)
    return truth,evaluator


@pytest.mark.parametrize('error',[-.23,.11])
def test_anchor_recovers_image_height_and_preserves_relative_structure(error):
    expected,evaluator=fixture();initial=deepcopy(expected)
    for o in initial['objects']:o['position_m'][1]+=error
    result,proof=fit_global_anchor(initial,evaluator,default_policy())
    assert proof['accepted'] and abs(result['objects'][0]['position_m'][1])<.006
    assert np.allclose(np.array(result['objects'][1]['position_m'])-result['objects'][0]['position_m'],np.array(expected['objects'][1]['position_m'])-expected['objects'][0]['position_m'])
    assert proof['source_transforms_used'] is False and result['objects'][0]['scale']==[1,1,1]


def test_unobservable_anchor_does_not_invent_height_and_limit_is_explicit():
    plan,evaluator=fixture();evaluator.observations=dict(list(evaluator.observations.items())[:1]);result,proof=fit_global_anchor(plan,evaluator,default_policy());assert result==plan and proof['reason']=='no_observable_platform_in_three_views'
    plan,evaluator=fixture();policy=default_policy();policy['max_local_evaluations']=1;_,proof=fit_global_anchor(plan,evaluator,policy);assert proof['stop_reason']=='local_evaluation_limit'


def test_repeated_views_do_not_establish_depth_or_anchor_observability():
    plan,evaluator=fixture();first=next(iter(evaluator.observations.values()))
    evaluator.observations={str(i):deepcopy(first) for i in range(3)}
    assert not evaluator.measure(plan,'native-v1')['per_object']['platform']['covered']
    result,proof=fit_global_anchor(plan,evaluator,default_policy())
    assert result==plan and proof['reason']=='no_observable_platform_in_three_views'


def test_legacy_xz_heuristic_cannot_correct_an_injected_vertical_group_bias():
    from hdrp_agent.reference_pose import fit_mask_poses
    truth,evaluator=fixture();candidate=deepcopy(truth)
    for item in candidate['objects']:item['position_m'][1]-=.23
    legacy,proof=fit_mask_poses(candidate,*evaluator.fixture_inputs)
    assert proof and abs(legacy['objects'][0]['position_m'][1]-truth['objects'][0]['position_m'][1])>.2


def test_small_silhouette_is_missing_evidence_not_perfect_or_failed_match():
    plan,evaluator=fixture();first=next(iter(evaluator.observations.values()))
    # Re-ingest a high-confidence mask with only nine pixels of horizontal extent.
    image=Image.fromarray(np.full((31,9),255,dtype='uint8'));out=io.BytesIO();image.save(out,format='PNG');images=Images();key=images.put(out.getvalue())
    frame=dict(key='tiny',calibration=first['view'],model_size=[1280,720])
    segment=dict(object_key='platform',view_key='tiny',selection=dict(confidence=.99,bbox_xyxy=[.5,.5,.5+9/1280,.5+31/720],mask_hash=key))
    small=GeometryEvaluator([frame],[segment],[],images,width=1280)
    measured=small.measure(plan,'native-version')
    assert measured['per_object']['platform']['mean_iou'] is None
    assert measured['excluded_masks'][0]['reason']=='insufficient_mask_pixel_extent'


def test_truncated_masks_can_inform_residual_but_cannot_establish_full_coverage():
    plan,original=fixture();frames,segments,geometry,artifacts=original.fixture_inputs;segments=deepcopy(segments)
    for segment in segments:segment['selection']['bbox_xyxy'][0]=0
    evaluator=GeometryEvaluator(frames,segments,geometry,artifacts,width=320);result=evaluator.measure(plan,'native')
    assert result['per_object']['platform']['mean_iou'] is not None
    assert not result['per_object']['platform']['covered'] and not result['fidelity_verified']
    assert 'truncated_masks_do_not_establish_full_coverage' in result['per_object']['platform']['missing_reasons']


def test_anchor_opens_observable_tilt_without_changing_scales():
    from hdrp_agent.reference_support_graph import SupportGraph
    truth,evaluator=fixture();graph=SupportGraph(truth,[dict(object_key='prop',support_key='platform')])
    candidate=graph.transform_group(truth,'platform',[0,0,0],rotation_deg=[5,0,0])
    result,proof=fit_global_anchor(candidate,evaluator,default_policy())
    assert proof['accepted'] and abs(result['objects'][0]['rotation_deg'][0])<2
    assert not proof['orientation_uniqueness_verified'] and not proof['scale_changed']
