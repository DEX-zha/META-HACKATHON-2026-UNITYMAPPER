import json
import hashlib

import pytest
from PIL import Image

from hdrp_agent.capture_validation import read_capture, repeatability
from hdrp_agent.domain import AgentError
from hdrp_agent.media import encode_clip


def witness(root):
    root.mkdir();poses=[dict(key=f'view-{i}') for i in range(5)]
    request=dict(capture_id='capture',version_id='version',inspection_hash='inspection',conditions_hash='conditions',scene_manifest_hash='manifest',include_clip=False,plan=dict(work_views=poses[:3],control_views=poses[3:],path_key='orbit',fps=24,duration_seconds=6))
    frames=[];hashes={}
    for i,pose in enumerate(poses):
        name=pose['key']+'.png';Image.new('RGB',(1280,720),(100,100,100)).save(root/name)
        frames.append(dict(file=name,role='work' if i<3 else 'control',camera_key=pose['key'],frame_index=0))
        hashes[name]=hashlib.sha256((root/name).read_bytes()).hexdigest()
    (root/'request.json').write_text(json.dumps(request))
    (root/'manifest.json').write_text(json.dumps(dict(capture_id='capture',version_id='version',inspection_hash='inspection',conditions_hash='conditions',status='complete',render_ready=True,frames=frames)))
    (root/'editor-proof.json').write_text(json.dumps(dict(scene_version_after='version',manifest_hash_after='manifest',frame_hashes=hashes)))
    return root


def test_repeated_witness_and_tampered_frame(tmp_path):
    a,b=witness(tmp_path/'a'),witness(tmp_path/'b')
    assert repeatability(read_capture(a),read_capture(b))['stable']
    Image.new('RGB',(1280,720),'white').save(b/'view-0.png')
    with pytest.raises(AgentError,match='changed'):read_capture(b)


def test_changed_conditions_and_missing_frames_cannot_show_gain(tmp_path):
    a,b=witness(tmp_path/'a'),witness(tmp_path/'b')
    first,second=read_capture(a),read_capture(b);second['request']['conditions_hash']='different'
    assert not repeatability(first,second)['stable']
    (b/'view-1.png').unlink()
    with pytest.raises(AgentError):read_capture(b)


def test_encoder_refuses_missing_index_before_invoking_ffmpeg(tmp_path):
    with pytest.raises(AgentError,match='missing'):encode_clip(tmp_path,[dict(frame_index=1,file='frame.png')])


def test_unity_float_projection_is_exact_and_does_not_mask_camera_changes():
    from copy import deepcopy
    from hdrp_agent.domain import WORKSPACE,fingerprint
    from hdrp_agent.capture_validation import unity_render_plan
    import json
    source=json.loads((WORKSPACE/'fixtures/inspection-plans/room.json').read_text())
    rendered=unity_render_plan(source)
    assert rendered['work_views'][0]['position_m'][1]==1.600000023841858
    assert source['work_views'][0]['position_m'][1]==1.6
    assert unity_render_plan(rendered)==rendered
    moved=deepcopy(rendered);moved['work_views'][0]['position_m'][1]+=1e-7
    assert fingerprint(moved)!=fingerprint(rendered)
