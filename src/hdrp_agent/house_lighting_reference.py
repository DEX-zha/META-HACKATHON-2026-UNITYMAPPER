"""Provenance-checked native lighting knowledge, distinct from generated evidence."""
import hashlib
import json
from collections import Counter
from pathlib import Path


def unwrap(value):
    return next(iter(value.values())) if isinstance(value,dict) and len(value)==1 else (value or {})


def load_reference(state,project):
    path=Path(state)/'references/clean-day/lighting.json'
    if not path.is_file():return dict(status='unavailable',reason='Native clean-day export required; do not infer settings from an image')
    raw=path.read_bytes();data=json.loads(raw);source=Path(project)/data['source_scene']
    if not source.resolve().is_relative_to(Path(project).resolve()) or not source.is_file() or hashlib.sha256(source.read_bytes()).hexdigest()!=data['source_sha256']:
        return dict(status='stale',reason='Reference scene changed; re-export native settings')
    if not data.get('source_unchanged') or not data.get('active_scene_unchanged'):return dict(status='unqualified',reason='Reference isolation was not verified')
    groups={}
    for light in data['lights']:
        hd=unwrap(light.get('hdrp_serialized'))
        values={k:light.get(k) for k in ['active','type','unit','intensity','range_m','bake_mode','color','temperature_k','use_temperature','shadows','spot_angle','inner_spot_angle']}
        # Unity 6000.3 serializes intensity in native photometric units. The
        # Light.lightUnit field selects an inspector display unit, not the unit
        # of the exported Light.intensity number. Preserve both explicitly.
        values['display_unit']=values['unit']
        values['unit']=light.get('native_unit') or {
            'Directional':'Lux','Box':'Lux','Point':'Candela','Spot':'Candela',
            'Pyramid':'Candela','Rectangle':'Nits','Disc':'Nits','Tube':'Nits',
        }.get(values['type'],'unqualified')
        values['intensity_semantics']='Unity Light.intensity in native units; display_unit is not its numeric unit'
        values['hdrp']={k:hd[k] for k in ['m_AffectDiffuse','m_AffectSpecular','m_VolumetricDimmer','m_ShapeWidth','m_ShapeHeight','m_LightDimmer','m_ShadowDimmer'] if k in hd}
        key=json.dumps(values,sort_keys=True)
        group=groups.setdefault(key,dict(settings=values,instances=[]))
        group['instances'].append({k:light[k] for k in ['hierarchy','position_m','rotation_deg']})
    result=dict(status='native_reference_only',source_scene=data['source_scene'],source_sha256=data['source_sha256'],export_sha256=hashlib.sha256(raw).hexdigest(),unity_version=data['unity_version'],lighting_settings=unwrap(data['lighting_settings']),light_groups=list(groups.values()),volumes=data['volumes'],reflection_probes=data['reflection_probes'],light_probe_groups=[dict(hierarchy=p['hierarchy'],count=p['count']) for p in data['light_probe_groups']],adaptive_probe_volumes=data['adaptive_probe_volumes'],material_shaders=dict(Counter(m['shader'] for m in data['materials'])),limitations=data['limitations'])
    (path.parent/'lighting-context.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
