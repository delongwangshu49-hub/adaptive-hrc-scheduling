"""Correct periodic Canvas age using only confirmations preceding each log tick.

This is a measurement correction, not a performance acceptance or a new run.
The raw log and old analyzer/results remain untouched. Output must be new.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path

QUANTIZATION_NS = 15_625_000


def statistics(samples):
    if not samples:
        return dict(n=0, p95_s=None, max_s=None)
    return dict(
        n=len(samples),
        p95_s=[sorted(x[k] for x in samples)[math.ceil(0.95 * len(samples)) - 1] for k in (0, 1)],
        max_s=[max(x[k] for x in samples) for k in (0, 1)],
    )


def analyze(rows):
    clocks = [x for x in rows if x["event"] == "clock_worker"]
    canvases = [
        (i, x)
        for i, x in enumerate(rows)
        if x["event"] == "js_observation"
        and x["observation"]["event"] == "canvas_complete"
        and x["observation"].get("envelope")
    ]
    last = None
    samples, ties, old = [], [], []
    skipped = dict(no_previous_canvas=0, no_nearby_clock=0, reversed_timestamp=0)
    for i, tick in enumerate(rows):
        if (
            tick["event"] == "js_observation"
            and tick["observation"]["event"] == "canvas_complete"
            and tick["observation"].get("envelope")
        ):
            last = (i, tick)
        if tick["event"] != "resources":
            continue
        if last is None:
            skipped["no_previous_canvas"] += 1
            continue
        if last[1]["t_ns"] > tick["t_ns"]:
            skipped["reversed_timestamp"] += 1
            continue
        clock = (
            min(clocks, key=lambda x: abs((x["q_send_ns"] + x["q_recv_ns"]) / 2 - tick["t_ns"]))
            if clocks
            else None
        )
        if (
            clock is None
            or abs((clock["q_send_ns"] + clock["q_recv_ns"]) / 2 - tick["t_ns"]) > 30e9
        ):
            skipped["no_nearby_clock"] += 1
            continue

        def age(canvas):
            source = canvas["observation"]["envelope"]["sampled_monotonic_s"] * 1e9
            return [
                (tick["t_ns"] - source + clock["offset_worker_minus_qt_lo_ns"] - QUANTIZATION_NS)
                / 1e9,
                (tick["t_ns"] - source + clock["offset_worker_minus_qt_hi_ns"] + QUANTIZATION_NS)
                / 1e9,
            ]

        bounds = age(last[1])
        samples.append(
            dict(
                resource_line=i + 1,
                canvas_line=last[0] + 1,
                sequence=last[1]["observation"]["sequence"],
                qt_sample_ns=tick["t_ns"],
                lo_s=bounds[0],
                hi_s=bounds[1],
            )
        )
        previous_rule = [c for c in canvases if c[1]["t_ns"] <= tick["t_ns"]]
        if previous_rule:
            selected = previous_rule[-1]
            old_age = age(selected[1])
            old.append(old_age)
            if selected[0] > i:
                ties.append(
                    dict(
                        resource_line=i + 1,
                        selected_future_line=selected[0] + 1,
                        age_understatement_s=bounds[0] - old_age[0],
                    )
                )
    return dict(
        method="LAST_CANVAS_CONFIRMATION_PRECEDING_RESOURCE_LOG_RECORD",
        quantization_expansion_ns=QUANTIZATION_NS,
        nearest_clock_limit_s=30,
        corrected=statistics([[x["lo_s"], x["hi_s"]] for x in samples]),
        previous_timestamp_rule=statistics(old),
        future_confirmation_ties=len(ties),
        source_changed_ties=sum(abs(x["age_understatement_s"]) > 1e-8 for x in ties),
        max_understatement_s=max((x["age_understatement_s"] for x in ties), default=0),
        skipped=skipped,
        samples=samples,
        ties=ties,
        qualification="NO_NEW_PERFORMANCE_PASS",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qt-log", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    raw = args.qt_log.read_bytes()
    result = analyze([json.loads(line) for line in raw.splitlines() if line.strip()])
    result["input"] = dict(
        path=str(args.qt_log.resolve()), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()
    )
    with args.output.open("x", encoding="utf8") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("samples", "ties")}))


if __name__ == "__main__":
    main()
