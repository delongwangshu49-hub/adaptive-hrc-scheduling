"""Bounded bilingual Qt replay including cold asynchronous binding; no production."""

import argparse
import hashlib
import json
import os
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "desktop/s19b/src"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    from PySide6.QtCore import QEvent, QTimer
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication
    from s19b_desktop.app import Workbench, configure_application
    from s19b_desktop.model import atomic_json, read_json
    from s19b_desktop.review import history_reason, preview_evidence, reason_fact

    source = args.live.parent
    journal = source / "online-journal.json"
    original_hash = hashlib.sha256(journal.read_bytes()).hexdigest()
    rows = json.loads(journal.read_text(encoding="utf-8"))
    facts = [reason_fact([r]) for r in rows]
    facts.sort(key=lambda r: len(json.dumps(r, ensure_ascii=False)), reverse=True)
    facts = facts[:40]
    assert history_reason(source) == reason_fact(rows)
    preview = preview_evidence(source, "online-journal.json")
    assert len(preview) < 30_000
    del rows
    live = read_json(args.live)
    results = dict(
        scope="SYNTHETIC_LIVE_REPLAY_OFFSCREEN_QT_NO_PRODUCTION_NO_GPU_PAINT",
        source=str(source),
        journal_sha256=original_hash,
        journal_bytes=journal.stat().st_size,
        legacy_reason_and_bounded_preview="PASS",
        warmup_excluded=0,
        samples_each_language=200,
        max_callback_s=0.25,
        p95_callback_s=0.05,
        max_heartbeat_interval_s=0.25,
        blocks=[],
    )
    atomic_json(args.output / "predeclared.json", results)
    app = QApplication([])
    configure_application(app)
    for locale in ("zh-CN", "en"):
        fixture = args.output / locale
        fixture.mkdir()
        for name in ("configuration.json", "sources.json", "entity-catalog.json"):
            shutil.copyfile(source / name, fixture / name)
        settings = fixture / "settings.json"
        atomic_json(settings, {"locale": locale, "isaac_root": ""})
        window = Workbench(runs=fixture, settings=settings)
        window.timer.stop()
        window.show()
        window.run_directory = fixture
        window.run_id, window.request_id = live["run_id"], live["request_id"]
        window.backend = live["backend"]
        window.submitted_s = time.monotonic()
        window.busy = lambda: True
        window.arrange_scene = lambda: None
        beats = [time.perf_counter()]
        heartbeat = QTimer()
        heartbeat.setInterval(10)
        heartbeat.timeout.connect(lambda: beats.append(time.perf_counter()))
        heartbeat.start()
        samples = []
        began = time.perf_counter()
        bound_after = None
        for index in range(200):
            atomic_json(
                fixture / "live.json",
                dict(
                    live,
                    sequence=index + 1,
                    phase="RUNNING",
                    published_monotonic_s=time.monotonic(),
                    published_wall_s=time.time(),
                    reason=facts[index % len(facts)],
                ),
            )
            started = time.perf_counter()
            window.poll()
            app.processEvents()
            elapsed = time.perf_counter() - started
            samples.append(dict(seconds=elapsed, current=window.record_current))
            if bound_after is None and window.bound_version:
                bound_after = time.perf_counter() - began
            QTest.qWait(max(0, int(250 - elapsed * 1000)))
        heartbeat.stop()
        intervals = [b - a for a, b in zip(beats, beats[1:])]
        ordered = sorted(s["seconds"] for s in samples)
        block = dict(
            locale=locale,
            samples=samples,
            first_callback_s=samples[0]["seconds"],
            binding_wait_s=bound_after,
            unknown_samples=sum(not s["current"] for s in samples),
            max_s=ordered[-1],
            p95_s=ordered[189],
            heartbeat_intervals_s=intervals,
            max_heartbeat_interval_s=max(intervals),
        )
        block["pass"] = (
            bound_after is not None
            and ordered[-1] <= 0.25
            and ordered[189] <= 0.05
            and max(intervals) <= 0.25
            and window.record_current
        )
        results["blocks"].append(block)
        atomic_json(args.output / "replay.json", results)
        print(locale, block["pass"], "max", block["max_s"], flush=True)
        window.busy = lambda: False
        window.close()
        window.deleteLater()
        app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        app.processEvents()
    assert hashlib.sha256(journal.read_bytes()).hexdigest() == original_hash
    results["status"] = "PASS" if all(b["pass"] for b in results["blocks"]) else "FAILED"
    atomic_json(args.output / "replay.json", results)
    return 0 if results["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
