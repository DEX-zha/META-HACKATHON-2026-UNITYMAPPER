import json
from pathlib import Path

import jsonschema
import pytest
from openapi_spec_validator import validate

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "specs/003-hdrp-scene-agent/contracts"
DOMAIN = json.loads((CONTRACTS / "domain.schema.json").read_text())
API = json.loads((CONTRACTS / "http-api.openapi.json").read_text())


def schema(name):
    return {"$schema": DOMAIN["$schema"], "$defs": DOMAIN["$defs"], "$ref": f"#/$defs/{name}"}


def test_domain_metaschema():
    jsonschema.Draft202012Validator.check_schema(DOMAIN)


def test_openapi_specification():
    validate(API)


def test_shared_schema_definitions():
    encoded = json.dumps(API["components"]["schemas"]).replace("#/components/schemas/", "#/$defs/")
    assert json.loads(encoded) == DOMAIN["$defs"]


def test_real_fixture_payloads():
    for name, path in [("Brief", "fixtures/briefs/room.json"), ("InspectionPlan", "fixtures/inspection-plans/room.json")]:
        jsonschema.validate(json.loads((ROOT / path).read_text()), schema(name))


@pytest.mark.parametrize("payload", [
    {"id": "a", "kind": "artifact", "target": "wall", "method": "arbitrary code", "minimum": None, "maximum": 1, "unit": "normalized", "required": True},
    {"reason": "stop", "execute_script": "unsafe"},
    {"reason": 123},
])
def test_invalid_payloads_rejected(payload):
    model = "Criterion" if "kind" in payload else "StopRequest"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema(model))
