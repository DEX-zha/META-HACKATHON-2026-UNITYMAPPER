import pytest
from hdrp_agent.domain import AgentError
from hdrp_agent.reference_planner import BUILDING_ROOT, catalogue_context, validate_building_mapping


def room():
    names = ['Floor_6x3', 'WallIn_A_6x_windowtriple', 'WallIn_A_3x_door', 'WallIn_A_6x', 'WallIn_A_3x', 'Sofa_3seat']
    assets = [dict(asset_id=str(i), name=name, path=(BUILDING_ROOT if i < 5 else 'Assets/AtmosphericHouse/Prefabs/Furniture/')+name+'.prefab', bounds_center_m=[0,0,0], bounds_size_m=[1,1,1]) for i,name in enumerate(names)]
    return assets, [dict(key='object-'+a['asset_id'], asset_id=a['asset_id'], primitive=None) for a in assets]


def test_envelope_uses_building_and_furniture_can_use_other_folders():
    assets, objects = room()
    validate_building_mapping(objects, assets)
    context = catalogue_context(assets)
    assert context['path_directories'][context['rows'][0][context['columns'].index('path_directory')]]+'/' == BUILDING_ROOT


@pytest.mark.parametrize('error', ['primitive', 'missing_wall', 'wrong_folder', 'closed_window'])
def test_rejects_incomplete_or_primitive_architecture(error):
    assets, objects = room()
    if error == 'primitive': objects.append(dict(key='support_wall', asset_id=None, primitive='cube'))
    elif error == 'missing_wall': objects.pop(4)
    elif error == 'wrong_folder': assets[1]['path']='Assets/Other/Wall.prefab'
    elif error == 'closed_window': assets[1]['name']='WallIn_A_6x'
    with pytest.raises(AgentError): validate_building_mapping(objects, assets)


def test_camera_facing_away_is_reoriented_without_changing_objects():
    from hdrp_agent.reference_geometry import orient_empty_estimated_views, rotation
    import numpy as np
    plan = dict(objects=[dict(asset_id='floor', position_m=[0,0,0], rotation_deg=[0,0,0], scale=[1,1,1])], estimated_views=[dict(key='reference-0', position_m=[0,10,0], rotation_deg=[-90,0,0], fov_deg=38)])
    result, fixes = orient_empty_estimated_views(plan, [])
    assert fixes and result['objects'] == plan['objects']
    assert (rotation(result['estimated_views'][0]['rotation_deg'])[:,2] @ np.array([0,-10,0])) > 0
    assert plan['estimated_views'][0]['rotation_deg'] == [-90,0,0]
    assert not orient_empty_estimated_views(result, [])[1]
    plan['estimated_views'] = None
    assert orient_empty_estimated_views(plan, []) == (plan, [])
