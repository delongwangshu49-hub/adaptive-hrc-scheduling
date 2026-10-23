"""Rebuild complete P043 candidates, reject truncations and bind actual adoption."""

import argparse
import json
from dataclasses import replace
from pathlib import Path

from adaptive_hrc_scheduling.algorithms.lns import fingerprint
from adaptive_hrc_scheduling.algorithms.simulation_joint import (
    Genes,
    Schedule,
    SimulationJointProblem,
    Step,
)
from adaptive_hrc_scheduling.contracts.codec import decode
from adaptive_hrc_scheduling.contracts.production import digest
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory


def verify(directory):
    root = Path(directory)
    initial = decode(m.Configuration, json.loads((root / "configuration.json").read_text()))
    saved = json.loads((root / "session-state.json").read_text())
    rows = []
    for path in sorted(root.glob("candidate-*.json")):
        data = json.loads(path.read_text())
        history = WorkforceHistory(initial, data["catalog_generations"])
        history.active_products = set(saved["active_products"])
        obs = decode(m.PlanningObservation, data["observation"])
        config = history.views[obs.config_sha256]
        full = decode(m.ExecutionSnapshot, data["snapshot"])
        n = data["prefix_event_count"]
        state = replace(
            full.events[n - 1].state,
            intervals=tuple(x for x in full.state.intervals if x.end_h <= obs.sampled_h),
        )
        prefix = m.ExecutionSnapshot(
            config.schema_version,
            config.id,
            digest(config),
            full.run_id,
            full.epoch,
            state,
            full.events[:n],
        )
        raw = data["candidate"]
        g = raw["genes"]
        genes = Genes(
            *(tuple(tuple(x) for x in g[k]) for k in ("modes", "crews", "order", "slots")),
            tuple(g["rests"]),
            g["initial_action_only"],
        )
        candidate = Schedule(
            raw["anchor_sha256"],
            raw["end_h"],
            genes,
            tuple(Step(decode(m.Plan, x["plan"]), x["advance_to_h"]) for x in raw["steps"]),
            raw["scope"],
        )
        source_rows = tuple(x for x in data["decisions"] if x["event_count"] < n)
        problem = SimulationJointProblem(
            config, obs, prefix, decisions=source_rows, end_h=data["end_h"], catalog=history
        )
        actual = problem.verify(candidate)
        bad = problem.verify(replace(candidate, steps=candidate.steps[:-1]))
        if not actual.valid or bad.valid:
            raise ValueError((path.name, actual, bad))
        rebuilt, _ = problem.preview(candidate)
        if rebuilt != full:
            raise ValueError("CANDIDATE_REBUILD:" + path.name)
        rows.append(
            dict(
                file=path.name,
                status="PASS",
                candidate_sha256=fingerprint(raw),
                full_end_h=full.state.time_h,
                after_person_arrival=any(
                    r.get("workforce_kind") == "PERSON_ARRIVE" for r in data["catalog_generations"]
                ),
                truncation_rejected=True,
                truncation_reasons=bad.reasons,
            )
        )
    if not rows:
        raise ValueError("COMPLETE_CANDIDATE_REQUIRED")
    journal = json.loads((root / "online-journal.json").read_text())
    adopted = [
        dict(
            sequence=r["sequence"],
            command=r["plan_operation"],
            receipt_id=r["receipt_id"],
            candidate_sha256=r["cache_sha256"],
        )
        for r in journal
        if r.get("selected_source") == "VERIFIED_CACHE" and r.get("receipt_kind") == "STARTED"
    ]
    keys = {r["candidate_sha256"] for r in rows if r["after_person_arrival"]}
    if not any(r["candidate_sha256"] in keys for r in adopted):
        raise ValueError("PERSON_CHANGE_ACTUAL_ADOPTION_REQUIRED")
    return dict(
        status="PASS",
        identity="P043-CANDIDATE-INDEPENDENT-r1",
        candidates=rows,
        truncations_rejected=len(rows),
        actual_adoption=adopted,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = verify(args.directory)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            dict(
                status=result["status"],
                candidates=len(result["candidates"]),
                adoptions=len(result["actual_adoption"]),
            )
        )
    )
