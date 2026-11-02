import json
import pytest
from hdrp_agent.direct_room import choose_pair,validate_action,native_step
from hdrp_agent.domain import AgentError


def test_pair_selection_requires_same_group_and_prefers_actual_desk_chair():
    items=[dict(id='sofa1',group_id='lounge'),dict(id='table1',group_id='lounge'),dict(id='chair1',group_id='work'),dict(id='desk1',group_id='work')]
    assert choose_pair(items)==['chair1','desk1']
    assert choose_pair([items[2],items[1]]) is None


def test_model_cannot_move_other_room_furniture():
    action=dict(action='move',summary='Move chair',target_id='wardrobe',position=[1,0,2],yaw=90,look_at=[0,0,0],fov=65)
    with pytest.raises(AgentError):validate_action(action,['chair','desk'])
    action['target_id']='chair'
    assert validate_action(action,['chair','desk'])==action


def test_native_command_never_replays_an_uncertain_step(tmp_path):
    (tmp_path/'command-0000.json').write_text('{"action":"move"}')
    with pytest.raises(AgentError,match='no replay'):native_step(tmp_path,0,'v1',dict(action='move'))
    assert json.loads((tmp_path/'command-0000.json').read_text())==dict(action='move')


def test_report_escapes_model_text(tmp_path):
    from hdrp_agent.direct_room import report
    report(tmp_path,[dict(label='Model <script>',action=dict(summary='<script>unsafe</script>'),result=dict(error='<img onerror=bad>'))])
    page=(tmp_path/'report.html').read_text()
    assert '<script>' not in page and '&lt;script&gt;' in page
    assert '<img onerror' not in page
