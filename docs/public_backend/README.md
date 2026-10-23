# P04 dynamic backend and continuous sessions

This candidate covers P04.1–P04.4 on the simulation research model. It adds shared RunSpec/request consumption, new orders and personnel, versioned catalogs, bounded continuous lifetime and a read-only timeline consumer. The new dual-view GUI and the five-scenario final acceptance remain subsequent work.

## Run a bounded CPU witness

Use Python 3.12 and the repository environment; PowerShell 7 on Windows. Each output directory must be new.

```powershell
$env:PYTHONPATH = "src;scripts"
uv run --locked python scripts/run_lifecycle_witness.py artifacts/lifetime-drain --profile docs/public_backend/budget_profile.json --case drain
uv run --locked python scripts/verify_lifecycle_session.py artifacts/lifetime-drain
uv run --locked python scripts/run_lifecycle_witness.py artifacts/lifetime-stop --profile docs/public_backend/budget_profile.json --case stop
```

The drain witness cancels one untouched initial order, waits with metered time, accepts an asynchronously published future new person, closes intake, applies the accepted request and completes. The stop witness starts and completes a real command under an asynchronous stop. The `active-drain` case closes while a command is STARTED and finishes that command before completing the cancelled-order drain. These are local lifetime witnesses, not four finished products or the final continuous production scenario. Kit witnesses use the same driver with the actual USD adapter and receiver; CPU output does not establish Kit behavior.

For a supplied RunSpec/configuration, use `scripts/run_session.py --configuration FILE --bundle FILE --output NEW_DIRECTORY`. Create a complete-lifetime spec with `control.session_lifecycle.enable(spec, **clock)`; its identity is `P04.4-SESSION-r1`. The older `P03.2-CONTRACT-r3` launch identity remains a checkpoint compatibility path. Fixed protocol rejects undeclared input and retains fixed-set completion. For new replay sessions, the bound source contains `requests` and a `received_sim_h` map keyed by request ID; the writer releases those requests at recorded reception boundaries.

## Runtime and persistence

Only the production worker mutates state. Producers atomically publish request files through `submit_file`; filename ordering is not causal ordering. A producer waits for acceptance before dependent sequence numbers. Immediate time resolves at actual receipt. Future requests are rechecked at application. CLOSE_INPUT records the last accepted sequence at its application boundary and prevents later new orders/arrivals; accepted future work and recovery controls remain eligible. STOP does not resume or imply completion.

The clock advances by the minimum of declared heartbeat, idle step, session end, request, completion, calendar, qualification and protection boundaries. `simulation_rate` is simulation hours per wall second. It uses a high resolution monotonic counter; no wall-time catch-up jump is made after planning or Kit overhead. Indivisible planner/Kit calls are cooperative, not hard real-time preemptible; the declared poll interval bounds waits, not arbitrary native call latency. Existing total search/decision accounting remains unchanged. WAIT/REST/OFF_SHIFT and presence labour use the original integrator/rates; a protection boundary that cannot safely advance ends in explicit DRAIN_BLOCKED rather than clipping fatigue.

Completion requires no accepted pending requests, open products, residual stock, running work, holds, reservations or commitments, plus execution and causal audits and durable final state. Cancelled orders have separate legal terminal results and do not count as received products. `final-commit.json` binds saved state and projection files. Actual OS exit is a separate supervisor receipt. Terminal query rejections do not rewrite the committed snapshot. Failures preserve the last state and unknown audit/application facts.

## Timeline consumer

[Projection specification](timeline.md), [schema](timeline_schema.json) and [consumer bindings](bindings.json) describe the stream. Read `timeline.jsonl` in sequence with `TimelineConsumer(run_id, epoch, run_spec_sha256)`. The v2 stream provides frozen configuration and delivered source evidence. The consumer reconstructs catalog attributes, effective priorities, execution and all factual row semantics before trusting the view; legacy v1 streams require independent saved-run review. A gap or corruption retains the last verified state as STALE_CORRUPT. Filters and exports are read-only. Local residence age is available; cross-process source age remains AGE_UNKNOWN without a clock/round-trip proof. Scene and timeline envelopes compare as SAME_OBSERVATION or ASYNCHRONOUS; neither label asserts atomic physical synchronization.

## Evidence and limits

The revised local regression set contains 337 different tests (144 session/order/workforce, 20 lifetime, 24 repair, 115 online/simulation, 34 desktop). Original 15 and review 11 re-signed saved corruptions are rejected. Revision 2 has new local CPU drain/stop/active-drain and shared CPU desktop-worker replay witnesses, with separate actual process exit receipts. The original six CPU/Kit archives pass the stricter independent reinterpretation; Kit remains original-source evidence, not a new Kit execution. [evidence.json](evidence.json) distinguishes source identities. Prior P04.1–P04.3 candidate/adoption/USD evidence retains its original scope.

Tested lifetime capacity inherits four total products, three WIP slots and eighteen personnel limits; the new local lifetime witness is smaller. New UI layout, owner interaction acceptance, five-scenario experiments, long-run load/latency validation, release CI and industrial qualification are not established here. Historical S19B accepted limitations and the simulation-only domain remain in effect.
