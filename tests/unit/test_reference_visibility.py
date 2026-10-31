import numpy as np
from hdrp_agent.reference_metrics import SceneRaster


def test_shared_depth_hides_the_far_object_instead_of_comparing_full_silhouette():
    base=dict(asset_id=None,primitive='cube',rotation_deg=[0,0,0],scale=[1,1,1])
    plan=dict(objects=[dict(base,key='near',position_m=[0,0,3]),dict(base,key='far',position_m=[0,0,4])])
    view=dict(position_m=[0,0,0],rotation_deg=[0,0,0],fov_deg=50)
    image,status=SceneRaster([]).render(plan,view,(128,128))
    assert image[64,64]==0 and not np.any(image==1) and not status['unsupported_objects']
    plan['objects'][1]['position_m'][0]=.7
    partial,_=SceneRaster([]).render(plan,view,(128,128))
    assert np.any(partial==1) and partial[64,64]==0


def test_near_plane_crossing_and_unsupported_geometry_are_not_certified():
    plan=dict(objects=[dict(key='a',asset_id=None,primitive='cube',position_m=[0,0,.1],rotation_deg=[0,0,0],scale=[1,1,1]),dict(key='b',asset_id='missing',primitive=None,position_m=[0,0,4],rotation_deg=[0,0,0],scale=[1,1,1])])
    _,state=SceneRaster([]).render(plan,dict(position_m=[0,0,0],rotation_deg=[0,0,0],fov_deg=50),(64,64))
    assert state['near_plane_clipping_unqualified'] and state['unsupported_objects']==['b']


def test_symmetric_silhouette_cannot_prove_unique_orientation():
    from copy import deepcopy
    from hdrp_agent.reference_metrics import mask_metrics
    base=dict(objects=[dict(key='cube',asset_id=None,primitive='cube',position_m=[0,0,4],rotation_deg=[0,0,0],scale=[1,1,1])]);other=deepcopy(base);other['objects'][0]['rotation_deg'][1]=180
    view=dict(position_m=[0,0,0],rotation_deg=[0,0,0],fov_deg=50);raster=SceneRaster([])
    a,_=raster.render(base,view,(128,128));b,_=raster.render(other,view,(128,128))
    assert mask_metrics(a==0,b==0)['visible_iou']==1
    assert base['objects'][0]['rotation_deg']!=other['objects'][0]['rotation_deg']
