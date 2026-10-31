"""Strict transport DTOs using the reviewed JSON Schema as their single source.

Pydantic owns request/error integration; JSON Schema validates all fields without
coercion. Relational and Unity-specific bounds are enforced before dispatch too.
"""

from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from jsonschema import Draft202012Validator, FormatChecker, validators
from pydantic import ConfigDict, RootModel, model_validator

WORKSPACE = Path(__file__).resolve().parents[2]
CONTRACTS = WORKSPACE / "specs/003-hdrp-scene-agent/contracts"
DOMAIN = json.loads((CONTRACTS / "domain.schema.json").read_text())
StrictValidator = validators.extend(Draft202012Validator, type_checker=Draft202012Validator.TYPE_CHECKER.redefine('integer', lambda checker, value: type(value) is int))


class AgentError(Exception):
    def __init__(self, code: str, message: str, status: int = 409, command_id: str | None = None):
        super().__init__(message)
        self.code, self.message, self.status, self.command_id = code, message, status, command_id

    def as_dict(self):
        return {"code": self.code, "message": self.message, "retryable": False, "command_id": self.command_id}


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def fingerprint_bytes(value: Any) -> bytes:
    def normalized(item):
        if isinstance(item, float):
            if not math.isfinite(item): raise ValueError('Non-finite hash input')
            if item == 0: return '0'
            number = format(Decimal(str(item)), 'f')
            return number.rstrip('0').rstrip('.') if '.' in number else number
        if isinstance(item, dict):
            return '{' + ','.join(canonical(k)+':'+normalized(v) for k,v in sorted(item.items())) + '}'
        if isinstance(item, list): return '['+','.join(normalized(v) for v in item)+']'
        return canonical(item)
    return normalized(value).encode()


def fingerprint(value: Any) -> str:
    return hashlib.sha256(fingerprint_bytes(value)).hexdigest()


@lru_cache
def validator(name: str) -> Draft202012Validator:
    return StrictValidator({"$defs": DOMAIN["$defs"], "$ref": f"#/$defs/{name}"}, format_checker=FormatChecker())


def bounds(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Numeric value must be finite and in [{low}, {high}]")


PROPERTY_BOUNDS={"intensity_lumen": (0, 100000), "illuminance_lux": (0, 150000), "temperature_kelvin": (1000, 20000), "volumetric_dimmer": (0, 1), "mean_free_path_m": (1, 1000), "anisotropy": (-0.9, 0.9), "emission_nits": (0, 1000), "scale_in_lightmap": (0.1, 4), "lightmap_uv_pack_margin": (0.00390625, 0.0625)}


def operation(data):
    op = data["op"]
    if op == "set_transform":
        if all(data[k] is None for k in ["position_m", "rotation_deg", "scale"]):
            raise ValueError("Transform must change at least one field")
        for key, limit in [("position_m", 100), ("rotation_deg", 360)]:
            if data[key] is not None:
                for value in data[key]: bounds(value, -limit, limit)
    if op in {"set_light", "set_fog", "set_gi", "set_material"}:
        key, value = data["property"], data["value"]
        if key in {"use_volumetric", "enable_volumetric_fog", "contribute_gi"}:
            if type(value) is not bool: raise ValueError("Boolean property requires a boolean")
        elif key == "base_color_rgba":
            if not isinstance(value, list) or len(value) != 4: raise ValueError("RGBA requires four values")
            for v in value: bounds(v, 0, 1)
        else:
            limits = PROPERTY_BOUNDS
            bounds(value, *limits[key])


def semantic(name, data):
    canonical(data)  # Reject non-finite numbers at any depth, including NaN.
    if name in {"Operation", "TransformOperation", "LightOperation", "FogOperation", "MaterialOperation", "GiOperation", "BakeOperation", "CreateOperation", "PrefabOperation"}:
        operation(data)
    if name == "Patch":
        for item in data["operations"]: operation(item)
    if name == "SessionCreate":
        for criterion in data["criteria"]: semantic("Criterion", criterion)
        keys = [c["id"] for c in data["criteria"]]
        if len(keys) != len(set(keys)): raise ValueError("Criterion IDs must be unique")
        semantic("InspectionPlan", data["inspection"])
    if name == "InspectionPlan":
        views = data["work_views"] + data["control_views"]
        keys = [v["key"] for v in views]
        poses = [(tuple(v["position_m"]), tuple(v["rotation_deg"]), v["fov_deg"]) for v in views]
        if len(keys) != len(set(keys)) or len(poses) != len(set(poses)):
            raise ValueError("Work and control cameras must be distinct")
    if name == "Criterion":
        lo, hi = data["minimum"], data["maximum"]
        if lo is not None and hi is not None and lo > hi: raise ValueError("Criterion range is inverted")
        if data["method"] != "artistic_review" and lo is None and hi is None: raise ValueError("Numeric criterion needs a bound")
    if name in {"Command", "ApplyPatchCommand"} and data["kind"] == "apply_patch":
        if data["expected_version"] != data["payload"]["expected_version"] or data["session_id"] != data["payload"]["session_id"]:
            raise ValueError("Command and patch must share version and session")
        semantic("Patch", data["payload"])
    if name == "ModelProposal":
        for item in data["operations"]: operation(item)


class SchemaDTO(RootModel[dict[str, Any]]):
    model_config = ConfigDict(strict=True)
    schema_name: ClassVar[str]

    @model_validator(mode="before")
    @classmethod
    def validate_contract(cls, value):
        errors = list(validator(cls.schema_name).iter_errors(value))
        if errors:
            error = errors[0]
            path = ".".join(map(str, error.absolute_path)) or "payload"
            # Do not include untrusted payload values in the exception/log.
            raise ValueError(f"Invalid {cls.schema_name} at {path}: {error.validator}")
        semantic(cls.schema_name, value)
        return value


@lru_cache
def dto(name: str) -> type[SchemaDTO]:
    if name not in DOMAIN["$defs"]: raise ValueError("Unknown contract")
    return type(name, (SchemaDTO,), {"__module__": __name__, "schema_name": name})


def payload(name: str, value: Any) -> dict:
    return dto(name).model_validate(value).root


for _name in ["SessionCreate", "Session", "ProjectRegister", "ProjectRegistered", "Patch", "Command", "CommandResult", "Budget", "Criterion", "InspectionPlan"]:
    globals()[_name] = dto(_name)
