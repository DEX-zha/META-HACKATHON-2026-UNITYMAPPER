import numpy as np
from hdrp_agent.reference_geometry import rotation,rotation_euler,ray,triangulate,project_points,fit_initial_positions


def test_calibrated_pixel_projection_and_ray_agree_with_unity_axes():
    view=dict(position_m=[1,2,-4],rotation_deg=[17,35,-12],fov_deg=50)
    point=np.array(view['position_m'])+rotation(view['rotation_deg'])@np.array([.4,-.2,5])
    uv,z=project_points([point],view,(1280,720))
    x,y=uv[0]/[1280,720];origin,direction=ray(view,[x,y,x,y],1280/720)
    assert np.dot(direction,(point-origin)/np.linalg.norm(point-origin))>1-1e-12
    assert z[0]==5 and y>.5


def test_triangulation_recovers_known_point_but_rejects_parallel_rays():
    point=np.array([.2,1.17,2.1]);views=[dict(position_m=[x,2,-4],rotation_deg=[0,0,0],fov_deg=50) for x in [-2,0,2]]
    observations=[]
    for v in views:
        uv,_=project_points([point],v,(1280,720));x,y=uv[0]/[1280,720];observations.append((v,[x,y,x,y],1280/720))
    assert np.allclose(triangulate(observations),point,atol=1e-10)
    assert triangulate([observations[0]]*3) is None


def test_rotations_round_trip_even_at_gimbal_lock():
    for euler in [[17,-42,13],[90,25,48],[-90,-72,15],[0,180,0]]:
        assert np.allclose(rotation(rotation_euler(rotation(euler))),rotation(euler),atol=1e-8)


def test_decentred_scaled_pivot_is_not_the_visible_box_centre():
    pivot=np.array([.3,.7,1.4]);euler=[12,40,-8];scale=[2,1,3];centre=[.2,.3,-.1]
    world_centre=pivot+rotation(euler)@(np.array(centre)*scale)
    views=[dict(position_m=[x,2,-4],rotation_deg=[0,0,0],fov_deg=50) for x in [-2,0,2]]
    frames=[];boxes=[]
    for i,view in enumerate(views):
        uv,_=project_points([world_centre],view,(1280,720));x,y=uv[0]/[1280,720]
        frames.append(dict(key=str(i),calibration=view,model_size=[1280,720]))
        boxes.append(dict(view_key=str(i),bbox_xyxy=[x-.02,y-.02,x+.02,y+.02]))
    plan=dict(objects=[dict(key='prop',asset_id='asset',position_m=[0,0,0],rotation_deg=euler,scale=scale)])
    result,proof=fit_initial_positions(plan,dict(objects=[dict(key='prop',view_boxes=boxes)]),frames,[dict(asset_id='asset',bounds_center_m=centre)],[])
    assert np.allclose(result['objects'][0]['position_m'],pivot)
    assert 'occlusion' in proof[0]['limitation']
    # An occluded region centre can be internally consistent yet not the mesh centre.
    biased_centre=world_centre+np.array([0,.08,0])
    for box,view in zip(boxes,views):
        uv,_=project_points([biased_centre],view,(1280,720));x,y=uv[0]/[1280,720];box['bbox_xyxy']=[x-.02,y-.02,x+.02,y+.02]
    biased,_=fit_initial_positions(plan,dict(objects=[dict(key='prop',view_boxes=boxes)]),frames,[dict(asset_id='asset',bounds_center_m=centre)],[])
    assert abs(biased['objects'][0]['position_m'][1]-pivot[1]-.08)<1e-4


def test_native_pose_serialization_removes_matrix_residue_before_hashing():
    from hdrp_agent.reference_geometry import native_pose_precision
    from hdrp_agent.domain import fingerprint
    plan=dict(objects=[dict(position_m=[.020000000000000004,1,2],rotation_deg=[-0.,-2.7370812190272498e-17,-14.000000000000002],scale=[1,1,1])])
    normalized=native_pose_precision(plan)
    assert normalized['objects'][0]['rotation_deg']==[0,0,-14]
    assert normalized['objects'][0]['position_m']==[.02,1,2]
    assert fingerprint(normalized)==fingerprint(native_pose_precision(normalized))
    assert plan['objects'][0]['rotation_deg'][1]!=0
