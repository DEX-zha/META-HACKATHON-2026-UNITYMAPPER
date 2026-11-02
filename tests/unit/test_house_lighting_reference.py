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
