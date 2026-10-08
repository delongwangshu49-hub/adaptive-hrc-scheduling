"""S18 simulation admission bound to the exact approved inputs, never industrial G2."""

import hashlib
import json
import re
from importlib.resources import files

from adaptive_hrc_scheduling.contracts.codec import as_data, require
from adaptive_hrc_scheduling.domain import production as m

VERSION = "S18-PROD-2.0"
CONSUMERS = (
    "domain",
    "contract",
    "schemas",
    "generator",
    "mapping",
    "light",
    "human_navigation",
    "execution_audit",
    "planning",
    "observation_ledger",
    "decision_audit",
    "joint_driver",
    "isaac_adapter",
    "isaac_port",
)
PROPOSAL_DIGEST = "5834f023c3ccb9789b43aa9a72b9cc3a4a9d951b35bc0670a885bdec93f995a0"
ASSUMPTION_DIGEST = "8f1f2ea6a4e9096c57d9f3d6fc882291231c0240f2b03c2a97a7a93ba9065bbd"


def approved_inputs():
    root = files("adaptive_hrc_scheduling").joinpath("simulation_inputs")
    approval = json.loads(root.joinpath("S18_simulation_scope_approval_r1.json").read_bytes())
    require(
        approval["status"] == "APPROVED_FOR_LOCAL_IMPLEMENTATION"
        and approval["decision_id"] == "S18-SIM-APPROVAL-001"
        and approval["approved_clauses"] == [f"SR{i:02}" for i in range(1, 9)],
        "SIM_APPROVAL_REQUIRED",
    )
    for name, expected in (("md", PROPOSAL_DIGEST), ("json", ASSUMPTION_DIGEST)):
        raw = root.joinpath("S18_simulation_scope_proposal_r1." + name).read_bytes()
        require(hashlib.sha256(raw).hexdigest() == expected, "SIM_APPROVED_INPUT_DRIFT")
    require(
        approval["proposal_sha256"] == PROPOSAL_DIGEST
        and approval["assumption_sha256"] == ASSUMPTION_DIGEST,
        "SIM_APPROVAL_BINDING",
    )


def profile(config):
    bindings = tuple(
        m.ScopeBinding(
            p.id,
            p.revision,
            a.id,
            p.id + suffix,
            a.id + ".ABSTRACT-JOINTS-v1",
            "v1",
            a.id + ".H-SIM-v1",
            a.id + ".HR-SIM-v1",
            "v1",
            "v1",
            tuple(f"A{i:02}" for i in range(1, 7)),
        )
        for p in config.products
        for a in config.core_activities
        if a.product_id == p.id and a.code in ("W-B", "W-T")
        for suffix in ((".BOTTOM",) if a.code == "W-B" else (".TOP",))
    )
    return m.ResearchProfile(
        "SIMULATION_RESEARCH_ONLY",
        "S18-SIM-A1",
        "S18-SIM-APPROVAL-001",
        PROPOSAL_DIGEST,
        ASSUMPTION_DIGEST,
        "APPROVED_ASSUMPTION_SET",
        "NOT_ESTABLISHED",
        "OPEN",
        bindings,
        tuple(m.Consumer(i, VERSION) for i in CONSUMERS),
    )


def validate_admission(config):
    new = config.schema_version == VERSION
    require(new == (config.purpose == "SIMULATION_RESEARCH_ONLY"), "SIM_VERSION_PURPOSE")
    if not new:
        require(config.specification == "S15-PROD-SPEC-1.0", "LEGACY_SPECIFICATION_VERSION")
        require(
            config.research is None
            and all(
                not o.branch
                and not o.hold_resources
                and not o.release_resources
                and not o.activity_prerequisites
                and o.handover is None
                and o.action not in ("HANDOVER", "RESTORE")
                and o.production_mode != "HR-seq"
                for o in config.operations
            ),
            "SIM_FIELDS_IN_LEGACY",
        )
        return
    approved_inputs()
    require(
        all(
            o.handover is None and o.action not in ("HANDOVER", "RESTORE")
            for o in config.operations
        ),
        "HANDOVER_MUST_BE_VALIDATED_SERVICE",
    )
    require(config.specification == "S18-PROD-SPEC-2.0", "SIM_SPECIFICATION")
    require(config.research == profile(config), "SIM_SCOPE_OR_CONSUMER_BINDING")
    require(
        len(config.people) == 15
        and sum(d.kind != "FIXTURE" for d in config.devices) == 8
        and sum(p.capacity for p in config.places if p.kind == "FINISHED") == 2,
        "SIM_RESOURCE_BOUNDARY",
    )
    require(
        all(p.variant in ("SR-W1", "SR-W2") and p.revision == "v1" for p in config.products),
        "SIM_PRODUCT_VERSION",
    )
    require(
        all(not e.id.startswith("G2") or e.status == "UNKNOWN" for e in config.evidence),
        "SIM_CANNOT_ESTABLISH_INDUSTRIAL_G2",
    )
    require(
        all(e.status != "PASS" or e.basis != "INDUSTRIAL" for e in config.evidence),
        "SIM_CANNOT_CLAIM_INDUSTRIAL_PASS",
    )
    require(
        all(re.fullmatch(r"PRODUCT-[1-9][0-9]*", p.id) for p in config.products), "SIM_PRODUCT_ID"
    )
    validate_preserved_inputs(config)
    for scope in config.research.scope_bindings:
        activity = next(a for a in config.core_activities if a.id == scope.activity_id)
        require(activity.location == "J2" and activity.code in ("W-B", "W-T"), "SIM_CELL_SCOPE")
        for mode in activity.modes:
            require(mode.enabled and mode.kind in ("H", "HR-seq"), "SIM_MODE_SCOPE")
            expected = (
                [(0.5, 0.5, "SETUP")] + [(0.5, 0.5, "WORK")] * 4 + [(0.5, 0, "UNLOAD")]
                if mode.kind == "H"
                else [(0.5, 0.5, "SETUP"), (1, 0, "ROBOT"), (0.5, 0, "UNLOAD")]
            )
            require(
                [(u.base_h, u.kappa, u.phase) for u in mode.units] == expected,
                "SIM_STAGE_NUMERICAL_DRIFT",
            )
            for u in mode.units:
                require(
                    u.equipment
                    == (("WELD-J2", "FIX-J2") if mode.kind == "H" else ("R1", "FIX-J2")),
                    "SIM_EQUIPMENT_DRIFT",
                )
                require(
                    tuple(r.qualification for r in u.roles)
                    == (
                        () if u.phase == "ROBOT" else ("WELD",) if mode.kind == "H" else ("ROBOT",)
                    ),
                    "SIM_ROLE_DRIFT",
                )


def attempt_owner(op):
    return f"ATTEMPT:{op.activity_id}:{op.attempt_index}:{op.branch.revision}"


def completed_activity(config, completed, activity):
    ids = set(completed)
    return any(
        all(
            i in ids
            for b in config.bindings
            if b.activity_id == activity and b.mode_id == mode.id
            for i in b.operation_ids
        )
        for a in config.core_activities
        if a.id == activity
        for mode in a.modes
        if mode.enabled
    )


def applicable(op, attempts):
    return not op.branch or all(
        a.activity_id != op.activity_id or a.definition_id == op.branch.definition_id
        for a in attempts
    )


PRESERVED_INPUT_DIGEST = "d54cb6ef5e454a015b44edb29417b3fa0969bd8e53eb0e04884cc37c93b2df24"


def validate_preserved_inputs(config):
    raw = (
        files("adaptive_hrc_scheduling")
        .joinpath("simulation_inputs", "S15_preserved_inputs.json")
        .read_bytes()
    )
    require(
        hashlib.sha256(raw).hexdigest() == PRESERVED_INPUT_DIGEST, "SIM_PRESERVED_BASELINE_DRIFT"
    )
    baselines = json.loads(raw)

    def template(product):
        return baselines[product.variant + ("-REWORK" if config.rework_enabled else "")]

    primary = template(config.products[0])
    for key in (
        "people",
        "devices",
        "cap",
        "min_rest_h",
        "setup_h",
        "load_h",
        "unload_h",
        "rigging_t",
    ):
        require(as_data(getattr(config, key)) == primary[key], "SIM_PRESERVED_PARAMETER:" + key)

    def renamed(value, pid):
        return json.loads(json.dumps(value).replace("PRODUCT-1", pid))

    for key in ("places", "routes", "core_activities", "core_edges"):
        expected = {}
        for product in config.products:
            for row in renamed(template(product)[key], product.id):
                if (
                    key == "routes"
                    and int(product.id.split("-")[-1]) % 2 == 0
                    and row["id"]
                    in ("ROUTE-" + product.id + ".BUFFER", "ROUTE-" + product.id + ".SHIP")
                ):
                    row = next(
                        e
                        for e in renamed(template(product)["even_buffer_routes"], product.id)
                        if e["id"] == row["id"]
                    )
                if key == "core_activities" and row["code"] in ("W-B", "W-T"):
                    for mode in row["modes"]:
                        mode["enabled"] = True
                        for unit in mode["units"]:
                            for role in unit["roles"]:
                                role["id"] = "WELDER" if mode["kind"] == "H" else "OPERATOR"
                ident = row.get("id") or (row["source"], row["target"], row["relation"])
                expected[ident] = row
        actual = as_data(getattr(config, key))
        indexed = {
            row.get("id") or (row["source"], row["target"], row["relation"]): row for row in actual
        }
        require(len(indexed) == len(actual) and indexed == expected, "SIM_PRESERVED_MAPPING:" + key)
    for product in config.products:
        expected = template(product)["products"][0]
        for key in ("bom", "mass_t", "rigging_t", "due_h"):
            require(as_data(getattr(product, key)) == expected[key], "SIM_PRESERVED_PRODUCT:" + key)
