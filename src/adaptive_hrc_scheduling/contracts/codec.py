"""Strict JSON boundary and generated Draft 2020-12 structural schemas.

Cross-record rules live in validation.py. Both loading and dumping validate;
constructing a dataclass alone is intentionally not an acceptance boundary.
"""

import json
import math
import re
import types
from dataclasses import fields, is_dataclass
from typing import Annotated, Literal, Union, get_args, get_origin, get_type_hints

ID = Annotated[str, "id"]
Nonnegative = Annotated[float, "nonnegative"]
Positive = Annotated[float, "positive"]
Count = Annotated[int, "positive"]
Index = Annotated[int, "nonnegative"]
Fraction = Annotated[float, "fraction"]
Digest = Annotated[str, "sha256"]
ID_PATTERN = r"^[A-Za-z][A-Za-z0-9_.:-]{0,159}$"


class ContractError(ValueError):
    """Invalid shape, value, unit, reference or cross-record invariant."""


def require(condition, message):
    if not condition:
        raise ContractError(message)


def decode(kind, value, path="$ "):
    origin, args = get_origin(kind), get_args(kind)
    if origin is Annotated:
        result = decode(args[0], value, path)
        for rule in args[1:]:
            if rule == "id":
                require(re.fullmatch(ID_PATTERN, result) is not None, f"{path}: invalid ID")
            elif rule == "sha256":
                require(re.fullmatch(r"[0-9a-f]{64}", result) is not None, f"{path}: digest")
            elif rule == "positive":
                require(result > 0, f"{path}: must be positive")
            elif rule == "nonnegative":
                require(result >= 0, f"{path}: must be nonnegative")
            elif rule == "fraction":
                require(0 <= result < 1, f"{path}: expected [0,1)")
        return result
    if origin in (types.UnionType, Union):
        for branch in args:
            try:
                return decode(branch, value, path)
            except ContractError:
                pass
        raise ContractError(f"{path}: no matching union member")
    if origin is Literal:
        require(any(type(value) is type(x) and value == x for x in args), f"{path}: enum")
        return value
    if origin is tuple:
        require(type(value) is list, f"{path}: expected array")
        return tuple(decode(args[0], x, f"{path}[{i}]") for i, x in enumerate(value))
    if is_dataclass(kind):
        require(type(value) is dict, f"{path}: expected object")
        hints = get_type_hints(kind, include_extras=True)
        require(set(value) == set(hints), f"{path}: missing or unknown fields")
        return kind(**{k: decode(t, value[k], f"{path}.{k}") for k, t in hints.items()})
    if kind is float:
        require(type(value) in (int, float), f"{path}: expected finite number")
        try:
            number = float(value)
        except (OverflowError, ValueError) as error:
            raise ContractError(f"{path}: numeric overflow") from error
        require(math.isfinite(number), f"{path}: nonfinite number")
        return number
    require(type(value) is kind, f"{path}: expected {kind.__name__}")
    return value


def as_data(value):
    if is_dataclass(value):
        return {f.name: as_data(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [as_data(x) for x in value]
    return value


def _pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, f"duplicate JSON member: {key}")
        result[key] = value
    return result


def loads(kind, text, *, config=None):
    from .validation import validate

    try:
        value = json.loads(text, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as error:
        raise ContractError(str(error)) from error
    record = decode(kind, value)
    validate(record, config=config)
    return record


def dumps(record, *, config=None):
    from .validation import validate

    checked = decode(type(record), as_data(record))
    validate(checked, config=config)
    return (
        json.dumps(as_data(checked), ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        + "\n"
    )


def schema(kind):
    """Generate structure only; semantic acceptance still requires loads()."""
    definitions = {}

    def visit(t):
        origin, args = get_origin(t), get_args(t)
        if origin is Annotated:
            node = visit(args[0])
            rules = {
                "id": {"pattern": ID_PATTERN},
                "sha256": {"pattern": "^[0-9a-f]{64}$"},
                "positive": {"exclusiveMinimum": 0},
                "nonnegative": {"minimum": 0},
                "fraction": {"minimum": 0, "exclusiveMaximum": 1},
            }
            for rule in args[1:]:
                node.update(rules[rule])
            return node
        if origin in (types.UnionType, Union):
            return {"anyOf": [visit(x) for x in args]}
        if origin is Literal:
            return {"enum": list(args)}
        if origin is tuple:
            return {"type": "array", "items": visit(args[0])}
        if is_dataclass(t):
            if t.__name__ not in definitions:
                definitions[t.__name__] = {}
                hints = get_type_hints(t, include_extras=True)
                definitions[t.__name__] = {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {k: visit(v) for k, v in hints.items()},
                    "required": list(hints),
                }
            return {"$ref": f"#/$defs/{t.__name__}"}
        return {
            "type": {
                str: "string",
                float: "number",
                int: "integer",
                bool: "boolean",
                type(None): "null",
            }[t]
        }

    root = visit(kind)
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": kind.__name__,
        "$comment": "Structural schema only. Python semantic validation is mandatory.",
        **root,
        "$defs": definitions,
    }
