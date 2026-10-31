"""Evaluator-only synthetic fixtures. Never imported by application code."""
from copy import deepcopy
import numpy as np
from hdrp_agent.reference_geometry import rotation,rotation_euler
from hdrp_agent.reference_metrics import SceneRaster


def generate(case):
    truth=dict(objects=[dict(key='platform',asset_id=None,primitive='cube',position_m=[0,-.1,0],rotation_deg=[0,0,0],scale=[3,.2,3]),dict(key='prop',asset_id=None,primitive='cube',position_m=[.3,.5,.1],rotation_deg=[0,23,0],scale=[.3,1,.4])],lights=[dict(intensity=1000)])
    if case['occluder']:
        truth['objects'].append(dict(key='occluder',asset_id=None,primitive='cube',position_m=[.2,.5,-.3],rotation_deg=[0,0,0],scale=[.2,1,.1]))
    candidate=deepcopy(truth);r=rotation([0,case['yaw_error_deg'],0]);shift=np.asarray(case['translation_error_m'])
    for item in candidate['objects']:
        item['position_m']=(r@np.asarray(item['position_m'])+shift).tolist()
        item['rotation_deg']=rotation_euler(r@rotation(item['rotation_deg']))
    candidate['lights'][0]['intensity']*=case['light_multiplier']
    views=[dict(key=f'view-{i}',position_m=p,rotation_deg=a,fov_deg=50) for i,(p,a) in enumerate([([-4,3,-4],[25,45,0]),([4,3,-4],[25,-45,0]),([0,5,-4],[48,0,0])])]
    raster=SceneRaster([])
    observations=[dict(calibration=v,reference_ids=raster.render(truth,v,(160,120))[0],candidate_ids=raster.render(candidate,v,(160,120))[0]) for v in views]
    return dict(inputs=dict(candidate=candidate,observations=observations),expected=dict(reference=truth,configuration=deepcopy(case)))
