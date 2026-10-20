"""S20 r2 input generation and checks, with all formal executions locked."""

import argparse
from dataclasses import asdict

from s20_design import (
    METHODS,
    PATHS,
    ROOT,
    fingerprint,
    generate,
    read,
    require,
    validate_design,
    write,
)

from adaptive_hrc_scheduling.control.research_projection import ObservationSettings
from adaptive_hrc_scheduling.research_objective import WeightedObjective

EXTENSIONS = "experiments/manifests/s20_extensions_r2.json"


def extension_rows(catalog):
    rows = []
    for config in catalog["configurations"]:
        count = config["builder"]["products"]
        if count == 1 and config["builder"]["variant"] == "SR-W2":
            continue
        split = "dev" if count == 1 else "test"
        end = 1 if split == "dev" else 720
        budget = "DEV" if split == "dev" else "MAIN"

        def append(group, label, method, objective=None, observation=None):
            rows.append(
                dict(
                    id=f"S20-r2-{split}-{config['id']}-{group}-{label}-{method}",
                    pair_id=f"S20-r2-{split}-{config['id']}-{group}-{label}",
                    split=split,
                    group=group,
                    config_id=config["id"],
                    config_sha256=config["configuration_sha256"],
                    method=method,
                    end_h=end,
                    budget_id=budget,
                    objective=objective,
                    observation=observation,
                    scenario="NORMAL",
                    status="PENDING_FREEZE",
                    outcome=None,
                    execution_authorization="DEVELOPMENT_ONLY"
                    if split == "dev"
                    else "NOT_AUTHORIZED",
                )
            )

        for weight in (0, 0.5, 1):
            append(
                "D",
                f"lambda-{weight}",
                "ADAPTIVE_JOINT",
                objective=asdict(WeightedObjective(weight)),
            )
        settings = [("BASE", ObservationSettings(seed="B-BASE-DETERMINISTIC"))]
        seeds = ("B-DEV-00",) if split == "dev" else tuple(f"B-TEST-{i:02}" for i in range(8))
        delays = (0.25,) if split == "dev" else (0.25, 1)
        for delay in delays:
            settings.append(
                (f"delay-{delay}", ObservationSettings(delay_h=delay, seed="B-DELAY-DETERMINISTIC"))
            )
        amplitudes = (0.02,) if split == "dev" else (0.02, 0.05)
        probabilities = (0.3, 1) if split == "dev" else (0.1, 0.3)
        for seed in seeds:
            for a in amplitudes:
                settings.append(
                    (f"noise-{a}-{seed}", ObservationSettings(fatigue_noise=a, seed=seed))
                )
            for probability in probabilities:
                settings.append(
                    (
                        f"missing-{probability}-{seed}",
                        ObservationSettings(missing_probability=probability, seed=seed),
                    )
                )
        for label, setting in settings:
            for method in METHODS:
                append("B", label, method, observation=asdict(setting))
    return rows


def build():
    catalog, manifest, sources = generate()
    catalog["candidate_revision"] = "r2"
    catalog["annexes"]["D"].update(
        status="IMPLEMENTED_PENDING_FREEZE",
        methods=["ADAPTIVE_JOINT"],
        additional_test_runs=12,
        tail_policy="S20-REST-TAIL-r1",
    )
    catalog["annexes"]["B"].update(
        status="IMPLEMENTED_PENDING_FREEZE",
        baseline="SEPARATE_PERIODIC_PROJECTED_BASELINE",
        additional_test_runs=560,
        period_h=0.25,
        A_baseline_reuse=False,
    )
    additions = [p.relative_to(ROOT).as_posix() for p in (ROOT / "src").rglob("*.py")]
    additions += [
        "scripts/s20_design.py",
        "scripts/run_s20_development.py",
        "scripts/s20_extension_design.py",
        "scripts/run_s20_extension_development.py",
        "tests/test_s20_design.py",
        "tests/test_s20_extensions.py",
    ]
    from s20_design import file_sha

    sources["files"].update({p: file_sha(ROOT / p) for p in additions})
    sources["scope"] = "S20_R2_EXACT_IMPLEMENTATION_AND_INHERITED_ASSETS"
    manifest.update(
        candidate_revision="r2",
        config_catalog_sha256=fingerprint(catalog),
        source_catalog_sha256=fingerprint(sources),
        source_file_count=len(sources["files"]),
    )
    extensions = dict(
        version="S20-EXTENSIONS-r2",
        status="PENDING_FREEZE",
        formal_execution_enabled=False,
        config_catalog_sha256=fingerprint(catalog),
        source_catalog_sha256=fingerprint(sources),
        core_manifest_sha256=fingerprint(manifest),
        rows=extension_rows(catalog),
        formal_runs=dict(A_C=64, D=12, B=560, total=636),
        development_runs=dict(D=3, B=20, total=23),
        baseline_revision_reason="B periodic sampling requires its own zero-perturbation baseline; A current-prefix baseline is not equivalent",
    )
    return catalog, manifest, sources, extensions


def check():
    catalog, manifest, sources = (read(ROOT / p) for p in PATHS)
    summary = validate_design(catalog, manifest, sources)
    extensions = read(ROOT / EXTENSIONS)
    require(
        extensions["version"] == "S20-EXTENSIONS-r2"
        and extensions["status"] == "PENDING_FREEZE"
        and extensions["formal_execution_enabled"] is False,
        "EXTENSION_EXECUTION_LOCK",
    )
    require(
        extensions["config_catalog_sha256"] == fingerprint(catalog)
        and extensions["source_catalog_sha256"] == fingerprint(sources)
        and extensions["core_manifest_sha256"] == fingerprint(manifest),
        "EXTENSION_BINDING",
    )
    require(extensions["rows"] == extension_rows(catalog), "EXTENSION_GRID_OR_AUTHORIZATION")
    require(
        len({r["id"] for r in extensions["rows"]}) == len(extensions["rows"]),
        "EXTENSION_DUPLICATE_ID",
    )
    test = [r for r in extensions["rows"] if r["split"] == "test"]
    dev = [r for r in extensions["rows"] if r["split"] == "dev"]
    require(len(test) == 572 and len(dev) == 23, "EXTENSION_COUNTS")
    for row in extensions["rows"]:
        if row["observation"]:
            ObservationSettings(**row["observation"]).validate()
        if row["objective"]:
            WeightedObjective(**row["objective"]).validate()
    return dict(
        summary,
        extension_test_rows=572,
        extension_dev_rows=23,
        total_formal_rows=636,
        formal_runs_executed=0,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if args.write:
        for p, data in zip((*PATHS, EXTENSIONS), build()):
            write(ROOT / p, data)
    import json

    print(json.dumps(check(), indent=2))


if __name__ == "__main__":
    main()
