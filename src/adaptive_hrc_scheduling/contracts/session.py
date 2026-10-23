"""P03.2 wire contract used by workers and clients; no GUI or research imports."""

import hashlib
import json
import math
import re
from datetime import datetime
from importlib.resources import files

from .codec import require

SCHEMA = json.loads(files(__package__).joinpath("session_schema.json").read_text())


def canonical(value):
    def normalize(v):
        if type(v) is dict:
            require(all(type(k) is str for k in v), "JSON_KEY")
            return {k: normalize(x) for k, x in v.items()}
        if type(v) in (list, tuple):
            return [normalize(x) for x in v]
        if type(v) is float:
            require(math.isfinite(v), "NONFINITE_JSON")
            return int(v) if v.is_integer() else v
        require(v is None or type(v) in (str, int, bool), "JSON_TYPE")
        return v

    return json.dumps(
        normalize(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def loads(raw):
    def pairs(rows):
        result = {}
        for k, v in rows:
            require(k not in result, "DUPLICATE_JSON_KEY")
            result[k] = v
        return result

    def bad(_):
        require(False, "NONFINITE_JSON")

    return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad)


def validate_record(name, value, kind=None):
    require(type(value) is dict, "FIELD_INVALID")
    fields = SCHEMA[name]
    if name == "RunSpec" and value.get("schema_version") == "P04.4-SESSION-r1":
        fields = {**fields, "schema_version": {"type": "enum:P04.4-SESSION-r1", "required": True}}
    require(set(value) <= fields.keys(), "FIELD_UNKNOWN")
    for key, spec in fields.items():
        if key not in value:
            require(not spec["required"], "FIELD_REQUIRED:" + key)
            continue
        validate_type(spec["type"], value[key], kind)
    return value


def validate_type(typ, v, kind):
    if typ.endswith("[]"):
        require(type(v) is list, "FIELD_INVALID")
        for x in v:
            validate_type(typ[:-2], x, kind)
        if typ == "id[]":
            require(len(v) == len(set(v)), "DUPLICATE_ID")
    elif typ in SCHEMA:
        validate_record(typ, v, kind)
    elif typ == "event_payload":
        require(kind in SCHEMA, "REQUEST_KIND")
        validate_record(kind, v)
    elif typ.startswith("enum:"):
        require(type(v) is str and v in typ[5:].split(","), "FIELD_INVALID")
    elif typ in ("id", "hash"):
        pattern = r"[A-Za-z0-9._-]{1,80}" if typ == "id" else r"[a-f0-9]{64}"
        require(type(v) is str and re.fullmatch(pattern, v), "FIELD_INVALID")
    elif typ == "bool":
        require(type(v) is bool, "FIELD_INVALID")
    elif typ in ("integer", "index", "count"):
        require(type(v) is int and (typ == "integer" or v >= (typ == "count")), "FIELD_INVALID")
    elif typ in ("positive", "nonnegative", "fraction"):
        require(type(v) in (int, float) and math.isfinite(v), "FIELD_INVALID")
        require(
            v > 0 if typ == "positive" else 0 <= v <= 1 if typ == "fraction" else v >= 0,
            "FIELD_INVALID",
        )
    elif typ == "path":
        require(type(v) is str and (v.startswith("/World/") or v == "CPU:N/A"), "FIELD_INVALID")
    elif typ == "utc":
        require(type(v) is str, "FIELD_INVALID")
        parsed = datetime.fromisoformat(v.replace("Z", "+00:00"))
        require(
            parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0,
            "FIELD_INVALID",
        )
    else:
        require(False, "SCHEMA_TYPE_UNKNOWN")


def validate_spec(value):
    validate_record("RunSpec", value)
    require(value["epoch"] == 0, "FRESH_EPOCH")
    require(bool(value["initial_orders"]) and bool(value["initial_people"]), "INITIAL_EMPTY")
    for rows, key in (
        (value["initial_orders"], "order_id"),
        (value["initial_people"], "person_id"),
    ):
        require(len({r[key] for r in rows}) == len(rows), "DUPLICATE_INITIAL_ID")
    cost = value["cost"]
    declared = set(cost["person_template_ids"])
    rates = [r["template_id"] for r in cost["rates"]]
    require(bool(declared) and set(rates) == declared, "COST_RATE_REQUIRED")
    require(len(rates) == len(set(rates)), "COST_RATE_CONFLICT")
    require(
        {p["parameter_template_id"] for p in value["initial_people"]} <= declared,
        "COST_RATE_REQUIRED",
    )
    require(
        cost["legacy_resource_cost_source_sha256"] == value["initial_config_sha256"],
        "COST_RESOURCE_SOURCE",
    )
    cap = value["capacity"]
    require(
        cap["max_lifetime_products"] >= 4 and cap["max_wip_products"] <= cap["max_open_products"],
        "CAPACITY_INVALID",
    )
    mode = value["mode"]
    if mode == "FIXED_PROTOCOL":
        require(
            "fixed_event_manifest_sha256" in value
            and value["scenario"] != "INTERACTIVE"
            and "replay_source_sha256" not in value,
            "FIXED_MANIFEST_REQUIRED",
        )
    elif mode == "INTERACTIVE_REPLAY":
        require(
            "replay_source_sha256" in value and "fixed_event_manifest_sha256" not in value,
            "REPLAY_SOURCE_REQUIRED",
        )
    else:
        require(
            value["scenario"] == "INTERACTIVE"
            and "fixed_event_manifest_sha256" not in value
            and "replay_source_sha256" not in value,
            "MODE_SOURCE_MISMATCH",
        )
    return loads(canonical(value))  # detached frozen wire value owned by the consumer


def request_digest(request):
    return digest({k: v for k, v in request.items() if k != "request_digest"})


def validate_request(request):
    require(type(request) is dict, "FIELD_INVALID")
    validate_record("ChangeRequest", request, request.get("kind"))
    require(request_digest(request) == request["request_digest"], "REQUEST_DIGEST")
    require(
        (request["time_rule"] == "AT_SIM_H") == ("requested_sim_h" in request), "TIME_RULE_INVALID"
    )
    return loads(canonical(request))


def validate_bundle(value):
    """Bind a finite replay journal by content, rather than echoing its hash."""
    required = {"spec", "profile", "fixed_requests"}
    require(
        type(value) is dict and required <= set(value) <= required | {"replay_source"},
        "SESSION_BUNDLE_FIELDS",
    )
    spec = validate_spec(value["spec"])
    require(type(value["fixed_requests"]) is list, "FIXED_REQUESTS_INVALID")
    for request in value["fixed_requests"]:
        validate_request(request)
    if spec["mode"] == "INTERACTIVE_REPLAY":
        source = value.get("replay_source")
        require(
            type(source) is dict
            and (
                set(source) == {"requests"}
                or (
                    spec["schema_version"] == "P04.4-SESSION-r1"
                    and set(source) == {"requests", "received_sim_h"}
                )
            )
            and type(source["requests"]) is list
            and not value["fixed_requests"],
            "REPLAY_SOURCE_REQUIRED",
        )
        require(digest(source) == spec["replay_source_sha256"], "REPLAY_SOURCE_BINDING")
        if spec["schema_version"] == "P04.4-SESSION-r1":
            require(
                type(source.get("received_sim_h")) is dict
                and set(source["received_sim_h"]) == {r["request_id"] for r in source["requests"]},
                "REPLAY_RECEPTION_REQUIRED",
            )
            for received_h in source["received_sim_h"].values():
                validate_type("nonnegative", received_h, None)
        for request in source["requests"]:
            validate_request(request)
            require(
                request["source"] == "REPLAY"
                and (request["run_id"], request["epoch"]) == (spec["run_id"], spec["epoch"]),
                "REPLAY_REQUEST_BINDING",
            )
    else:
        require("replay_source" not in value, "MODE_SOURCE_MISMATCH")
    return loads(canonical(value))
