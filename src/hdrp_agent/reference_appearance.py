"""Matched native appearance measurements; control views remain evaluator-only."""
import hashlib
import numpy as np
from PIL import Image
from .domain import fingerprint
from .reference_metrics import appearance_regions,assess_appearance


def measure_capture_pair(reference,candidate,analysis,*,noise=None):
    original={r['camera_key']:r for r in reference['statics']};actual={r['camera_key']:r for r in candidate['statics']}
    views={};controls={}
    for key,record in original.items():
        if key not in actual:continue
        paths=[reference['directory']/record['file'],candidate['directory']/actual[key]['file']]
        pixels=[]
        for path in paths:
            with Image.open(path) as image:pixels.append(np.asarray(image.convert('RGB'),dtype=float)/255)
        a,b=pixels;regions={};h,w=a.shape[:2]
        if record['role']=='work':
            for item in analysis['objects']:
                box=next((v['bbox_xyxy'] for v in item['view_boxes'] if v['view_key']==key),None)
                if box:
                    x0,y0,x1,y1=[round(v*d) for v,d in zip(box,[w,h,w,h])]
                    mask=np.zeros((h,w),bool);mask[max(0,y0):min(h,y1),max(0,x0):min(w,x1)]=True;regions[item['key']]=mask
        measured=appearance_regions(a,b,regions)
        measured['frame_hashes']=[hashlib.sha256(p.read_bytes()).hexdigest() for p in paths]
        (controls if record['role']=='control' else views)[key]=measured
    a,b=reference['request'],candidate['request']
    native_protocols=[c['result'].get('render_protocol') for c in [reference,candidate]]
    comparable=a['conditions_hash']==b['conditions_hash'] and a['inspection_hash']==b['inspection_hash']
    protocol_qualified=comparable and all(native_protocols) and native_protocols[0]==native_protocols[1] and native_protocols[0].get('render_path')=='native_gameview' and native_protocols[0].get('exposure_mode')=='Fixed' and native_protocols[0].get('anti_aliasing')=='None' and native_protocols[0].get('dynamic_resolution') is False
    noise_valid=bool(noise and noise['conditions_hash']==a['conditions_hash'] and noise['inspection_hash']==a['inspection_hash'])
    return dict(version=b['version_id'],stage='after_native_capture',work_views=views,control_views=controls,capture_conditions_comparable=comparable,protocol_qualified=protocol_qualified,reference_protocol_hash=fingerprint(native_protocols[0]) if native_protocols[0] else None,candidate_protocol_hash=fingerprint(native_protocols[1]) if native_protocols[1] else None,noise_bound=noise['noise_bound'] if noise_valid else None,noise_evidence_hash=fingerprint(noise) if noise_valid else None,limits='Native GameView comparison only; missing camera protocol evidence prevents appearance qualification. Editor inspection images never qualify this gate.')


def assess_capture_appearance(before,after):
    issues=[]
    if not after['protocol_qualified']:issues.append(dict(kind='capture_protocol_unqualified'))
    old_error=np.mean([v['global_metrics']['luminance_mae'] for v in before['work_views'].values()]) if before['work_views'] else None
    new_error=np.mean([v['global_metrics']['luminance_mae'] for v in after['work_views'].values()]) if after['work_views'] else None
    if old_error is None or new_error is None or new_error>=old_error-(after['noise_bound'] or 0):issues.append(dict(kind='no_appearance_gain'))
    controls={key:dict(before=value['global_metrics']['luminance_mae'],after=after['control_views'].get(key,{}).get('global_metrics',{}).get('luminance_mae')) for key,value in before['control_views'].items()}
    for key,previous in before['work_views'].items():
        current=after['work_views'].get(key)
        if current is None:issues.append(dict(kind='appearance_view_missing',view_key=key));continue
        _,local=assess_appearance(previous,current,reference_protocol=after['reference_protocol_hash'],candidate_protocol=after['candidate_protocol_hash'],controls=controls,noise_bound=after['noise_bound'])
        issues.extend(dict(view_key=key,**issue) if 'view_key' not in issue else issue for issue in local if issue['kind']!='no_appearance_gain')
        if current['global_metrics']['luminance_mae']>previous['global_metrics']['luminance_mae']+(after['noise_bound'] or 0):issues.append(dict(kind='appearance_view_regression',view_key=key))
    return not issues,issues
