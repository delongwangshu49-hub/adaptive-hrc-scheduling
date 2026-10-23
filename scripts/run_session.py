"""P04 shared CPU CLI/research entry, with explicit RunSpec and frozen configuration."""

import argparse
import gzip
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_hrc_scheduling.contracts.codec import as_data  # noqa: E402
from adaptive_hrc_scheduling.contracts.production import decode  # noqa: E402
from adaptive_hrc_scheduling.contracts.session import loads, validate_bundle  # noqa: E402
from adaptive_hrc_scheduling.control.production_decisions import record  # noqa: E402
from adaptive_hrc_scheduling.control.production_loop import run  # noqa: E402
from adaptive_hrc_scheduling.control.session import Session, save_atomic  # noqa: E402
from adaptive_hrc_scheduling.control.session_budget import load_profile  # noqa: E402
from adaptive_hrc_scheduling.domain.production import Configuration  # noqa: E402
from adaptive_hrc_scheduling.production_backend import ProductionBackend  # noqa: E402


def execute(config, bundle, output, *, source="CLI", max_turns=20000, execution_hook=None):
    bundle = validate_bundle(bundle)
    spec = bundle["spec"]
    session = Session(
        spec,
        ProductionBackend(config, run_id=spec["run_id"], epoch=spec["epoch"]),
        load_profile(bundle["profile"]),
        output,
        source=source,
        fixed_requests=bundle["fixed_requests"],
        replay_source=bundle.get("replay_source"),
    )
    for request in bundle["fixed_requests"] + bundle.get("replay_source", {}).get("requests", []):
        if not (session.lifecycle and session.replay_source):
            session.submit(request)
    result = run(
        session.backend,
        session.scenario(),
        joint_policy=session.policy,
        execution_hook=execution_hook,
        session=session,
        max_turns=max_turns,
        orderly_stop=lambda world: session.stopped,
    )
    save_atomic(session.output / "configuration.json", as_data(config))
    save_atomic(session.output / "report.json", result.manifest)
    save_atomic(session.output / "online-journal.json", session.policy.journal)
    save_atomic(
        session.output / "audits.json",
        dict(execution=as_data(result.audit), decisions=as_data(result.decision_audit)),
    )
    for name, rows in (
        ("events", (as_data(e) for e in result.snapshot.events)),
        ("decisions", (record(d) for d in result.decisions)),
    ):
        with gzip.open(session.output / (name + ".jsonl.gz"), "wt", encoding="utf-8") as stream:
            for row in rows:
                stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    return result, session


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-turns", type=int, default=20000)
    args = parser.parse_args()
    config = decode(Configuration, loads(args.configuration.read_text(encoding="utf-8")))
    bundle = loads(args.bundle.read_text(encoding="utf-8"))
    result, session = execute(config, bundle, args.output, max_turns=args.max_turns)
    print(
        json.dumps(
            dict(
                binding=session.binding,
                termination=result.manifest["termination"],
                execution=result.audit.status,
                decisions=result.decision_audit.status,
            )
        )
    )
    return 0 if result.audit.status == result.decision_audit.status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
