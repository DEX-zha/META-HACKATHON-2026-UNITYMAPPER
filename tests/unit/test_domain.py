import copy
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from hdrp_agent.domain import payload

ROOT = Path(__file__).resolve().parents[2]


def request():
    return {
        "project_id": "project", "scene_id": "scene", "base_version": "v1", "mode": "inspect",
        "brief": json.loads((ROOT / "fixtures/briefs/room.json").read_text()),
        "inspection": json.loads((ROOT / "fixtures/inspection-plans/room.json").read_text()),
        "criteria": [{"id": "visibility", "kind": "visibility", "target": "wall", "method": "luminance_range", "minimum": 0.1, "maximum": 0.9, "unit": "normalized", "required": True}],
        "max_attempts": 3, "session_timeout_seconds": 1200, "bake_timeout_seconds": 600, "provider_mode": "offline",
    }


def test_session_roundtrip():
    assert payload("SessionCreate", request()) == request()


@pytest.mark.parametrize("field,value", [("max_attempts", True), ("max_attempts", "3"), ("max_attempts", 3.0), ("max_attempts", 4), ("provider_mode", "pretend-live")])
def test_no_coercion_or_limit_bypass(field, value):
    data = request()
    data[field] = value
    with pytest.raises(ValidationError):
        payload("SessionCreate", data)


def test_control_camera_must_be_distinct():
    data = request()
    data["inspection"]["control_views"][0] = copy.deepcopy(data["inspection"]["work_views"][0])
    data["inspection"]["control_views"][0]["key"] = "hidden-but-same-camera"
    with pytest.raises(ValidationError):
        payload("SessionCreate", data)


@pytest.mark.parametrize("value", [True, -1, 100001, float("nan")])
def test_light_value_checked_by_property(value):
    data = {"op": "set_light", "target_id": "light", "property": "intensity_lumen", "value": value}
    with pytest.raises(ValidationError):
        payload("Operation", data)


def test_fog_cannot_silently_clamp_below_hdrp_minimum():
    with pytest.raises(ValidationError):
        payload("Operation", {"op": "set_fog", "target_id": "fog", "property": "mean_free_path_m", "value": 0.1})


def test_transform_must_modify_something():
    with pytest.raises(ValidationError):
        payload("Operation", {"op": "set_transform", "target_id": "box", "position_m": None, "rotation_deg": None, "scale": None})


def test_python_csharp_numeric_fingerprint_vector():
    from hdrp_agent.domain import fingerprint
    assert fingerprint({'z':1.0,'a':.000001})=='ea081c659013c34749ebebb0005d476d8b0d8f99645e3b331453cb4ae7b3a86b'
    assert fingerprint({'n':-0.0})==fingerprint({'n':0})


def test_naive_or_malformed_command_deadline_is_rejected():
    from hdrp_agent.domain import fingerprint
    for date in ['not-a-date','2026-10-28T10:00:00']:
        data={'diagnostic_keys':['lights']}
        with pytest.raises(ValidationError):payload('Command',dict(id='command',session_id='session',kind='inspect',expected_version='version',payload_hash=fingerprint(data),payload=data,deadline_utc=date,bridge_epoch='epoch'))


def test_uv_padding_is_bounded_independently_of_lightmap_scale():
    operation=dict(op='set_gi',target_id='mesh',property='lightmap_uv_pack_margin',value=.03125)
    assert payload('Operation',operation)==operation
    for value in [True,.001,.1,4]:
        with pytest.raises(ValidationError):payload('Operation',dict(operation,value=value))
    with pytest.raises(ValidationError):payload('Operation',dict(operation,property='scale_in_lightmap',value=.03125))
