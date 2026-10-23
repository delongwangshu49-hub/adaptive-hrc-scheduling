"""Single-field P043 saved corruption probes; originals remain immutable."""

import copy
import json
import shutil
import tempfile
from pathlib import Path

from verify_workforce_session import verify

from adaptive_hrc_scheduling.contracts.session import digest


def run(directory):
    root = Path(directory)
    original = json.loads((root / "session-state.json").read_text())
    rows = []

    def no_applied(data):
        data["receipts"] = [
            r
            for r in data["receipts"]
            if not (r["request_id"] == "P043-1" and r["status"] == "APPLIED")
        ]
        previous = "0" * 64
        for i, r in enumerate(data["receipts"], 1):
            r.update(
                receipt_sequence=i, receipt_id="RECEIPT-" + str(i), previous_receipt_hash=previous
            )
            previous = digest(r)

    def scene(data):
        next(r for r in data["scene_bindings"] if r["domain_id"] == "W3")["ready"] = False

    cases = [
        ("missing_APPLIED_rechained", no_applied),
        ("scene_not_ready", scene),
        (
            "available_hours_forged",
            lambda d: d["workforce_statistics"]["people"]["W3"].update(available_h=999),
        ),
        (
            "labour_cost_forged",
            lambda d: d["workforce_statistics"]["people"]["W3"].update(labour_cost=0),
        ),
        ("exposure_reset", lambda d: d["workforce_statistics"]["people"]["W3"].update(exposure=0)),
        (
            "false_prearrival_zero_history",
            lambda d: d["workforce_statistics"]["people"]["W3"].update(before_arrival="ZERO"),
        ),
        ("old_person_deleted", lambda d: d["workforce_statistics"]["people"].pop("W1")),
        (
            "false_person_business_status",
            lambda d: d["workforce_results"][0].update(status="DEPARTED"),
        ),
        ("missing_safe_departure_completion", lambda d: d["generations"].pop()),
        (
            "wrong_person_parameter",
            lambda d: d["generations"][0]["payload"].update(parameter_template_sha256="0" * 64),
        ),
        (
            "return_attempts_initial_F_override",
            lambda d: d["requests"]["P043-4"]["payload"].update(initial_f=0),
        ),
        (
            "scene_identity_reused",
            lambda d: next(r for r in d["scene_bindings"] if r["domain_id"] == "W3").update(
                scene_entity_id="W1"
            ),
        ),
        (
            "missing_presence_intervals",
            lambda d: d["workforce_statistics"]["people"]["W3"].update(presence_intervals=[]),
        ),
    ]
    with tempfile.TemporaryDirectory(prefix="p043-negative-") as temp:
        dest = Path(temp)
        for name in ("run-spec.json", "profile.json", "launch-binding.json", "configuration.json"):
            shutil.copy2(root / name, dest / name)
        for name, modify in cases:
            bad = copy.deepcopy(original)
            modify(bad)
            (dest / "session-state.json").write_text(json.dumps(bad))
            try:
                verify(dest, evidence_directory=root)
            except (ValueError, KeyError, TypeError) as exc:
                rows.append(
                    dict(
                        case=name, status="REJECTED", reason=str(exc), exception=type(exc).__name__
                    )
                )
            else:
                raise AssertionError("CORRUPTION_ACCEPTED:" + name)
    return dict(status="PASS", identity="P043-SAVED-CORRUPTIONS-r1", count=len(rows), cases=rows)


if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    result = run(args.directory)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
