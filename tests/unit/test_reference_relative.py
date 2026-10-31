from copy import deepcopy
import io
import numpy as np
from PIL import Image
from hdrp_agent.reference_metrics import SceneRaster,GeometryEvaluator,primitive_mesh
from hdrp_agent.reference_pose import fit_relative_poses
from hdrp_agent.reference_schedule import default_policy


def calibrated_prop(scale=1,floor_width=3):
    vertices,triangles=primitive_mesh('cube')[0]
    geometry=[dict(asset_id='prop-asset',meshes=[dict(vertices=(vertices*np.array([.12,.3,.12])).tolist(),triangles=triangles.flatten().tolist())])]
    truth=dict(objects=[dict(key='floor',primitive='cube',asset_id=None,position_m=[0,-.05,0],rotation_deg=[0,0,0],scale=[floor_width,.1,floor_width]),dict(key='prop',primitive=None,asset_id='prop-asset',position_m=[0,.15,0],rotation_deg=[0,0,0],scale=[1,1,1])])
    truth['objects'][1]['scale']=[scale]*3
    images={};frames=[];segments=[];raster=SceneRaster(geometry)
    for index,(p,r) in enumerate([([-1,.4,-1],[10,45,0]),([1,.4,-1],[10,-45,0]),([0,.4,-1.4],[10,0,0])]):
        view=dict(position_m=p,rotation_deg=r,fov_deg=35);key=str(index);ids,_=raster.render(truth,view,(320,240));mask=ids==1;y,x=np.where(mask);rect=[x.min(),y.min(),x.max()+1,y.max()+1]
        out=io.BytesIO();Image.fromarray((mask*255).astype('uint8')).crop(rect).save(out,format='PNG');images[key]=out.getvalue()
        frames.append(dict(key=key,calibration=view,model_size=[320,240]));segments.append(dict(object_key='prop',view_key=key,selection=dict(confidence=1,mask_hash=key,bbox_xyxy=[v/d for v,d in zip(rect,[320,240,320,240])])))
    class Store:
        def read(self,key):return images[key]
    return truth,GeometryEvaluator(frames,segments,geometry,Store(),width=320)


def test_relative_solver_moves_toward_nonoverlapping_closeup_without_scale_compensation():
    truth,evaluator=calibrated_prop();initial=deepcopy(truth);initial['objects'][1]['position_m'][0]=.19
    before=evaluator.measure(initial,'v-before')['per_object']['prop']['contour_error_px']
    result,proof=fit_relative_poses(initial,evaluator,[dict(object_key='prop',support_key='floor')],default_policy())
    after=evaluator.measure(result,'v-after')['per_object']['prop']['contour_error_px']
    assert after<before*.3
    assert abs(result['objects'][1]['position_m'][0])<.035
    assert result['objects'][1]['scale']==[1,1,1] and proof['source_transforms_used'] is False


def test_scale_unlock_requires_independent_multiview_shape_evidence_and_frozen_policy():
    from hdrp_agent.reference_scale import fit_evidenced_scale
    truth,evaluator=calibrated_prop(1.1,floor_width=1.5);initial=deepcopy(truth);initial['objects'][1]['scale']=[1,1,1]
    policy=default_policy();result,proof=fit_evidenced_scale(initial,evaluator,initial,policy)
    assert result==initial and proof['reason']=='scale_locked'
    policy['scale_mode']='evidenced';result,proof=fit_evidenced_scale(initial,evaluator,initial,policy)
    assert proof['accepted'] and result['objects'][1]['scale']==[1.1]*3
    assert result['objects'][1]['position_m']==initial['objects'][1]['position_m']
    evaluator.observations=dict(list(evaluator.observations.items())[:2]);result,proof=fit_evidenced_scale(initial,evaluator,initial,policy)
    assert result==initial and not proof['accepted']
