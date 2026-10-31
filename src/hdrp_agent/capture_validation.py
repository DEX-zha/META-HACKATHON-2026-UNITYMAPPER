"""Compare measured evidence only; temporal warmup never implies stability."""
import hashlib
import json
import struct
from copy import deepcopy
from pathlib import Path

import numpy as np
from PIL import Image

from .config import contained
from .domain import AgentError


def read_capture(directory):
    directory=Path(directory).resolve()
    request=json.loads((directory/'request.json').read_text())
    result=json.loads((directory/'manifest.json').read_text())
    proof=json.loads((directory/'editor-proof.json').read_text())
    if result['status']!='complete' or result['render_ready'] is not True:raise AgentError('CAPTURE_UNSTABLE','Capture did not finish rendering')
    for key in ['capture_id','version_id','inspection_hash','conditions_hash']:
        if result[key]!=request[key]:raise AgentError('STALE_VERSION','Capture belongs to another request or version')
    if proof['scene_version_after']!=request['version_id'] or proof['manifest_hash_after']!=request['scene_manifest_hash']:raise AgentError('STALE_VERSION','Scene or visual dependencies changed during capture')
    frames=result['frames']
    statics=[f for f in frames if f['camera_key']!=request['plan']['path_key']]
    plan=request['plan'];work=plan['work_views'];control=plan['control_views'];keys=[p['key'] for p in work+control]
    if len(work)<3 or len(work)>(8 if request.get('preserve_camera_settings') else 3) or len(control)!=2 or len(keys)!=len(set(keys)) or plan['path_key'] in keys:raise AgentError('INVALID_MEDIA','Capture viewpoints exceed the registered bounds or contain duplicate keys')
    expected={p['key']:role for role in ['work','control'] for p in plan[role+'_views']}
    if len(statics)!=len(expected) or {f['camera_key']:f['role'] for f in statics}!=expected:raise AgentError('MISSING_FRAME','Every registered work and control view is required')
    for frame in frames:
        path=contained(directory,directory/frame['file'])
        if not path.is_file():raise AgentError('MISSING_FRAME','Original capture frame is missing')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=proof['frame_hashes'].get(frame['file']):raise AgentError('HASH_MISMATCH','Capture frame bytes changed')
        with Image.open(path) as image:
            if image.size!=(1280,720):raise AgentError('INVALID_MEDIA','Capture resolution changed')
    clip=[f for f in frames if f['camera_key']==request['plan']['path_key']]
    if request['include_clip'] and sorted(f['frame_index'] for f in clip)!=list(range(round(request['plan']['duration_seconds']*request['plan']['fps']))):raise AgentError('MISSING_FRAME','Clip frame sequence is incomplete')
    return dict(directory=directory,request=request,result=result,proof=proof,statics=statics,clip=clip)


def comparable(before,after,*,requires_bake=False):
    a,b=before['request'],after['request']
    if a['conditions_hash']!=b['conditions_hash'] or a['inspection_hash']!=b['inspection_hash']:return False,'Capture conditions or inspection plan differ'
    if requires_bake and any(x['request'].get('bake_status')!='complete' for x in [before,after]):return False,'Completed current-version GPU bake proof is missing'
    return True,None


def luminance(path):
    with Image.open(path) as image:rgb=np.asarray(image.convert('RGB'),dtype=np.float64)/255
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    return linear@np.array([.2126,.7152,.0722])


def repeatability(before,after,threshold=.01):
    if threshold!=.01:raise AgentError('CRITERIA_FROZEN','Repeatability threshold is fixed before trials')
    valid,reason=comparable(before,after)
    if not valid:return dict(stable=False,reason=reason,errors={})
    if before['request']['version_id']!=after['request']['version_id']:return dict(stable=False,reason='Witness versions differ',errors={})
    by_key={f['camera_key']:f for f in after['statics']}
    errors={f['camera_key']:float(np.mean(np.abs(luminance(before['directory']/f['file'])-luminance(after['directory']/by_key[f['camera_key']]['file'])))) for f in before['statics']}
    return dict(stable=all(e<=threshold for e in errors.values()),threshold=threshold,errors=errors,reason=None if all(e<=threshold for e in errors.values()) else 'Maximum warmup may be needed; no improvement verdict is admissible')


def unity_render_plan(plan):
    """Unity poses use IEEE-754 single precision; compare that exact projection.

    This is not an epsilon tolerance: only the declared float fields are converted,
    using the same representable values consumed by the qualified runtime DTO.
    """
    result=deepcopy(plan)
    single=lambda value:struct.unpack('!f',struct.pack('!f',value))[0]
    for role in ['work_views','control_views']:
        for view in result[role]:
            for key in ['position_m','rotation_deg']:view[key]=[single(x) for x in view[key]]
            view['fov_deg']=single(view['fov_deg'])
    for key in ['duration_seconds','fixed_ev']:result[key]=single(result[key])
    return result
