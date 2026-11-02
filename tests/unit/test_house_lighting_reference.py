import hashlib,json
from hdrp_agent.house_lighting_reference import load_reference


def test_native_reference_needs_matching_source_and_preserves_units(tmp_path):
    project=tmp_path/'project';project.mkdir();scene=project/'day.unity';scene.write_text('source')
    directory=tmp_path/'state/references/clean-day';directory.mkdir(parents=True)
    data=dict(source_scene='day.unity',source_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),source_unchanged=True,active_scene_unchanged=True,unity_version='6',lighting_settings={'LightingSettings':{'bounces':3}},lights=[dict(hierarchy='sun',position_m=[0,1,0],rotation_deg=[30,0,0],unit='Lux',intensity=250,active=True,type='Directional')],volumes=[],materials=[],reflection_probes=[],light_probe_groups=[],adaptive_probe_volumes=[],limitations='Reference only')
    (directory/'lighting.json').write_text(json.dumps(data))
    result=load_reference(tmp_path/'state',project)
    assert result['light_groups'][0]['settings']['unit']=='Lux'
    assert result['lighting_settings']['bounces']==3
    scene.write_text('changed')
    assert load_reference(tmp_path/'state',project)['status']=='stale'


def test_inspector_lumens_do_not_relabel_native_candelas_or_nits(tmp_path):
    project=tmp_path/'project';project.mkdir();scene=project/'day.unity';scene.write_text('source')
    directory=tmp_path/'state/references/clean-day';directory.mkdir(parents=True)
    lights=[dict(hierarchy=kind,position_m=[0,1,0],rotation_deg=[0,0,0],unit='Lumen',intensity=intensity,active=True,type=kind) for kind,intensity in [('Spot',64.45775),('Rectangle',217.029449)]]
    data=dict(source_scene='day.unity',source_sha256=hashlib.sha256(scene.read_bytes()).hexdigest(),source_unchanged=True,active_scene_unchanged=True,unity_version='6000.3',lighting_settings={},lights=lights,volumes=[],materials=[],reflection_probes=[],light_probe_groups=[],adaptive_probe_volumes=[],limitations='Reference only')
    (directory/'lighting.json').write_text(json.dumps(data))
    settings=[g['settings'] for g in load_reference(tmp_path/'state',project)['light_groups']]
    assert [(s['intensity'],s['unit'],s['display_unit']) for s in settings]==[(64.45775,'Candela','Lumen'),(217.029449,'Nits','Lumen')]
