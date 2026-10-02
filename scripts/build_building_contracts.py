"""Generate only the frozen C04 steel fixtures; not an S11 instance generator."""

import argparse
import csv
import json
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.contracts.building import (
    TOP_LEVEL,
    digest,
    dumps,
    planning_input,
    validate,
)
from adaptive_hrc_scheduling.contracts.codec import schema
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
G2 = (
    "G2-JOINT",
    "G2-WPS",
    "G2-PROGRAM",
    "G2-FIXTURE",
    "G2-PEOPLE",
    "G2-ISOLATION",
    "G2-INSPECTION",
    "G2-OUTPUT",
)


def build_configuration(variant="SR-W1", *, products=1):
    people = []
    for pid, qual, rate in [
        ("P1", "PREP", 0.08),
        ("W1", "WELD", 0.15),
        ("W2", "WELD", 0.15),
        ("OP1", "ROBOT", 0.04),
        ("AF1", "ASSEMBLE", 0.12),
        ("AF2", "ASSEMBLE", 0.12),
        ("E1", "ELECTRIC", 0.10),
        ("PL1", "PLUMB", 0.10),
        ("T1", "WET", 0.12),
        ("T2", "WET", 0.12),
        ("C1", "COAT", 0.12),
        ("QA1", "QA", 0.08),
        ("Lop", "CRANE", 0.15),
        ("Lrig", "RIG", 0.15),
        ("Lsig", "SIGNAL", 0.15),
    ]:
        people.append(
            b.Person(
                pid,
                (qual,) + (("HOIST",) if pid == "P1" else ()),
                10000,
                0.2,
                rate,
                0.02,
                0.2,
                b.Calendar(24, (b.Window(0, 4), b.Window(4.5, 8.5))),
            )
        )
    people_by = {p.id: p for p in people}
    resources = [
        b.Resource(r, "BUFFER" if r == "BUF" else "BAY", 2 if r == "BUF" else 1, 0)
        for r in ("PRE", "J2", "BUF", "J3", "F1", "Q1", "OUT1")
    ]
    resources += [
        b.Resource(r, "EQUIPMENT", 1, 12 if r == "CR1" else 3 if r == "HST1" else 0)
        for r in ("CUT1", "WELD1", "R1", "HST1", "CR1", "TEST1")
    ]
    resources += [b.Resource(r, "FIXTURE", 1, 0) for r in ("FIX-J2", "FIX-J3")]
    resources += [b.Resource(r, "ROUTE", 1, 0) for r in ("ROUTE-COMP", "ROUTE-MODULE")]
    evidence = [
        b.Evidence(g, "UNKNOWN", "UNRESOLVED", "docs/research/production_evidence.md", "v1")
        for g in ("G1", "G4", "G5", "G6", "G7", *G2)
    ]
    rows = list(
        csv.DictReader(
            (ROOT / "docs/model/steel_process.tsv").read_text(encoding="utf-8").splitlines(),
            delimiter="\t",
        )
    )
    edge_rows = list(
        csv.DictReader(
            (ROOT / "docs/model/steel_edges.tsv").read_text(encoding="utf-8").splitlines(),
            delimiter="\t",
        )
    )
    products_out = []
    components = []
    materials = []
    activities = []
    edges = []
    bom_parts = {
        "CUT": ("B-ST",),
        "W-B": ("B-ST",),
        "W-T": ("B-ST",),
        "W-3D": ("B-ST",),
        "COAT": ("B-ST",),
        "FLOOR": ("B-FL", "B-WT"),
        "MEP-E": ("B-ME",),
        "MEP-P": ("B-ME",),
        "LINING": ("B-EN",),
        "WPROOF": ("B-WT",),
        "TEST-SET": ("B-WT",),
        "TILE": ("B-WT",),
        "EXT": ("B-FI", "B-EN"),
        "PAINT": ("B-EN",),
        "FIT": ("B-FI", "B-ME"),
        "PACK": ("B-PR",),
    }
    for n in range(1, products + 1):
        pid = f"PRODUCT-{n}"

        def prefix(code):
            return pid + "." + code

        bom = tuple(
            b.BOMItem(i, q, u)
            for i, q, u in [
                ("B-ST", 1, "set"),
                ("B-FL", 18, "m2"),
                ("B-EN", 1, "set"),
                ("B-WT", 1, "set"),
                ("B-ME", 1, "set"),
                ("B-FI", 1, "set"),
                ("B-PR", 1, "set"),
            ]
        )
        if variant == "SR-W2":
            bom += tuple(
                b.BOMItem(i, 1, "set") for i in ("B-BRANCH", "B-EXTRA-BASIN", "B-EXTRA-SOCKET")
            )
        products_out.append(
            b.Product(
                pid, f"ORDER-{n}", variant, "v1", bom, 8, 1, 0, 192 if variant == "SR-W2" else 168
            )
        )
        components += [
            b.Component(
                prefix(k), pid, k, 4 if k == "COLUMNS" else 1, "PRE", 2 if k != "COLUMNS" else 4
            )
            for k in ("BOTTOM", "TOP", "COLUMNS")
        ]
        for row in rows:
            code = row["activity"]
            aid = prefix(code)
            loc = row["location"].split(">")[0]
            if code == "JOIN-IN":
                loc = "BUF"
            qual = prefix("METHOD-" + code)
            checkpoint = prefix("CHECKPOINT-" + code)
            evidence += [
                b.Evidence(qual, "UNKNOWN", "UNRESOLVED", row["existence_source"], "v1"),
                b.Evidence(checkpoint, "UNKNOWN", "UNRESOLVED", row["legal_checkpoint_A_U"], "v1"),
            ]
            quality = None
            release = None
            if code.startswith("Q-"):
                quality = prefix("CRITERION-" + code)
                evidence.append(
                    b.Evidence(
                        quality, "UNKNOWN", "UNRESOLVED", "docs/model/selected_steel.md", "v1"
                    )
                )
            if code.startswith("WAIT-"):
                release = prefix("RELEASE-" + code)
                evidence.append(
                    b.Evidence(
                        release, "UNKNOWN", "UNRESOLVED", "docs/model/selected_steel.md", "v1"
                    )
                )
            mat_ids = ()
            if code in bom_parts:
                bids = bom_parts[code]
                if variant == "SR-W2":
                    bids += (
                        ("B-BRANCH",)
                        if code == "MEP-P"
                        else ("B-EXTRA-BASIN",)
                        if code == "FIT"
                        else ("B-EXTRA-SOCKET",)
                        if code == "MEP-E"
                        else ()
                    )
                mid = prefix("KIT-" + code)
                materials.append(b.Material(mid, pid, aid, bids, 1, True, True, True))
                mat_ids = (mid,)
            roles = tuple(x for x in row["roles"].replace("末端", "").split(",") if x != "-")
            equipment = tuple(x for x in row["equipment"].split(",") if x not in ("-", "J2", "J3"))
            if code in ("W-B", "W-T"):
                roles = ("W1",)
                equipment = ("WELD1", "FIX-J2")
            if code == "W-3D":
                equipment = ("WELD1", "FIX-J3")
            move = None
            if ">" in row["location"]:
                src, dst = row["location"].split(">")
                entities = (
                    (prefix("BOTTOM"), prefix("TOP"), prefix("COLUMNS"))
                    if code == "JOIN-IN"
                    else (prefix("BOTTOM" if code in ("MV-IN-B", "MV-B") else "TOP"),)
                    if code.startswith("MV-")
                    else (pid,)
                )
                move = b.Move(
                    src,
                    dst,
                    "ROUTE-COMP" if code.startswith("MV-") else "ROUTE-MODULE",
                    equipment[0],
                    entities,
                    (0.25, 0.5, 1) if code == "JOIN-IN" else (float(row["active_base_h_E"]),),
                    ("G1", "G6", qual),
                    ("v1", "v1", "v1"),
                )
            modes = []
            for kind in (
                ("H", "HR-seq")
                if code in ("W-B", "W-T")
                else ("MOVE",)
                if move
                else ("WAIT",)
                if code.startswith("WAIT-")
                else ("GATE",)
                if code == "READY"
                else ("H-team",)
            ):
                units = []

                def role_records(ids):
                    return tuple(
                        b.Role(
                            i,
                            "HOIST"
                            if i == "P1" and code.startswith("MV-")
                            else people_by[i].qualifications[0],
                        )
                        for i in ids
                    )

                if kind == "HR-seq":
                    pieces = [
                        (0.5, "SETUP", ("OP1",), ("R1", "FIX-J2"), 0.5),
                        (1, "ROBOT", (), ("R1", "FIX-J2"), 0),
                        (0.5, "UNLOAD", ("OP1",), ("R1", "FIX-J2"), 0),
                    ]
                elif kind == "H":
                    pieces = (
                        [(0.5, "SETUP", roles, equipment, 0.5)]
                        + [(0.5, "WORK", roles, equipment, 0.5)] * 4
                        + [(0.5, "UNLOAD", roles, equipment, 0)]
                    )
                else:
                    duration = float(row["active_base_h_E"])
                    if variant == "SR-W2" and code in ("MEP-P", "Q-FIN"):
                        duration += 0.5
                    phase = (
                        "MOVE" if move else "CHECK" if code.startswith(("Q-", "WAIT-")) else "WORK"
                    )
                    kappa = 0 if phase in ("MOVE", "CHECK") else 0.5
                    chunks = (
                        [duration]
                        if move
                        else [0.5] * int(duration // 0.5)
                        + ([duration % 0.5] if duration % 0.5 else [])
                    )
                    pieces = [(d, phase, roles, equipment, kappa) for d in chunks if d]
                for u, (d, phase, rs, eq, kappa) in enumerate(pieces):
                    units.append(
                        b.WorkUnit(
                            f"U{u + 1}",
                            d,
                            checkpoint,
                            phase,
                            role_records(rs),
                            eq,
                            kappa,
                            False if phase in ("WORK", "ROBOT") else True,
                        )
                    )
                modes.append(
                    b.Mode(
                        prefix(kind),
                        kind,
                        "v1",
                        (qual, "G5", *G2) if kind == "HR-seq" else (qual, "G5"),
                        ("v1",) * (2 + len(G2) if kind == "HR-seq" else 2),
                        tuple(units),
                        kind != "HR-seq",
                    )
                )
            activities.append(
                b.Activity(
                    aid,
                    pid,
                    code,
                    loc,
                    row["face"],
                    tuple(modes),
                    mat_ids,
                    float(row["wait_h_E"]),
                    release,
                    quality,
                    move,
                )
            )
        materials.append(
            b.Material(
                prefix("REPAIR-TEST-KIT"), pid, prefix("TEST-SET"), ("B-WT",), 1, True, True, True
            )
        )
        materials.append(
            b.Material(prefix("REPAIR-KIT"), pid, prefix("Q-POND"), ("B-WT",), 1, True, True, True)
        )
        edges += [b.Edge(prefix(e["from"]), prefix(e["to"]), e["relation"]) for e in edge_rows]
    parameters = tuple(
        b.Parameter(i, v, u, "E", "docs/model/parameters.md", "SYNTHETIC_UNCALIBRATED")
        for i, v, u in [
            ("N07-cap", 0.8, "1"),
            ("N09-recovery", 0.2, "h^-1"),
            ("N12-rest", 0.25, "h"),
            ("N06-handover", 0.1, "h"),
            ("N06-restore", 0.1, "h"),
        ]
    )
    config = b.Configuration(
        "C04-1.0",
        "BW-" + variant + "-" + str(products),
        "C03-0.3",
        b.Units("h", "h^-1", "F.h", "t", "m"),
        "RESEARCH_BLOCKED",
        0.8,
        0.25,
        240,
        tuple(people),
        tuple(resources),
        tuple(products_out),
        tuple(components),
        tuple(materials),
        tuple(activities),
        tuple(edges),
        tuple(evidence),
        (b.FacePair("D-E", "W-P", "G6"),),
        parameters,
    )
    validate(config)
    return config


def synthetic_fixture(config, *, hr=False):
    """Test-only conditional branch input. Never a claim of acquired qualification."""
    c = replace(
        config,
        purpose="SYNTHETIC_TEST_ONLY",
        evidence=tuple(
            replace(
                e, status="PASS", basis="SYNTHETIC_TEST", reference="CONDITIONAL_CODE_BRANCH_ONLY"
            )
            if hr or e.id not in G2
            else e
            for e in config.evidence
        ),
    )
    if hr:
        c = replace(
            c,
            activities=tuple(
                replace(a, modes=tuple(replace(m, enabled=True) for m in a.modes))
                for a in c.activities
            ),
        )
    validate(c)
    return c


def initial_snapshot(c):
    scenario = b.HiddenScenario("C04-1.0", c.id, 0, ())
    return b.ExecutionSnapshot(
        "C04-1.0",
        c.id,
        digest(c),
        0,
        0,
        tuple(
            b.ProductState(p.id, "UNASSEMBLED", "RELEASED", False, None, (), False)
            for p in c.products
        ),
        tuple(b.ComponentState(x.id, "UNFABRICATED", False) for x in c.components),
        tuple(
            b.MaterialState(x.id, x.arrived, x.identified, x.released, None) for x in c.materials
        ),
        (),
        (),
        tuple(b.HumanState(p.id, p.initial_f, 0, p.initial_f, 0) for p in c.people),
        (),
        (),
        (),
        (),
        (),
        tuple(p.id for p in c.products if p.release_h == 0),
        (),
        0,
        0,
        scenario,
        (),
        (),
        (),
        (),
    )


def generated():
    c = build_configuration()
    w2 = build_configuration("SR-W2")
    obs = b.PlanningObservation(
        "C04-1.0",
        c.id,
        "OBS-0",
        0,
        0,
        0,
        0,
        tuple(b.ObservedProduct(p.id, "RELEASED", "UNASSEMBLED", (), False) for p in c.products),
        (),
        (),
        (),
    )
    a = c.activities[0]
    m = a.modes[0]
    cmd = b.DispatchCommand(
        "C04-1.0", c.id, "COMMAND-1", 0, 0, a.id, m.id, 0, 0, (b.RoleBinding("P1", "P1"),)
    )
    samples = {
        "configuration": c,
        "sr_w2": w2,
        "planning_observation": obs,
        "planning_input": planning_input(c, obs),
        "dispatch": cmd,
        "plan": b.Plan(
            "C04-1.0",
            c.id,
            obs.id,
            (),
            tuple(b.Prediction(p.id, None) for p in c.products),
            "INCOMPLETE",
        ),
        "execution_event": b.ExecutionEvent(
            "C04-1.0", c.id, "EVENT-0", 0, "INITIALIZED", c.id, None, "SYNTHETIC_UNCALIBRATED"
        ),
        "execution_snapshot": initial_snapshot(c),
        "hidden_scenario": b.HiddenScenario("C04-1.0", c.id, 0, ()),
        "offline_evaluation": b.OfflineEvaluation(
            "C04-1.0",
            c.id,
            240,
            initial_snapshot(c).products,
            initial_snapshot(c).people,
            1,
            0,
            "EXECUTOR_SUMMARY_NOT_S10",
        ),
        "run_manifest": b.RunManifest(
            "C04-1.0",
            c.id,
            digest(c),
            "C03-0.3",
            "example.uncommitted",
            0,
            "building-event",
            "PLANNED",
            ("G1", "G2", "G4", "G5", "G6", "G7"),
            "NOT_ESTABLISHED",
        ),
    }
    out = {
        f"examples/building_contracts/{name}.json": dumps(value, config=c)
        for name, value in samples.items()
    }
    for cls in TOP_LEVEL:
        out[f"schemas/building/{cls.__name__}.schema.json"] = (
            json.dumps(schema(cls), indent=2, ensure_ascii=False, sort_keys=True) + "\n"
        )
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for name, text in generated().items():
        path = ROOT / name
        if args.check:
            if not path.exists() or path.read_bytes() != text.encode("utf-8"):
                raise SystemExit("Generated drift: " + name)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8", newline="\n")
    print("C04: 11 examples and 10 schemas " + ("verified" if args.check else "generated"))


if __name__ == "__main__":
    main()
