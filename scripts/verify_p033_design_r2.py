"""P03.3 r2 offline design/limited-repair reference predicates; never runs production/Qt/Kit."""

import argparse
import copy
import csv
import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


INPUT_BINDING = {}


def input_path(name):
    ref = INPUT_BINDING["files"][Path(name).name]
    return ROOT / ref["path"]


def load(name):
    return json.loads(input_path(name).read_text(encoding="utf-8-sig"))


def table(name):
    with input_path(name).open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream, delimiter="\t"))


def view_errors(pair):
    """Synthetic display predicates, not verification of actual production evidence."""
    errors = []
    a, b = pair["views"]
    identity = ("run", "epoch", "catalog", "state", "observation", "prefix", "plan", "sample")
    if (a["run"], a["epoch"]) != (b["run"], b["epoch"]):
        errors.append("CROSS_RUN_EPOCH")
    if pair["label"] == "SAME_OBSERVATION" and any(a[k] != b[k] for k in identity):
        errors.append("FALSE_SYNCHRONY")
    for v in pair["views"]:
        if v["row_event_count"] > v["delivered_event_count"]:
            errors.append("FUTURE_LEAK")
        if v["age"] < 0:
            errors.append("AGE_INVALID")
        if v["age"] > 5 and v["status"] == "CURRENT":
            errors.append("STALE_UNMARKED")
        if "painted_as" in v:
            errors.append("LEGACY_PAINT_FIELD")
        schedule, proposal = v["schedule"], v["proposal"]
        painted_schedule, painted_proposal = v.get("painted_schedule"), v.get("painted_proposal")
        if schedule not in {"ACTUAL", "COMMITTED", "TENTATIVE", "UNSCHEDULED"} or proposal not in {
            "CANDIDATE",
            "ADOPTED",
            "SUPERSEDED",
        }:
            errors.append("STATE_ENUM")
        if schedule != "ACTUAL" and painted_schedule == "ACTUAL":
            errors.append("PREDICTION_AS_ACTUAL")
        if painted_schedule != schedule:
            errors.append("SCHEDULE_PAINT_MISMATCH")
        if proposal == "CANDIDATE" and painted_proposal == "ADOPTED":
            errors.append("CANDIDATE_AS_ADOPTED")
        if v.get("row_kind") == "FACT_PREFIX":
            if schedule != "ACTUAL" or painted_proposal != "FACT_PREFIX":
                errors.append("FACT_ROW_STATE")
            if (
                not v.get("actual_event_ids")
                or not v.get("actual_readback_ids")
                or v.get("actual_prefix") != v["prefix"]
            ):
                errors.append("ACTUAL_EVIDENCE_REQUIRED")
        elif v.get("row_kind") == "PLAN":
            if schedule == "ACTUAL":
                errors.append("ACTUAL_REQUIRES_FACT_ROW")
            if painted_proposal != proposal:
                errors.append("PROPOSAL_PAINT_MISMATCH")
            if proposal == "ADOPTED" and not v.get("adoption_id"):
                errors.append("ADOPTION_REQUIRED")
            if schedule == "COMMITTED" and not v.get("commitment_id"):
                errors.append("COMMITMENT_REQUIRED")
        else:
            errors.append("ROW_KIND_INVALID")
    return errors


class DesignReject(ValueError):
    pass


def require(ok, reason):
    if not ok:
        raise DesignReject(reason)


def canonical(value):
    def normalize(item):
        if isinstance(item, dict):
            return {k: normalize(v) for k, v in item.items()}
        if isinstance(item, list):
            return [normalize(v) for v in item]
        if type(item) is float:
            require(math.isfinite(item), "NONFINITE")
            if item.is_integer():
                return int(item)
        return item

    return json.dumps(
        normalize(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def request_digest(req):
    return hashlib.sha256(
        canonical({k: v for k, v in req.items() if k != "request_digest"})
    ).hexdigest()


def freeze_request(req, observation):
    """Reference materialization only. Input observation verification is an external prerequisite."""
    require("request_digest" not in req, "ALREADY_FROZEN")
    require(observation.get("verified") is True, "UNVERIFIED_ANCHOR")
    fields = (
        "run_id",
        "epoch",
        "observation_id",
        "event_count",
        "event_prefix_hash",
        "catalog_version",
        "state_revision",
        "sampled_sim_h",
    )
    require(all(k in observation for k in fields), "ANCHOR_FIELD_REQUIRED")
    require(
        (req["run_id"], req["epoch"]) == (observation["run_id"], observation["epoch"]),
        "ANCHOR_IDENTITY",
    )
    require(
        req["expected_catalog_version"] == observation["catalog_version"]
        and req["expected_state_revision"] == observation["state_revision"],
        "ANCHOR_VERSION",
    )
    t = observation["sampled_sim_h"]
    require(type(t) in (int, float) and math.isfinite(t) and t >= 0, "ANCHOR_TIME_INVALID")
    frozen = copy.deepcopy(req)
    frozen["expires_sim_h"] = t + 24
    if frozen["kind"] == "ORDER_CREATE" and frozen["payload"]["priority"] == "URGENT":
        frozen["payload"]["due_sim_h"] = t + 96
    frozen["request_digest"] = request_digest(frozen)
    record = dict(
        anchor={k: observation[k] for k in fields},
        request_digest=frozen["request_digest"],
        rule="P033-PRE-SUBMIT-ABSOLUTE-1",
    )
    return frozen, record


def receipt_time_outcome(frozen, received_sim_h):
    require(request_digest(frozen) == frozen["request_digest"], "REQUEST_DIGEST")
    if received_sim_h > frozen["expires_sim_h"]:
        return "EXPIRED"
    if frozen["kind"] == "ORDER_CREATE" and received_sim_h >= frozen["payload"]["due_sim_h"]:
        return "DUE_PASSED"
    return "WITHIN_TIME_LIMITS_ONLY"


def record_errors(schema, name, value, kind=None):
    """Bound P03.2 leaf/type validation for design fixtures. No admission/runtime implementation."""
    errors = []
    fields = schema["records"][name]["fields"]
    if not isinstance(value, dict):
        return ["FIELD_INVALID"]
    if set(value) - set(fields):
        errors.append("FIELD_UNKNOWN")
    for key, field in fields.items():
        if key not in value:
            if field["required"]:
                errors.append("FIELD_REQUIRED:" + key)
            continue
        typ, v = field["type"], value[key]

        def valid_type(t, item):
            if t in schema["records"]:
                return not record_errors(schema, t, item, kind)
            if t == "event_payload":
                return not record_errors(schema, kind, item)
            if t.startswith("enum:"):
                return type(item) is str and item in t[5:].split(",")
            if t == "id":
                return type(item) is str and re.fullmatch(r"[A-Za-z0-9._-]{1,80}", item) is not None
            if t == "path":
                return type(item) is str and (item.startswith("/World/") or item == "CPU:N/A")
            if t == "hash":
                return type(item) is str and re.fullmatch(r"[a-f0-9]{64}", item) is not None
            if t in {"index", "count", "integer"}:
                return type(item) is int and (t == "integer" or item >= (1 if t == "count" else 0))
            if t in {"positive", "nonnegative", "fraction"}:
                return (
                    type(item) in (int, float)
                    and math.isfinite(item)
                    and (
                        item > 0
                        if t == "positive"
                        else 0 <= item <= 1
                        if t == "fraction"
                        else item >= 0
                    )
                )
            if t == "bool":
                return type(item) is bool
            if t == "utc":
                try:
                    dt = datetime.fromisoformat(item.replace("Z", "+00:00"))
                    return dt.utcoffset() is not None and dt.utcoffset().total_seconds() == 0
                except (ValueError, AttributeError):
                    return False
            return False

        ok = (
            type(v) is list and all(valid_type(typ[:-2], x) for x in v)
            if typ.endswith("[]")
            else valid_type(typ, v)
        )
        if not ok:
            errors.append("FIELD_INVALID:" + key)
    return errors


def e21_errors(e, e20):
    errors = []
    if e["scope"] == "SHARED_E20":
        if (e["run"], e["epoch"]) != (e20["run"], e20["epoch"]) or not e20[
            "queued_then_instantiated"
        ]:
            errors.append("E21_SHARED_BINDING")
    elif e["scope"] == "SEPARATE_BOUNDED":
        if (e["run"], e["epoch"]) == (e20["run"], e20["epoch"]):
            errors.append("E21_SEPARATE_IDENTITY")
    else:
        errors.append("E21_SCOPE")
    if e["registered"] < 4 or e["instantiated"] < 4:
        errors.append("E21_FOUR_PRODUCTS")
    if (
        not e["queue_event_id"]
        or not e["instance_readback_id"]
        or e["queue_exit_h"] < e["queue_entry_h"]
    ):
        errors.append("E21_QUEUE_WITNESS")
    if (
        e["wip"] > e["wip_limit"]
        or e["registered"] > e["lifetime_limit"]
        or e["open"] > e["open_limit"]
        or e["queued"] > e["queue_limit"]
    ):
        errors.append("E21_LIMIT")
    return errors


def command_resources(command, version_binding, catalogs):
    """Reference source join, not actual interval reconstruction."""
    require(command["id"] == version_binding["command_id"], "COMMAND_BINDING")
    version = version_binding["admitted_catalog_version"]
    require(version in catalogs, "CATALOG_VERSION_MISSING")
    catalog = catalogs[version]
    require(catalog["hash"] == version_binding["admitted_catalog_hash"], "CATALOG_HASH")
    if command.get("service"):
        op = command["service"]["operation"]
        require(op["id"] == command["operation_id"], "SERVICE_OPERATION_ID")
        source = "IMMUTABLE_COMMAND_SERVICE_OPERATION"
    else:
        require(command["operation_id"] in catalog["operations"], "OPERATION_MISSING")
        op = catalog["operations"][command["operation_id"]]
        source = "ADMITTED_CATALOG_OPERATION"
    return dict(
        people=sorted({x["person_id"] for x in command["roles"]}),
        equipment=sorted(set(op["equipment"])),
        catalog_version=version,
        source=source,
    )


def repair_checks(check, recipe, schema):
    def rejects(fn, code):
        try:
            fn()
        except DesignReject as e:
            return str(e) == code
        return False

    ref = recipe["arrive"]["scene_reference"]
    check("R01_scene_valid", not record_errors(schema, "SceneReference", ref), ref)
    bad = dict(ref, prim_path="/P05/People/W3")
    check(
        "R01_old_scene_rejected",
        bool(record_errors(schema, "SceneReference", bad)),
        "old literal retained as negative",
    )
    depart = dict(reason="REVIEW", handover_policy=recipe["depart"]["handover_policy"])
    check("R01_departure_valid", not record_errors(schema, "PERSON_DEPART", depart), depart)
    check(
        "R01_old_departure_rejected",
        bool(
            record_errors(
                schema,
                "PERSON_DEPART",
                dict(depart, handover_policy="LEGAL_BOUNDARY_OR_VERIFIED_HANDOVER_ELSE_HOLD"),
            )
        ),
        "old enum rejected",
    )
    check(
        "R01_client_ordinal_rejected",
        bool(record_errors(schema, "SceneReference", dict(ref, catalog_version=1))),
        "SceneReference stays immutable client input",
    )
    q = dict(
        run_id="REF",
        epoch=0,
        request_id="Q",
        producer_id="GUI",
        client_sequence=1,
        source="GUI",
        kind="ORDER_CREATE",
        target_id="NEW",
        payload=dict(
            order_id="NEW",
            template_id="SR-W1",
            template_revision="v1",
            template_sha256="a" * 64,
            quantity=1,
            due_sim_h=0,
            priority="URGENT",
            material_plan_id="MAT",
            arrival_rule="REQUEST_EFFECTIVE_TIME",
        ),
        expected_catalog_version=2,
        expected_state_revision=10,
        expected_target_revision=0,
        time_rule="IMMEDIATE",
        submitted_at_utc="2026-10-22T00:00:00Z",
    )
    obs = dict(
        run_id="REF",
        epoch=0,
        observation_id="O10",
        event_count=10,
        event_prefix_hash="a" * 64,
        catalog_version=2,
        state_revision=10,
        sampled_sim_h=10,
        verified=True,
    )
    frozen, metadata = freeze_request(q, obs)
    check(
        "R02_numeric_wire_valid",
        not record_errors(schema, "ChangeRequest", frozen, "ORDER_CREATE"),
        "existing schema no extension",
    )
    check(
        "R02_offsets_from_anchor",
        frozen["payload"]["due_sim_h"] == 106 and frozen["expires_sim_h"] == 34,
        "pre-submit t=10",
    )
    check(
        "R02_metadata_separate",
        "anchor" not in frozen and metadata["request_digest"] == frozen["request_digest"],
        metadata,
    )
    before = canonical(frozen)
    check(
        "R02_later_receipt_unchanged",
        receipt_time_outcome(frozen, 11) == "WITHIN_TIME_LIMITS_ONLY"
        and canonical(frozen) == before,
        "do not rebase to107/35",
    )
    check(
        "R02_expiry_inclusive",
        receipt_time_outcome(frozen, 34) == "WITHIN_TIME_LIMITS_ONLY",
        "inclusive endpoint",
    )
    check(
        "R02_late_expired",
        receipt_time_outcome(frozen, 35) == "EXPIRED" and canonical(frozen) == before,
        "no post-send extension",
    )
    changed = copy.deepcopy(frozen)
    changed["expires_sim_h"] = 35
    check(
        "R02_digest_tamper_rejected",
        rejects(lambda: receipt_time_outcome(changed, 11), "REQUEST_DIGEST"),
        "immutable request",
    )
    check(
        "R02_refreeze_rejected",
        rejects(lambda: freeze_request(frozen, obs), "ALREADY_FROZEN"),
        "same accepted/unknown request not rematerialized",
    )
    check(
        "R02_unknown_anchor_rejected",
        rejects(lambda: freeze_request(q, dict(obs, verified=False)), "UNVERIFIED_ANCHOR"),
        "verification precondition",
    )
    check(
        "R02_wrong_epoch_rejected",
        rejects(lambda: freeze_request(q, dict(obs, epoch=1)), "ANCHOR_IDENTITY"),
        "same run/epoch",
    )
    check(
        "R02_boolean_time_rejected",
        rejects(lambda: freeze_request(q, dict(obs, sampled_sim_h=True)), "ANCHOR_TIME_INVALID"),
        "finite numeric hours",
    )
    check(
        "R02_version_rejected",
        rejects(lambda: freeze_request(q, dict(obs, state_revision=9)), "ANCHOR_VERSION"),
        "versions bound to anchor",
    )
    check(
        "R02_original_not_mutated",
        "request_digest" not in q and "expires_sim_h" not in q,
        "pure reference materialization",
    )
    for schedule in ["UNSCHEDULED", "COMMITTED", "TENTATIVE"]:
        v = dict(
            run="R",
            epoch=0,
            catalog=1,
            state=1,
            observation="O",
            prefix="P",
            plan=1,
            sample=1,
            row_event_count=1,
            delivered_event_count=1,
            age=1,
            status="CURRENT",
            row_kind="PLAN",
            schedule=schedule,
            proposal="CANDIDATE",
            painted_schedule=schedule,
            painted_proposal="CANDIDATE",
            commitment_id="C",
        )
        p = dict(views=[copy.deepcopy(v), copy.deepcopy(v)], label="SAME_OBSERVATION")
        check("R04_" + schedule + "_legitimate", not view_errors(p), "unexecuted state distinct")
        p["views"][1]["painted_schedule"] = "ACTUAL"
        check(
            "R04_" + schedule + "_as_actual_rejected",
            "PREDICTION_AS_ACTUAL" in view_errors(p),
            "review counterexample",
        )
    v.update(
        row_kind="FACT_PREFIX",
        schedule="ACTUAL",
        proposal="CANDIDATE",
        painted_schedule="ACTUAL",
        painted_proposal="FACT_PREFIX",
        actual_event_ids=["EV1"],
        actual_readback_ids=["RB1"],
        actual_prefix="P",
    )
    p = dict(views=[copy.deepcopy(v), copy.deepcopy(v)], label="SAME_OBSERVATION")
    check(
        "R04_actual_prefix_beside_candidate",
        not view_errors(p),
        "actual facts independently retained",
    )
    p["views"][1]["actual_readback_ids"] = []
    check(
        "R04_missing_actual_readback_rejected",
        "ACTUAL_EVIDENCE_REQUIRED" in view_errors(p),
        "references required, full truth verification stays P06",
    )
    cmd = dict(id="C", operation_id="OP", roles=[dict(person_id="P1")], service=None)
    binding = dict(command_id="C", admitted_catalog_version=1, admitted_catalog_hash="H1")
    catalogs = {
        1: dict(hash="H1", operations={"OP": dict(id="OP", equipment=["FORK-01"])}),
        2: dict(hash="H2", operations={"OP": dict(id="OP", equipment=["OTHER"])}),
    }
    r = command_resources(cmd, binding, catalogs)
    check(
        "R05_static_admitted_join", r["equipment"] == ["FORK-01"] and r["catalog_version"] == 1, r
    )
    svc = dict(
        cmd,
        operation_id="SERVICE",
        service=dict(operation=dict(id="SERVICE", equipment=["CART-01"])),
    )
    check(
        "R05_service_join",
        command_resources(svc, binding, catalogs)["equipment"] == ["CART-01"],
        "immutable service operation",
    )
    check(
        "R05_missing_version_rejected",
        rejects(
            lambda: command_resources(cmd, dict(binding, admitted_catalog_version=9), catalogs),
            "CATALOG_VERSION_MISSING",
        ),
        "never fallback to latest",
    )
    check(
        "R05_wrong_hash_rejected",
        rejects(
            lambda: command_resources(cmd, dict(binding, admitted_catalog_hash="X"), catalogs),
            "CATALOG_HASH",
        ),
        "source binding",
    )
    check(
        "R05_missing_operation_rejected",
        rejects(
            lambda: command_resources(dict(cmd, operation_id="MISSING"), binding, catalogs),
            "OPERATION_MISSING",
        ),
        "not latest lookup",
    )
    check(
        "R05_service_id_mismatch_rejected",
        rejects(
            lambda: command_resources(dict(svc, operation_id="WRONG"), binding, catalogs),
            "SERVICE_OPERATION_ID",
        ),
        "stable identity",
    )
    check(
        "R05_no_command_equipment",
        "equipment" not in cmd and r["people"] == ["P1"],
        "source join does not invent wire field",
    )


def witness_errors(w):
    errors = []
    if any((s["run"], s["epoch"]) != (w["run"], w["epoch"]) for s in w["stages"]):
        errors.append("SPLICED_SESSION")
    expected = [
        "BASE_STARTED_WITH_ADJUSTABLE",
        "NORMAL_CREATE",
        "URGENT_CREATE_AND_EFFECT",
        "DEPART_APPLIED",
        "ARRIVE_NEW_PERSON",
        "CLOSE_INPUT",
        "ALL_RECEIVED_AND_EXIT",
    ]
    if [s["kind"] for s in w["stages"]] != expected:
        errors.append("STAGE_ORDER")
    if not w["base_started_readback"] or not w["adjustable_at_changes"]:
        errors.append("NO_REAL_START_OR_FOLLOWUP")
    if set(w["new_orders"]) & set(w["initial_orders"]) or w["new_person"] in w["initial_people"]:
        errors.append("PREDECLARED_POOL")
    if w["registered_products"] < 4 or w["instantiated_products"] != w["registered_products"]:
        errors.append("E21_INCOMPLETE")
    if w["max_wip"] > w["wip_limit"]:
        errors.append("CAPACITY_INVALID")
    if not w["urgent_actual_effect"] or not w["same_state_urgency_control"]:
        errors.append("URGENCY_UNPROVEN")
    if w["protected_before"] != w["protected_after"] or w["reset_count"]:
        errors.append("PROTECTED_HISTORY_CHANGED")
    if w["received_products"] != w["registered_products"]:
        errors.append("RECEIPTS_MISSING")
    if not w["new_person_actual_readback"] or not w["new_person_executed"]:
        errors.append("PERSON_NOT_WITNESSED")
    if "catalog_version" in w["client_scene_reference"]:
        errors.append("CLIENT_ORDINAL")
    if not w["departed_actual"] or not w["F_E_continuous"]:
        errors.append("PERSON_HISTORY_INVALID")
    if w["pending"] or w["holds"] or not w["intake_closed"] or not w["audit_save_pass"]:
        errors.append("DRAIN_INCOMPLETE")
    if w["exit_code"] != 0 or not w["exit_observed"]:
        errors.append("EXIT_UNPROVEN")
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="Fresh output directory")
    parser.add_argument("--binding", default="docs/public_delivery_r2/p033_revision_r2.json")
    args = parser.parse_args()
    global INPUT_BINDING
    INPUT_BINDING = json.loads((ROOT / args.binding).read_text(encoding="utf-8-sig"))
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=False)
    checks = []

    def check(name, passed, evidence):
        checks.append(dict(name=name, passed=bool(passed), evidence=evidence))

    schema = load("docs/delivery/p032_contract_schema_r3.json")["records"]
    fields = table("docs/delivery/timeline_field_source_map.tsv")
    ids = {row["source_id"] for row in table("docs/delivery/p032_source_map.tsv")}
    for row in fields:
        src = row["source_leaf_or_derivation"]
        resolved = src.startswith("P033:")
        if not resolved:
            record, leaf = src.split(".")
            resolved = record in schema and leaf in schema[record]["fields"]
        check(
            row["field_id"] + "_SOURCE",
            resolved
            and set(row["source_ids"].split(";")) <= ids
            and row["implementation_status"] == "DESIGN_NOT_IMPLEMENTED",
            src,
        )
    cases = table("docs/delivery/interaction_case_protocol.tsv")
    originals = {x["case_id"]: x for x in table("docs/delivery/interaction_cases_r2.tsv")}
    check(
        "CASE_SET", {x["case_id"] for x in cases} == set(originals) and len(cases) == 24, "E01-E24"
    )
    for row in cases:
        check(
            row["case_id"] + "_PROTOCOL",
            all(
                row[k]
                for k in (
                    "initial_input",
                    "trigger_and_action",
                    "expected",
                    "reject_or_not_met",
                    "evidence",
                    "independent_check",
                )
            )
            and row["requirements"] == originals[row["case_id"]]["requirements"]
            and row["production_result"] == "NOT_EXECUTED",
            row["independent_check"],
        )
    requirements = {
        x["requirement_id"] for x in table("docs/delivery/interaction_requirements_r2.tsv")
    }
    covered = set().union(*(set(x["requirements"].split(";")) for x in cases))
    check("I01_I08_COVERAGE", covered == requirements, sorted(covered))
    recipe = load("docs/delivery/e20_input_recipe.json")
    check(
        "E20_FOUR_PRODUCTS",
        sum(x["quantity"] for x in recipe["initial_orders"] + recipe["new_orders"]) == 4,
        "1+2+1",
    )
    check(
        "E20_NEW_IDS",
        not (
            {x["order_id"] for x in recipe["initial_orders"]}
            & {x["order_id"] for x in recipe["new_orders"]}
        )
        and recipe["arrive"]["person_id"] not in {x["id"] for x in recipe["initial_people"]},
        "no predeclared objects",
    )
    check(
        "SCENE_REFERENCE_NO_ORDINAL",
        "catalog_version" not in recipe["arrive"]["scene_reference"],
        "application emits SceneBinding",
    )
    for key in ("base_config", "contract"):
        ref = recipe[key]
        check(
            "RECIPE_" + key,
            hashlib.sha256(
                (ROOT / ref["path"]).read_bytes().replace(b"\r\n", b"\n")
                if ref.get("digest_basis") == "LF_NORMALIZED_SOURCE_BYTES"
                else (ROOT / ref["path"]).read_bytes()
            ).hexdigest()
            == ref["sha256"],
            ref["path"],
        )
    targets = table("docs/delivery/capacity_targets.tsv")
    check(
        "CAPACITY_NOT_MEASURED",
        len(targets) == 10
        and all(
            x["status"] == "PENDING_P04_P05_CALIBRATION"
            and x["final_supported_limit"] == "UNLOCKED"
            for x in targets
        ),
        "10 candidate thresholds",
    )
    # Equal canvas arithmetic under static design dimensions; no GUI test claim.
    matrix = []
    for width, height in ((1280, 720), (1366, 768), (1920, 1080)):
        for scale in (1, 1.25, 1.5):
            horizontal = width >= 1440
            # Common legend/axis gutters mirrored to reserve equal usable rectangles.
            free_w, free_h = width - 16, height - 64 - 32 - 16
            if horizontal:
                cw, ch = (free_w - 8) / 2 - 160, free_h - 72 - 24
            else:
                cw, ch = free_w - 160, (free_h - 8) / 2 - 72 - 24
            matrix.append(
                dict(
                    logical_client=[width, height],
                    scale=scale,
                    orientation="LR" if horizontal else "TB",
                    canvas=[cw, ch],
                    ratio=0.5,
                    actual_gui="NOT_TESTED",
                    host_availability="UNKNOWN",
                )
            )
            check(
                f"LAYOUT_{width}_{height}_{scale}",
                cw > 0 and ch >= 160,
                "static equal canvas geometry only",
            )
    (out / "layout_matrix.json").write_text(json.dumps(matrix, indent=2) + "\n", encoding="utf-8")
    view = dict(
        run="SYNTHETIC",
        epoch=0,
        catalog=2,
        state=20,
        observation="O20",
        prefix="P20",
        plan=3,
        sample=12,
        delivered_event_count=20,
        row_event_count=20,
        age=1,
        status="CURRENT",
        proposal="ADOPTED",
        schedule="ACTUAL",
        painted_schedule="ACTUAL",
        painted_proposal="FACT_PREFIX",
        row_kind="FACT_PREFIX",
        actual_event_ids=["EV20"],
        actual_readback_ids=["RB20"],
        actual_prefix="P20",
    )
    pair = dict(views=[copy.deepcopy(view), copy.deepcopy(view)], label="SAME_OBSERVATION")
    check("VIEW_POSITIVE", not view_errors(pair), "synthetic design predicate")
    mutations = [
        ("CROSS_RUN_EPOCH", "run", "OTHER"),
        ("FALSE_SYNCHRONY", "sample", 13),
        ("FUTURE_LEAK", "row_event_count", 21),
        ("AGE_INVALID", "age", -1),
        ("STALE_UNMARKED", "age", 6),
    ]
    negatives = []
    for expected, key, value in mutations:
        broken = copy.deepcopy(pair)
        broken["views"][1][key] = value
        result = view_errors(broken)
        check("REJECT_" + expected, expected in result, result)
        negatives.append(dict(expected=expected, fixture=broken, errors=result))
    for expected, changes in [
        ("CANDIDATE_AS_ADOPTED", dict(proposal="CANDIDATE", painted_proposal="ADOPTED")),
        (
            "PREDICTION_AS_ACTUAL",
            dict(
                schedule="TENTATIVE",
                painted_schedule="ACTUAL",
                painted_proposal="FACT_PREFIX",
                row_kind="FACT_PREFIX",
                actual_event_ids=["EV20"],
                actual_readback_ids=["RB20"],
                actual_prefix="P20",
            ),
        ),
    ]:
        broken = copy.deepcopy(pair)
        broken["views"][1].update(changes)
        result = view_errors(broken)
        check("REJECT_" + expected, expected in result, result)
        negatives.append(dict(expected=expected, fixture=broken, errors=result))
    asynchronous = copy.deepcopy(pair)
    asynchronous["views"][1]["sample"] = 11
    asynchronous["label"] = "ASYNCHRONOUS"
    check(
        "ASYNC_HONEST_POSITIVE",
        not view_errors(asynchronous),
        "different samples explicitly marked",
    )
    stages = [dict(kind=k, run="SYNTHETIC", epoch=0) for k in recipe["stage_order"]]
    witness = dict(
        run="SYNTHETIC",
        epoch=0,
        stages=stages,
        base_started_readback=True,
        adjustable_at_changes=True,
        initial_orders=["BASE"],
        new_orders=["NORMAL", "URGENT"],
        initial_people=["W1", "W2"],
        new_person="W3",
        registered_products=4,
        instantiated_products=4,
        queued_then_instantiated=True,
        max_wip=3,
        wip_limit=3,
        urgent_actual_effect=True,
        same_state_urgency_control=True,
        protected_before="OLD",
        protected_after="OLD",
        reset_count=0,
        received_products=4,
        new_person_actual_readback=True,
        new_person_executed=True,
        client_scene_reference={"domain_id": "W3"},
        departed_actual=True,
        F_E_continuous=True,
        pending=0,
        holds=0,
        intake_closed=True,
        audit_save_pass=True,
        exit_code=0,
        exit_observed=True,
    )
    check(
        "E20_REFERENCE_POSITIVE",
        not witness_errors(witness),
        "artificial witness only, not production evidence",
    )
    muts = [
        ("NO_REAL_START_OR_FOLLOWUP", "base_started_readback", False),
        ("PREDECLARED_POOL", "new_person", "W2"),
        ("E21_INCOMPLETE", "registered_products", 3),
        ("CAPACITY_INVALID", "max_wip", 4),
        ("URGENCY_UNPROVEN", "urgent_actual_effect", False),
        ("URGENCY_UNPROVEN", "same_state_urgency_control", False),
        ("PROTECTED_HISTORY_CHANGED", "protected_after", "CHANGED"),
        ("PROTECTED_HISTORY_CHANGED", "reset_count", 1),
        ("RECEIPTS_MISSING", "received_products", 3),
        ("PERSON_NOT_WITNESSED", "new_person_actual_readback", False),
        ("PERSON_HISTORY_INVALID", "F_E_continuous", False),
        ("DRAIN_INCOMPLETE", "intake_closed", False),
        ("DRAIN_INCOMPLETE", "pending", 1),
        ("EXIT_UNPROVEN", "exit_observed", False),
        ("CLIENT_ORDINAL", "client_scene_reference", {"catalog_version": 2}),
    ]
    for index, (expected, key, value) in enumerate(muts):
        broken = copy.deepcopy(witness)
        broken[key] = value
        result = witness_errors(broken)
        check(f"REJECT_E20_{index:02}_{expected}", expected in result, result)
        negatives.append(dict(expected=expected, fixture=broken, errors=result))
    for expected in ("SPLICED_SESSION", "STAGE_ORDER"):
        broken = copy.deepcopy(witness)
        if expected == "SPLICED_SESSION":
            broken["stages"][3]["epoch"] = 1
        else:
            broken["stages"][2], broken["stages"][3] = broken["stages"][3], broken["stages"][2]
        result = witness_errors(broken)
        check("REJECT_" + expected, expected in result, result)
        negatives.append(dict(expected=expected, fixture=broken, errors=result))
    without_queue = copy.deepcopy(witness)
    without_queue["queued_then_instantiated"] = False
    check(
        "R03_E20_without_queue_positive",
        not witness_errors(without_queue),
        "E21 may be separate bounded case",
    )
    e21 = dict(
        scope="SHARED_E20",
        run=witness["run"],
        epoch=0,
        registered=4,
        instantiated=4,
        queue_entry_h=1,
        queue_exit_h=2,
        queue_event_id="Q",
        instance_readback_id="RB",
        wip=3,
        wip_limit=3,
        lifetime_limit=8,
        open=4,
        open_limit=8,
        queued=1,
        queue_limit=8,
    )
    check("R03_E21_shared_positive", not e21_errors(e21, witness), "same run/epoch queue witness")
    separate = dict(e21, scope="SEPARATE_BOUNDED", run="BOUND")
    check(
        "R03_E21_separate_positive",
        not e21_errors(separate, without_queue),
        "no full four-receipt long-run requirement in bounded capacity predicate",
    )
    check(
        "R03_E21_missing_queue_rejected",
        "E21_QUEUE_WITNESS" in e21_errors(dict(separate, queue_event_id=""), without_queue),
        "E20 relaxation cannot certify missing E21",
    )
    check(
        "R03_E21_shared_wrong_identity_rejected",
        "E21_SHARED_BINDING" in e21_errors(dict(e21, run="OTHER"), witness),
        "no splicing",
    )
    check(
        "R03_E21_shared_without_queue_rejected",
        "E21_SHARED_BINDING" in e21_errors(e21, without_queue),
        "shared witness must actually queue",
    )
    check(
        "R03_E21_separate_same_identity_rejected",
        "E21_SEPARATE_IDENTITY" in e21_errors(dict(separate, run=witness["run"]), without_queue),
        "independent evidence remains independent",
    )
    check(
        "R03_E21_over_capacity_rejected",
        "E21_LIMIT" in e21_errors(dict(separate, wip=4), without_queue),
        "capacity still enforced",
    )
    repair_checks(check, recipe, load("docs/delivery/p032_contract_schema_r3.json"))
    for name, ref in INPUT_BINDING["files"].items():
        data = (ROOT / ref["path"]).read_bytes()
        if ref.get("digest_basis") == "LF_NORMALIZED_SOURCE_BYTES":
            data = data.replace(b"\r\n", b"\n")
        check("BINDING_" + name, hashlib.sha256(data).hexdigest() == ref["sha256"], ref["path"])
    (out / "synthetic_negative_fixtures.json").write_text(
        json.dumps(
            dict(scope="SYNTHETIC_DESIGN_REFERENCE_ONLY", negative_fixtures=negatives),
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    result = dict(
        scope="OFFLINE_DESIGN_R2_LIMITED_REPAIR_NOT_RUNTIME_ACCEPTANCE",
        checks=checks,
        count=len(checks),
        passed=sum(c["passed"] for c in checks),
        negative_count=len(negatives),
        production_runs=0,
        kit_runs=0,
    )
    (out / "checks.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: v for k, v in result.items() if k != "checks"}))
    return 0 if all(c["passed"] for c in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
