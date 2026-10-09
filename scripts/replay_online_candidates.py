"""Rebuild saved S19 candidates from actual prefixes and perform full offline audits."""

import argparse
import gzip
import json
import math
from pathlib import Path

from adaptive_hrc_scheduling.algorithms.lns import fingerprint
from adaptive_hrc_scheduling.algorithms.simulation_joint import (
    Genes,
    Schedule,
    SimulationJointProblem,
    Step,
)
from adaptive_hrc_scheduling.contracts.codec import as_data, decode, require
from adaptive_hrc_scheduling.domain import production as m


def replay(folder):
    config = decode(m.Configuration, json.loads((folder / "configuration.json").read_text()))
    saved = json.loads((folder / "online-candidates.json").read_text())
    journal = json.loads((folder / "online-journal.json").read_text())
    proofs = []
    for row in saved:
        raw, events = row["candidate"], []
        try:
            with gzip.open(folder / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
                for count, line in enumerate(stream):
                    if count >= row["prefix_event_count"]:
                        break
                    events.append(decode(m.ExecutionEvent, json.loads(line)))
            obs = decode(m.PlanningObservation, row["observation"])
            g = raw["genes"]
            require(
                set(raw) == {"anchor_sha256", "end_h", "genes", "steps", "scope"},
                "CANDIDATE_FIELDS",
            )
            require(
                set(g)
                in (
                    {"modes", "crews", "order", "slots", "rests"},
                    {"modes", "crews", "order", "slots", "rests", "initial_action_only"},
                ),
                "GENE_FIELDS",
            )
            for field in ("modes", "crews", "order", "slots"):
                for pair in g[field]:
                    require(len(pair) == 2 and type(pair[0]) is str, "GENE_PAIR")
                    require(
                        type(pair[1]) is str
                        if field in ("modes", "crews")
                        else type(pair[1]) is int
                        if field == "order"
                        else type(pair[1]) in (int, float) and math.isfinite(pair[1]),
                        "GENE_VALUE",
                    )
            require(all(type(x) is str for x in g["rests"]), "REST_VALUES")
            genes = Genes(
                *(tuple(tuple(x) for x in g[k]) for k in ("modes", "crews", "order", "slots")),
                tuple(g["rests"]),
                g.get("initial_action_only", False),
            )
            candidate = Schedule(
                raw["anchor_sha256"],
                raw["end_h"],
                genes,
                tuple(Step(decode(m.Plan, x["plan"]), x["advance_to_h"]) for x in raw["steps"]),
                raw["scope"],
            )
            prefix = m.ExecutionSnapshot(
                config.schema_version,
                config.id,
                obs.config_sha256,
                obs.run_id,
                obs.epoch,
                decode(m.State, row["prefix_state"]),
                tuple(events),
            )
            problem = SimulationJointProblem(
                config,
                obs,
                prefix,
                decisions=row["decisions"],
                end_h=candidate.end_h,
                fixed_mode=row["fixed_mode"],
                rejected=tuple(row["rejected"]),
                committed=tuple(
                    (decode(m.DispatchCommand, x["command"]), x["reason"])
                    for x in row.get("committed", [])
                ),
            )
            result = as_data(problem.verify(candidate))
        except (ValueError, TypeError, KeyError, IndexError) as exc:
            result = dict(valid=False, score=None, reasons=[str(exc)])
        key = fingerprint(raw)
        proofs.append(
            dict(
                candidate_sha256=key,
                report=result,
                journal_bound=any(
                    x.get("cache_sha256") == key or x.get("verified_candidate_sha256") == key
                    for x in journal
                ),
            )
        )
    starts = sum(
        r.get("selected_source") == "VERIFIED_CACHE" and r.get("receipt_kind") == "STARTED"
        for r in journal
    )
    return dict(
        status="PASS"
        if proofs and all(p["report"]["valid"] and p["journal_bound"] for p in proofs)
        else "FAILED"
        if proofs
        else "EMPTY",
        candidates=proofs,
        cached_started=starts,
        scope="OFFLINE_FULL_REPLAY_NOT_ONLINE_BUDGET_MEASUREMENT",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = replay(args.folder)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))
    return result["status"] == "FAILED"


if __name__ == "__main__":
    raise SystemExit(main())
