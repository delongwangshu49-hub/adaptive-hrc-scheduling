"""Strict JSON boundary and generated Draft 2020-12 structural schemas.

Cross-record rules live in validation.py. Both loading and dumping validate;
constructing a dataclass alone is intentionally not an acceptance boundary.
"""

import json
import math
import re
import types
from collections import OrderedDict
from dataclasses import fields, is_dataclass
from functools import lru_cache, wraps
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


@lru_cache(maxsize=256)
def type_hints(kind):
    return get_type_hints(kind, include_extras=True)


_checked_records = OrderedDict()
_json_records = OrderedDict()


def canonical_json(value, *, normalize_numbers=False):
    """Exact compact sorted JSON; reuse only immutable serialized subtrees."""
    return _canonical_json(value, normalize_numbers)[0]


@lru_cache(maxsize=16384, typed=True)
def _json_atom(value):
    return json.dumps(value, separators=(",", ":"), allow_nan=False)


@lru_cache(maxsize=256)
def _json_fields(kind):
    return tuple((f.name, json.dumps(f.name)) for f in sorted(fields(kind), key=lambda f: f.name))


def _canonical_json(value, normalize):
    if type(value) in (str, int, float, bool, type(None)):
        if normalize and type(value) is float and value.is_integer():
            value = int(value)
        return _json_atom(value), True
    key = (id(value), normalize)
    previous = _json_records.get(key)
    if previous is not None and previous[0] is value:
        _json_records.move_to_end(key)
        return previous[1], True
    if is_dataclass(value):
        parts = [
            (encoded, _canonical_json(getattr(value, name), normalize))
            for name, encoded in _json_fields(type(value))
        ]
        result = "{" + ",".join(k + ":" + v for k, (v, _) in parts) + "}"
        immutable = type(value).__dataclass_params__.frozen and all(ok for _, (_, ok) in parts)
    elif type(value) in (tuple, list):
        parts = [_canonical_json(x, normalize) for x in value]
        result = "[" + ",".join(v for v, _ in parts) + "]"
        immutable = type(value) is tuple and all(ok for _, ok in parts)
    elif type(value) is dict:
        result = (
            "{"
            + ",".join(
                json.dumps(k) + ":" + _canonical_json(value[k], normalize)[0] for k in sorted(value)
            )
            + "}"
        )
        immutable = False
    else:
        if normalize and type(value) is float and value.is_integer():
            value = int(value)
        return _json_atom(value), type(value) in (
            str,
            int,
            float,
            bool,
            type(None),
        )
    if immutable:
        _json_records[key] = (value, result)
        if len(_json_records) > 32768:
            _json_records.popitem(last=False)
    return result, immutable


def checked(record):
    """Strict native structural decoding, reusing frozen, immutable subtrees.

    Equivalent to decode(type(record), as_data(record)). Entries retain their
    source object and are identity checked; mutable leaves never enter the cache.
    Domain/relational validation remains the caller's responsibility.
    """
    return _checked(type(record), record, "$ ")[0]


def _checked(kind, value, path):
    if type(value) in (str, int, float, bool, type(None)):
        try:
            return _checked_atom(kind, value, type(value)), True
        except ContractError:
            # Failed checks retain the caller's full diagnostic field path.
            return decode(kind, value, path), True
    key = (kind, id(value))
    prior = _checked_records.get(key)
    if prior is not None and prior[0] is value:
        _checked_records.move_to_end(key)
        return prior[1], True
    origin, args = get_origin(kind), get_args(kind)
    if origin is tuple and type(value) is tuple:
        parts = [_checked(args[0], x, f"{path}[{i}]") for i, x in enumerate(value)]
        result, immutable = (
            (
                value
                if all(x is old for (x, _), old in zip(parts, value))
                else tuple(x for x, _ in parts)
            ),
            all(ok for _, ok in parts),
        )
        if immutable:
            _remember_checked(key, value, result)
        return result, immutable
    if is_dataclass(kind) and is_dataclass(value):
        require(
            type(value) is kind or {f.name for f in fields(value)} == set(type_hints(kind)),
            f"{path}: missing or unknown fields",
        )
        parts = {
            k: _checked(t, getattr(value, k), f"{path}.{k}") for k, t in type_hints(kind).items()
        }
        result = (
            value
            if type(value) is kind and all(x is getattr(value, k) for k, (x, _) in parts.items())
            else kind(**{k: x for k, (x, _) in parts.items()})
        )
        immutable = type(value).__dataclass_params__.frozen and all(ok for _, ok in parts.values())
        if immutable:
            _remember_checked(key, value, result)
        return result, immutable
    if origin in (types.UnionType, Union):
        for branch in args:
            try:
                return _checked(branch, value, path)
            except ContractError:
                pass
        raise ContractError(f"{path}: no matching union member")
    return decode(kind, as_data(value), path), type(value) in (str, int, float, bool, type(None))


@lru_cache(maxsize=16384)
def _checked_atom(kind, value, actual_type):
    return decode(kind, value)


def _remember_checked(key, value, result):
    _checked_records[key] = (value, result)
    if len(_checked_records) > 16384:
        _checked_records.popitem(last=False)


def immutable_memo(maxsize=128):
    """Bounded identity cache for one validated immutable native argument."""

    def decorate(function):
        entries = OrderedDict()

        @wraps(function)
        def call(value):
            previous = entries.get(id(value))
            if previous is not None and previous[0] is value:
                entries.move_to_end(id(value))
                return previous[1]
            result = function(value)
            _, immutable = _checked(type(value), value, "$ ")
            if immutable:
                entries[id(value)] = (value, result)
                if len(entries) > maxsize:
                    entries.popitem(last=False)
            return result

        call.cache_clear = entries.clear
        return call

    return decorate


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
        hints = type_hints(kind)
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
