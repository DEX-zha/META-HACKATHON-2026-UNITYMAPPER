import json
import pytest
from PIL import Image
from hdrp_agent.house_atlas import inspect_atlas
from hdrp_agent.domain import AgentError


def test_atlas_keeps_unqualified_views_honest_and_rejects_paths(tmp_path):
    Image.new('RGB',(1280,720)).save(tmp_path/'room-0.png')
    atlas=dict(schema_version='house-atlas.v1',source_sha256='a'*64,status='complete',source_unchanged=True,rooms=[dict(name='room')],instances=[dict(room='room')],captures=[dict(key='room-0',file='room-0.png',coverage_qualified=False)])
    (tmp_path/'atlas.json').write_text(json.dumps(atlas))
    out=inspect_atlas(tmp_path);assert out['visual_qualified'] is False
    assert out['rooms'][0]['instances']==1 and out['captures'][0]['sha256']
    assert 'framing requires qualification' in (tmp_path/'index.html').read_text()
    atlas['captures'][0]['file']='../secret.png';(tmp_path/'atlas.json').write_text(json.dumps(atlas))
    with pytest.raises(AgentError):inspect_atlas(tmp_path)
