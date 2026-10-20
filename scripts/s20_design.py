"""Build/check the S20 candidate design. This module never starts a production run."""

import argparse
import hashlib
import json
import math
from collections import Counter
from dataclasses import asdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from build_simulation_production import configuration  # noqa: E402

from adaptive_hrc_scheduling.contracts.codec import as_data  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import digest  # noqa: E402
from adaptive_hrc_scheduling.control.production_loop import (  # noqa: E402
    Scenario,
    validate_scenario,
)
from adaptive_hrc_scheduling.control.simulation_joint_policy import Budget  # noqa: E402

VERSION = "S20-DESIGN-r1"
METHODS = ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE")
PATHS = (
    "experiments/configs/s20_r2.json",
    "experiments/manifests/s20_r2.json",
    "experiments/manifests/s20_sources_r2.json",
)


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def file_sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def descriptor(variant, count):
    c = configuration(variant=variant, products=count)
    return {
        "id": f"{variant}-N{count}",
        "builder": {"variant": variant, "products": count, "rework": False},
        "configuration_sha256": digest(c),
        "schema_version": c.schema_version,
        "layout_version": c.layout_version,
        "research": as_data(c.research),
        "recipe_sha256": c.recipe_sha256,
        "products": as_data(c.products),
        "people": as_data(c.people),
        "devices": as_data(c.devices),
        "places": as_data(c.places),
        "source": "scripts/build_simulation_production.py:configuration",
        "numeric_policy": "UNMODIFIED_APPROVED_RECIPE",
        "cap": c.cap,
        "finished_capacity": sum(p.capacity for p in c.places if p.kind == "FINISHED"),
        "routes_sha256": fingerprint(as_data(c.routes)),
        "operations_sha256": fingerprint(as_data(c.operations)),
        "lots_sha256": fingerprint(as_data(c.lots)),
        "sensitivity": "PHYSICAL_VALUE_CHANGES_REQUIRE_SEPARATE_APPROVAL_AND_CONSUMER_UPDATE",
    }


def budget(window, interval, calls, wall):
    return asdict(
        Budget(
            calls,
            calls,
            2 * calls,
            calls * wall,
            1,
            1,
            wall,
            tuple(interval * i for i in range(calls)),
            window,
        )
    )


def generate():
    configs = [descriptor(v, n) for v in ("SR-W1", "SR-W2") for n in (1, 2, 3)]
    catalog = {
        "version": VERSION,
        "status": "PENDING_FREEZE",
        "configurations": configs,
        "budgets": {"DEV": budget(1, 0.5, 2, 30), "MAIN": budget(8, 8, 90, 120)},
        "common": {
            "backend": "CPU",
            "frontend": "OFF",
            "simulation_end_h": 720,
            "observation": "CURRENT_EVENT_PREFIX_ZERO_DELAY",
            "solver_seed": "ZERO_BASED_SEARCH_CALL_INDEX_NO_EXTERNAL_OVERRIDE",
            "max_turns": 20000,
            "industrial_g2": "OPEN",
            "qualification": "NOT_ESTABLISHED",
            "order_release_h": 0,
            "automatic_quality": "EXISTING_SYNTHETIC_DRIVER_RULE",
            "stochastic_repetitions": 0,
            "wall_limit_kind": "COOPERATIVE_NOT_HARD_REALTIME",
        },
        "annexes": {
            "D": {
                "status": "BLOCKED_PENDING_INTERFACE_APPROVAL",
                "family_ids": [c["id"] for c in configs if c["builder"]["products"] > 1],
                "lambda": [0, 0.5, 1],
                "cap": 0.8,
                "score": "lambda*(1-C/K)+(1-lambda)*sum_E/(15*0.8*720)",
                "tie_break": ["max_E", "stable_candidate_fingerprint"],
                "shared_budget": "MAIN",
                "needed": ["objective_injection", "common_horizon_human_tail_integration"],
            },
            "B": {
                "status": "BLOCKED_PENDING_INTERFACE_APPROVAL",
                "family_ids": [c["id"] for c in configs if c["builder"]["products"] > 1],
                "delay_h": [0.25, 1],
                "fatigue_noise_amplitude": [0.02, 0.05],
                "missing_probability": [0.1, 0.3],
                "base": "ZERO_DELAY_NO_NOISE_NO_MISSING",
                "seed_ids": [f"B-TEST-{i:02}" for i in range(8)],
                "factor_design": "ONE_FACTOR_AT_A_TIME",
                "stream_scheme": "SHA256_UTF8_CANONICAL_ARRAY_v1",
                "sampling_population": "FINITE_REGISTERED_SEED_SET",
                "needed": [
                    "authorized_observation_projection",
                    "causal_audit_for_distorted_observation",
                ],
            },
            "REFERENCE": {
                "status": "SEPARATE_STATIC_DOMAIN_NOT_MAIN_A",
                "entry": "scripts/run_cpsat_reference.py",
                "formal_test_instances": [],
                "reason": "Existing instances are exposed development witnesses; no matched full production optimality claim",
            },
        },
    }
    rows = []

    def add(split, config, kind, scenario, groups, b):
        identity = fingerprint({"config": config["configuration_sha256"], "scenario": scenario})
        pair = f"{split}-{config['id']}-{kind}"
        for method in METHODS:
            rows.append(
                {
                    "id": pair + "-" + method,
                    "pair_id": pair,
                    "instance_identity": identity,
                    "split": split,
                    "groups": groups,
                    "config_id": config["id"],
                    "config_sha256": config["configuration_sha256"],
                    "method": method,
                    "scenario": scenario,
                    "budget_id": b,
                    "replicate": 0,
                    "random_stream": "DETERMINISTIC_SCENARIO_NO_EXTERNAL_RANDOM_DRAWS",
                    "execution_authorization": "DEVELOPMENT_ONLY"
                    if split == "dev"
                    else "NOT_AUTHORIZED",
                    "status": "PENDING_FREEZE",
                    "outcome": None,
                }
            )

    for c in configs:
        if c["builder"]["products"] == 1:
            split = "dev" if c["builder"]["variant"] == "SR-W1" else "tune"
            add(split, c, "NORMAL", asdict(Scenario(id=f"S20-{split}", until_h=1)), [], "DEV")
        else:
            scenarios = {
                "NORMAL": Scenario(id="S20-NORMAL"),
                "LATE_MATERIAL": Scenario(
                    id="S20-LATE-MATERIAL", delayed_lot="LOT-PRODUCT-1-STEEL", arrival_after_h=12
                ),
                "LATE_RECEIPT": Scenario(id="S20-LATE-RECEIPT", receive_after_h=480),
                "LOADED_FAILURE": Scenario(id="S20-LOADED-FAILURE", loaded_failure=True),
            }
            # Use the actual steel incoming-lot ID, not an invented alias.
            actual = configuration(**c["builder"])
            steel_lot = next(
                lot.id for lot in actual.lots if not lot.parent_ids and lot.material == "STEEL"
            )
            scenarios["LATE_MATERIAL"] = Scenario(
                id="S20-LATE-MATERIAL", delayed_lot=steel_lot, arrival_after_h=12
            )
            for kind, s in scenarios.items():
                add("test", c, kind, asdict(s), ["A", "C"], "MAIN")
    manifest = {
        "version": VERSION,
        "status": "PENDING_FREEZE",
        "config_catalog_sha256": fingerprint(catalog),
        "rows": rows,
        "formal_execution_enabled": False,
        "test_pair_count": 16,
        "test_run_count": 64,
        "tuning_policy": "NO_TUNING_RUNS_IN_S20_FIXED_PARAMETERS_NO_TEST_SELECTION",
    }
    import subprocess

    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    selected = [
        p for p in tracked if p.startswith(("src/", "sim/", "desktop/", "scripts/", "schemas/"))
    ]
    selected += [
        "pyproject.toml",
        "uv.lock",
        ".python-version",
        "docs/model/S18_simulation_scope_approval_r1.json",
    ]
    sources = {
        "version": VERSION,
        "scope": "INHERITED_PRODUCTION_AND_DISPLAY_BASELINE",
        "files": {p: file_sha(ROOT / p) for p in sorted(set(selected))},
    }
    manifest["source_catalog_sha256"] = fingerprint(sources)
    manifest["source_file_count"] = len(sources["files"])
    return catalog, manifest, sources


def validate_design(catalog, manifest, sources, root=ROOT):
    require(catalog["version"] == manifest["version"] == sources["version"] == VERSION, "VERSION")
    require(catalog["status"] == manifest["status"] == "PENDING_FREEZE", "FREEZE_STATUS")
    require(manifest["formal_execution_enabled"] is False, "FORMAL_EXECUTION_LOCK")
    require(fingerprint(catalog) == manifest["config_catalog_sha256"], "CATALOG_DIGEST")
    require(fingerprint(sources) == manifest["source_catalog_sha256"], "SOURCE_CATALOG_DIGEST")
    require(len(sources["files"]) == manifest["source_file_count"] > 0, "SOURCE_COUNT")
    for p, h in sources["files"].items():
        target = (root / p).resolve()
        require(target.is_relative_to(root.resolve()), "SOURCE_PATH")
        require(target.is_file() and file_sha(target) == h, "SOURCE_DIGEST:" + p)
    descriptors = {c["id"]: c for c in catalog["configurations"]}
    require(len(descriptors) == len(catalog["configurations"]) == 6, "CONFIGURATION_IDS")
    concrete = {}
    config_digests = {}
    for key, c in descriptors.items():
        actual = configuration(**c["builder"])
        require(
            c == descriptor(c["builder"]["variant"], c["builder"]["products"]),
            "CONFIGURATION_BINDING:" + key,
        )
        concrete[key] = actual
        config_digests[key] = digest(actual)
    for b in catalog["budgets"].values():
        Budget(**b).validate()
    require(catalog["budgets"]["DEV"] == json.loads(canonical(budget(1, 0.5, 2, 30))), "DEV_BUDGET")
    require(
        catalog["budgets"]["MAIN"] == json.loads(canonical(budget(8, 8, 90, 120))), "MAIN_BUDGET"
    )
    seen_ids, identities, pairs = set(), {}, {}
    for row in manifest["rows"]:
        require(row["id"] not in seen_ids, "DUPLICATE_RUN")
        seen_ids.add(row["id"])
        require(row["split"] in ("dev", "tune", "test"), "SPLIT")
        require(row["method"] in METHODS and row["outcome"] is None, "METHOD_OR_UNRUN_STATE")
        require(type(row["replicate"]) is int and row["replicate"] == 0, "DETERMINISTIC_REPLICATE")
        require(row["status"] == "PENDING_FREEZE", "ROW_STATUS")
        require(
            row["execution_authorization"]
            == ("DEVELOPMENT_ONLY" if row["split"] == "dev" else "NOT_AUTHORIZED"),
            "ROW_AUTHORIZATION",
        )
        c = concrete[row["config_id"]]
        require(row["config_sha256"] == config_digests[row["config_id"]], "CONFIG_DIGEST")
        s = Scenario(**row["scenario"])
        validate_scenario(c, s)
        require(
            s.delayed_lot is None
            or s.delayed_lot in {lot.id for lot in c.lots if not lot.parent_ids},
            "DELAYED_LOT",
        )
        require(row["budget_id"] == ("MAIN" if row["split"] == "test" else "DEV"), "SPLIT_BUDGET")
        require(s.until_h == (720 if row["split"] == "test" else 1), "SPLIT_WINDOW")
        identity = fingerprint(
            {"config": config_digests[row["config_id"]], "scenario": row["scenario"]}
        )
        require(identity == row["instance_identity"], "INSTANCE_IDENTITY")
        # Ignore labels when detecting the same numerical scenario across splits.
        semantic_scenario = dict(row["scenario"])
        semantic_scenario.pop("id")
        semantic_key = fingerprint(
            {"config": config_digests[row["config_id"]], "scenario": semantic_scenario}
        )
        require(
            semantic_key not in identities or identities[semantic_key] == row["split"],
            "SPLIT_LEAKAGE",
        )
        identities[semantic_key] = row["split"]
        pairs.setdefault(row["pair_id"], []).append(row)
    for pair in pairs.values():
        require(
            len(pair) == 4 and {r["method"] for r in pair} == set(METHODS), "INCOMPLETE_METHOD_PAIR"
        )
        signatures = {
            fingerprint({k: v for k, v in r.items() if k not in ("id", "method")}) for r in pair
        }
        require(len(signatures) == 1, "UNFAIR_PAIR")
    counts = Counter(r["split"] for r in manifest["rows"])
    require(counts == {"dev": 4, "tune": 4, "test": 64}, "RUN_ACCOUNTING")
    require(
        manifest["test_pair_count"] == 16 and manifest["test_run_count"] == 64, "DECLARED_COUNTS"
    )
    return {
        "status": "PASS",
        "rows": len(seen_ids),
        "pairs": len(pairs),
        "splits": dict(counts),
        "sources": len(sources["files"]),
        "formal_runs_executed": 0,
    }


def load_design():
    return tuple(read(ROOT / p) for p in PATHS)


def authorize_development(row):
    require(
        row["split"] == "dev" and row["execution_authorization"] == "DEVELOPMENT_ONLY", "DEV_ONLY"
    )


def keyed_uniform(seed, stream, entity, ordinal):
    """Candidate annex B stream; never installed in the production observer."""
    require(type(ordinal) is int and ordinal >= 0, "STREAM_ORDINAL")
    raw = hashlib.sha256(canonical([VERSION, seed, stream, entity, ordinal]).encode()).digest()
    return (int.from_bytes(raw[:8], "big") >> 11) / (2**53)


def paired_summary(pairs):
    """Finite-design summary: preserve failures, no fictitious stochastic CI."""
    differences, failures = [], Counter()
    ids = set()
    for row in pairs:
        require(row["pair_id"] not in ids, "DUPLICATE_ANALYSIS_PAIR")
        ids.add(row["pair_id"])
        values = []
        for side in ("left", "right"):
            value = row[side]
            status = value["status"]
            require(status in ("VALID", "FAILED", "MISSING", "CENSORED"), "ANALYSIS_STATUS")
            failures[side + ":" + status] += 1
            if status == "VALID":
                require(
                    type(value["value"]) in (int, float) and math.isfinite(value["value"]),
                    "NONFINITE_METRIC",
                )
                values.append(value["value"])
        if len(values) == 2:
            differences.append(values[0] - values[1])
    return {
        "planned_pairs": len(pairs),
        "valid_pairs": len(differences),
        "statuses": dict(failures),
        "paired_mean": sum(differences) / len(differences) if differences else None,
        "paired_min": min(differences) if differences else None,
        "paired_max": max(differences) if differences else None,
        "confidence_interval": None,
        "inference": "FINITE_DESIGN_DESCRIPTIVE_ONLY",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        from s20_extension_design import EXTENSIONS, build

        for p, value in zip((*PATHS, EXTENSIONS), build()):
            write(ROOT / p, value)
    print(json.dumps(validate_design(*load_design()), indent=2))


if __name__ == "__main__":
    main()
