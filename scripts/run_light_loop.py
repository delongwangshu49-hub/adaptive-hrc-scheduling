"""S12 synthetic environment and reproducible feedback cases; raw logs stay local."""

import argparse
import importlib.util
import json
from dataclasses import asdict, replace
from functools import lru_cache
from pathlib import Path

from adaptive_hrc_scheduling.contracts.building import digest, evidence_pass
from adaptive_hrc_scheduling.contracts.codec import as_data
from adaptive_hrc_scheduling.control.light_loop import Options, run_loop
from adaptive_hrc_scheduling.domain import building as b

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "s12_fixture", ROOT / "scripts/build_building_contracts.py"
)
generator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generator)


class SyntheticFeedback:
    """Trusted test plant, never supplied to choose. Reacts to actual completion.

    Quality and process outcomes are explicit synthetic assumptions. Delayed
    feedback is delivered at the first driver wake at/after its eligibility time.
    No scheduled quality fact exists before its actual inspection completes.
    """

    def __init__(
        self, *, quality_delay_h=0, fail_quality=None, cancel_code=None, receive_delay_h=None
    ):
        self.quality_delay_h = quality_delay_h
        self.fail_quality = fail_quality
        self.cancel_code = cancel_code
        self.receive_delay_h = receive_delay_h
        self.first_seen = {}

    def __call__(self, world):
        latest = {a.activity_id: a for a in sorted(world.snapshot.attempts, key=lambda a: a.number)}
        for aid, att in sorted(latest.items()):
            a = world.activities[aid]
            p = next(p for p in world.snapshot.products if p.product_id == a.product_id)
            if p.cancelled:
                continue
            if a.code == self.cancel_code and att.state in ("COMPLETED", "WAITING_RELEASE"):
                self.emit(world, "CANCEL", a.product_id)
                continue
            if (
                a.quality_evidence
                and att.state == "COMPLETED"
                and not any(
                    q.activity_id == aid and q.attempt == att.number for q in world.snapshot.quality
                )
                and evidence_pass(world.config, (a.quality_evidence,))
            ):
                key = (aid, att.number)
                self.first_seen.setdefault(key, world.time)
                if world.time >= self.first_seen[key] + self.quality_delay_h:
                    self.emit(
                        world,
                        "QUALITY_RESULT",
                        aid,
                        "FAIL" if a.code == self.fail_quality else "PASS",
                        att.number,
                    )
            if (
                att.state == "WAITING_RELEASE"
                and world.time >= att.wait_until_h
                and aid not in world.snapshot.released_processes
                and evidence_pass(world.config, (a.release_evidence, "G4"))
            ):
                self.emit(world, "PROCESS_RELEASE", aid)
        if self.receive_delay_h is not None:
            for p in world.snapshot.products:
                if p.state == "READY" and world.time >= p.ready_h + self.receive_delay_h:
                    self.emit(world, "RECEIVED", p.product_id)

    @staticmethod
    def emit(world, kind, entity, value=None, attempt=None):
        receipt = world.apply_event(
            b.WorldEvent(
                f"S12-SYN-{len(world.snapshot.events) + 1}",
                world.time,
                kind,
                entity,
                value,
                attempt,
            )
        )
        if not receipt.accepted:
            raise RuntimeError(receipt.reason)


def case_input(case):
    c = generator.build_configuration(
        case.get("variant", "SR-W1"), products=case.get("products", 1)
    )
    if case.get("synthetic", True):
        c = generator.synthetic_fixture(c)
    if "future_release_h" in case:
        c = replace(
            c,
            products=tuple(
                replace(p, release_h=case["future_release_h"], due_h=400)
                if p.id == "PRODUCT-2"
                else p
                for p in c.products
            ),
        )
    if case.get("missing_material"):
        c = replace(
            c,
            materials=tuple(
                replace(m, arrived=False, identified=False, released=False)
                if m.id == case["missing_material"]
                else m
                for m in c.materials
            ),
        )
    events = tuple(
        b.WorldEvent(f"CASE-{i}", x[0], x[1], x[2], None, None)
        for i, x in enumerate(case.get("events", []))
    )
    scenario = b.HiddenScenario("C04-1.0", c.id, 17, events)
    source = SyntheticFeedback(**case.get("feedback", {})) if case.get("synthetic", True) else None
    return c, scenario, Options(**case.get("options", {})), source


def reproduce(output):
    cases = json.loads((ROOT / "examples/light_loop/cases.json").read_text(encoding="utf-8"))
    rows = []
    config_digest = lru_cache(maxsize=32)(digest)
    for case in cases:
        c, scenario, opts, source = case_input(case)
        r = run_loop(c, scenario, opts, feedback_source=source)
        dest = output / case["id"]
        dest.mkdir(parents=True, exist_ok=True)
        data = {
            "decision_evidence_version": "S12-1.1",
            "status": r.status,
            "reason": r.reason,
            "trace": asdict(r.trace),
            "report": asdict(r.report),
            "decision_findings": r.decision_findings,
            "observed_configurations": {},
            "turns": [],
        }
        for turn in r.turns:
            key = config_digest(turn.feedback.configuration)
            if key not in data["observed_configurations"]:
                data["observed_configurations"][key] = asdict(turn.feedback.configuration)
            state = {
                f: as_data(getattr(turn.feedback.state, f))
                for f in (
                    "products",
                    "components",
                    "materials",
                    "attempts",
                    "running",
                    "residencies",
                    "locks",
                    "quality",
                    "failed_resources",
                    "released_processes",
                    "services",
                )
            }
            data["turns"].append(
                {
                    "configuration_sha256": key,
                    "observation": asdict(turn.feedback.observation),
                    "state": state,
                    "decision": asdict(turn.decision),
                    "accepted": turn.accepted,
                    "receipt": turn.receipt,
                    "actual_event_ids": turn.actual_event_ids,
                    "before_event_count": turn.before_event_count,
                    "after_event_count": turn.after_event_count,
                    "after_revision": turn.after_revision,
                    "after_h": turn.after_h,
                }
            )
        (dest / "actual-and-decisions.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (dest / "configuration.json").write_text(
            json.dumps(asdict(c), indent=2) + "\n", encoding="utf-8"
        )
        row = {
            "id": case["id"],
            "status": r.status,
            "reason": r.reason,
            "checker_status": r.report.status,
            "report_version": r.report.report_version,
            "decision_findings": list(r.decision_findings),
            "turns": len(r.turns),
            "dispatches": len(r.trace.consumed_commands),
            "end_h": r.trace.time_h,
            "products": [
                {"id": p.product_id, "state": p.state, "ready_h": p.ready_h}
                for p in r.trace.products
            ],
            "feedback_kinds": sorted(
                {json.loads(e.reason)["kind"] for e in r.trace.events if e.kind == "EXTERNAL"}
            ),
        }
        rows.append(row)
        if r.status != case["expected_status"] or r.report.status != "PASS" or r.decision_findings:
            raise RuntimeError(json.dumps(row) + str(r.report.findings[:5]))
    return (
        json.dumps(
            {
                "version": "S12-1.0",
                "scope": "SYNTHETIC_LIGHT_FEEDBACK_LOOP",
                "industrial_qualification": "NOT_ESTABLISHED",
                "default_hr": "DISABLED",
                "cases": rows,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    text = reproduce(args.output)
    (args.output / "summary.json").write_text(text, encoding="utf-8")
    if args.check and text != (ROOT / "examples/light_loop/summary.json").read_text(
        encoding="utf-8"
    ):
        raise SystemExit("Public S12 summary differs")
    print("S12 cases reproduced; actual trajectories independently checked.")


if __name__ == "__main__":
    main()
