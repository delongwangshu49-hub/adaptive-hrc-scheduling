"""Four separate, fresh, headless Kit mechanism witnesses; no full-chain claim."""

import gzip
import hashlib
import json
import os
import sys
from pathlib import Path
from time import perf_counter

R = Path(__file__).resolve().parents[2]
OUTPUT = Path(__file__).parent
sys.path[:0] = [str(R), str(R / "src"), str(R / "scripts"), str(R / "desktop/s19b/src")]
protocol = json.loads((OUTPUT / "kit-protocol-r5.json").read_bytes())
if not protocol.get("execution_enabled", False):
    raise RuntimeError("R5_AUXILIARY_REPAIR_ONLY_NO_NEW_RUN_BINDING")
from kit_failure_context_r1 import KitFailureContext

for name, expected in protocol["sources"].items():
    if hashlib.sha256((R / name).read_bytes()).hexdigest() != expected["sha256"]:
        raise RuntimeError("KIT_FROZEN_SOURCE_CHANGED:" + name)
import ctypes

ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)
kit_began = perf_counter()
app = None
success = False
current_unit = None
completed_rows = []
failure = None
preservation = []
failure_context = None
try:
    from isaacsim import SimulationApp

    os.environ["OPTIX_CACHE_PATH"] = str(R / ".local/s19b-render-cache/optix")
    app = SimulationApp(
        dict(
            headless=True,
            width=640,
            height=480,
            fast_shutdown=True,
            multi_gpu=False,
            enable_crashreporter=False,
            renderer="RayTracedLighting",
            extra_args=[
                "--ext-folder",
                str(Path(os.environ["ISAAC_PATH"]) / "extscache"),
                "--ext-folder",
                str(Path(os.environ["ISAAC_PATH"]) / "extsDeprecated"),
                "--ext-folder",
                str(Path(os.environ["ISAAC_PATH"]) / "extsUser"),
                "--/app/extensions/registryEnabled=false",
            ],
        ),
        experience=str(R / "sim/isaac/s19b_viewport.kit"),
    )
    import omni.usd
    from s19b_desktop.review import entity_catalog

    from adaptive_hrc_scheduling.backends.production_isaac_adapter import IsaacAdapter
    from adaptive_hrc_scheduling.contracts.codec import as_data
    from adaptive_hrc_scheduling.contracts.production import decode
    from adaptive_hrc_scheduling.contracts.production import digest as configuration_digest
    from adaptive_hrc_scheduling.control.production_decisions import record
    from adaptive_hrc_scheduling.control.production_loop import run
    from adaptive_hrc_scheduling.control.session import Session, save_atomic
    from adaptive_hrc_scheduling.control.session_budget import load_profile
    from adaptive_hrc_scheduling.domain.production import Configuration
    from sim.isaac.scene.model import load_config
    from sim.isaac.scene.production_port import USDProductionPort
    from sim.isaac.scene.production_receiver import SyntheticReceiver
    from sim.isaac.scene.target_scene import TargetScene

    for row in protocol["rows"]:
        unit = row["unit_id"]
        current_unit = unit
        backend = scene = c = bundle = directory = failure_context = None
        began = perf_counter()
        session = None
        directory = OUTPUT / "runs" / unit
        bundle = json.loads((OUTPUT / row["bundle"]).read_bytes())
        c = decode(Configuration, json.loads((OUTPUT / row["configuration"]).read_bytes()))
        failure_context = KitFailureContext(
            unit,
            bundle["spec"]["run_id"],
            bundle["spec"]["epoch"],
            directory,
            c,
            configuration_digest,
        )
        omni.usd.get_context().new_stage()
        scene = TargetScene(
            omni.usd.get_context().get_stage(),
            load_config(R / "examples/building_contracts/configuration.json"),
        )
        failure_context.scene = scene
        backend = IsaacAdapter(c, USDProductionPort(scene), run_id=bundle["spec"]["run_id"])
        failure_context.backend = backend
        receiver = SyntheticReceiver(backend.port)
        original_step = backend.port.step

        def with_receiver(command_id, now_h):
            receiver.step(backend.port.running[command_id], now_h)
            return original_step(command_id, now_h)

        backend.port.step = with_receiver
        if unit.startswith(("F-", "C-")):
            from dataclasses import fields

            from adaptive_hrc_scheduling.contracts.session_stream import FrozenEventArray
            from adaptive_hrc_scheduling.control.production_loop import Scenario
            from adaptive_hrc_scheduling.control.session_budget import BudgetAccount
            from adaptive_hrc_scheduling.dynamic_orders import CatalogHistory
            from adaptive_hrc_scheduling.research_initial import ResearchOnlinePolicy

            directory.mkdir(exist_ok=False)
            profile = load_profile(bundle["profile"])
            policy = ResearchOnlinePolicy(
                c, profile.limits, end_h=720, budget_account=BudgetAccount(profile)
            )
            policy.catalog_context = CatalogHistory(c)
            policy.method = "ADAPTIVE"
            began = perf_counter()
            last_f = began - 30

            def f_hook(adapter, phase):
                global last_f
                app.update()
                now = perf_counter()
                if (
                    now - began > row["wall_budget_s"]
                    or now - kit_began > protocol["cumulative_kit_wall_budget_s"]
                ):
                    raise TimeoutError("P053_F_KIT_FROZEN_LIMIT")
                if now - last_f >= 30:
                    with (OUTPUT / "kit-progress.jsonl").open("a", encoding="utf-8") as stream:
                        stream.write(
                            json.dumps(
                                dict(
                                    unit=unit,
                                    sim_h=adapter.world.s.time_h,
                                    events=len(adapter.world.events),
                                    elapsed_s=now - began,
                                    phase=phase,
                                )
                            )
                            + "\n"
                        )
                    last_f = now

            def resumed_done(world):
                if unit.startswith("C-"):
                    return "PRODUCT-2.KIT.U1" in world.s.completed
                return any(
                    e.kind == "COMPLETED" and e.command and e.command.resume_of
                    for e in world.events
                )

            scenario = (
                Scenario(id="C", until_h=720, cancel_product="PRODUCT-1", cancel_stage="STOCK")
                if unit.startswith("C-")
                else Scenario(id="F", until_h=720, actual_device_failure=True)
            )
            result = run(
                backend,
                scenario,
                joint_policy=policy,
                stop_condition=resumed_done,
                execution_hook=f_hook,
                max_turns=6000,
            )
            cache = FrozenEventArray(directory)
            cache.append(result.snapshot.events)
            snapshot = {f.name: getattr(result.snapshot, f.name) for f in fields(result.snapshot)}
            snapshot["events"] = cache
            save_atomic(directory / "snapshot.json", snapshot)
            save_atomic(directory / "configuration.json", c)
            save_atomic(directory / "state.json", result.snapshot.state)
            save_atomic(directory / "report.json", result.manifest)
            save_atomic(
                directory / "audits.json",
                dict(execution=result.audit, decisions=result.decision_audit),
            )
            save_atomic(directory / "online-journal.json", policy.journal)
            with gzip.open(directory / "decisions.jsonl.gz", "wt", encoding="utf-8") as stream:
                for d in result.decisions:
                    stream.write(json.dumps(record(d)) + "\n")
            scene.stage.GetRootLayer().Export(str(directory / "scene.usda"))
            done = bool(resumed_done(backend.world))
            save_atomic(
                OUTPUT / (unit + "-result.json"),
                dict(
                    unit=unit,
                    manifest=result.manifest,
                    elapsed_s=perf_counter() - began,
                    target_complete=done,
                    source="ACTUAL_HEADLESS_ISAAC_USD",
                    claim="LOCAL_CANCELLATION_CLEANUP_AND_REMAINING_KIT_PREFIX_NOT_FULL_PRODUCTION"
                    if unit.startswith("C-")
                    else "LOCAL_LOADED_DEVICE_FAILURE_REPAIR_RESUME_PREFIX_NOT_FULL_PRODUCTION",
                ),
            )
            print(
                "P053_KIT_RESULT",
                unit,
                done,
                result.audit.status,
                result.decision_audit.status,
                flush=True,
            )
            if not done or result.audit.status != "PASS" or result.decision_audit.status != "PASS":
                raise RuntimeError("P053_F_KIT_NOT_MET")
            completed_rows.append(unit)
            continue
        session = Session(
            bundle["spec"],
            backend,
            load_profile(bundle["profile"]),
            directory,
            source="RESEARCH",
            fixed_requests=bundle["fixed_requests"],
        )
        save_atomic(
            directory / "entity-catalog.json",
            dict(
                run_id=bundle["spec"]["run_id"],
                epoch=0,
                config_sha256=configuration_digest(c),
                scope="ACTUAL_ISAAC_USD_MAPPING",
                entities=entity_catalog(as_data(c), backend.port.mapping),
            ),
        )
        for request in bundle["fixed_requests"]:
            session.submit(request)
        began = perf_counter()
        last = began - 30

        def hook(adapter, phase):
            global last
            app.update()
            now = perf_counter()
            if (
                now - began > row["wall_budget_s"]
                or now - kit_began > protocol["cumulative_kit_wall_budget_s"]
            ):
                raise TimeoutError("P053_KIT_FROZEN_WALL_LIMIT")
            if now - last >= 30:
                with (OUTPUT / "kit-progress.jsonl").open("a", encoding="utf-8") as stream:
                    stream.write(
                        json.dumps(
                            dict(
                                unit=unit,
                                sim_h=adapter.world.s.time_h,
                                events=len(adapter.world.events),
                                elapsed_s=now - began,
                                phase=phase,
                            )
                        )
                        + "\n"
                    )
                last = now

        def complete(world):
            if unit.startswith("H-"):
                return any(
                    a.activity_id == "PRODUCT-1.W-B" and a.state == "COMPLETE"
                    for a in world.s.mode_attempts
                )
            return "PRODUCT-2.KIT.U1" in world.s.completed

        result = run(
            backend,
            session.scenario(),
            session=session,
            joint_policy=session.policy,
            execution_hook=hook,
            stop_condition=complete,
            max_turns=6000,
        )
        save_atomic(directory / "configuration.json", c)
        save_atomic(directory / "report.json", result.manifest)
        save_atomic(
            directory / "audits.json", dict(execution=result.audit, decisions=result.decision_audit)
        )
        save_atomic(directory / "online-journal.json", session.policy.journal)
        with gzip.open(directory / "decisions.jsonl.gz", "wt", encoding="utf-8") as stream:
            for d in result.decisions:
                stream.write(json.dumps(record(d)) + "\n")
        scene.stage.GetRootLayer().Export(str(directory / "scene.usda"))
        done = complete(backend.world)
        summary = dict(
            unit=unit,
            manifest=result.manifest,
            elapsed_s=perf_counter() - began,
            target_complete=done,
            source="ACTUAL_HEADLESS_ISAAC_USD",
            claim="LOCAL_MECHANISM_PREFIX_NOT_FULL_PRODUCTION_OR_GUI",
            initial_F=[p.initial_f for p in c.people],
            actual_final_humans=as_data(backend.world.s.humans),
            catalog_generations=len(session.history.generations),
        )
        save_atomic(OUTPUT / (unit + "-result.json"), summary)
        print(
            "P053_KIT_RESULT",
            unit,
            done,
            result.audit.status,
            result.decision_audit.status,
            flush=True,
        )
        if not done or result.audit.status != "PASS" or result.decision_audit.status != "PASS":
            raise RuntimeError("P053_KIT_MECHANISM_NOT_MET")
        completed_rows.append(unit)
    if perf_counter() - kit_began > protocol["cumulative_kit_wall_budget_s"]:
        raise TimeoutError("KIT_CUMULATIVE_BUDGET_EXCEEDED")
    success = True
except BaseException as exc:
    import traceback

    failure = dict(
        type=type(exc).__name__,
        message=str(exc),
        traceback=traceback.format_exc(),
        unit=current_unit,
    )
    traceback.print_exc()
    # Capture only values bound to this row. Identity rejection makes no filesystem writes.
    try:
        if failure_context is None:
            raise ValueError("CURRENT_ROW_CONTEXT_UNAVAILABLE")
        captured = failure_context.capture()
        from dataclasses import fields

        from adaptive_hrc_scheduling.contracts.session_stream import FrozenEventArray
        from adaptive_hrc_scheduling.control.session import save_atomic

        captured.directory.mkdir(exist_ok=True)
        failure_directory = captured.directory / "failure-preserved"
        failure_directory.mkdir(exist_ok=False)
        cache = FrozenEventArray(failure_directory)
        cache.append(captured.snapshot.events)
        values = {f.name: getattr(captured.snapshot, f.name) for f in fields(captured.snapshot)}
        values["events"] = cache
        save_atomic(failure_directory / "snapshot.json", values)
        save_atomic(failure_directory / "configuration.json", captured.configuration)
        save_atomic(failure_directory / "state.json", captured.snapshot.state)
        captured.scene.stage.GetRootLayer().Export(str(failure_directory / "scene.usda"))
        preservation.append(
            dict(
                unit=captured.unit,
                run_id=captured.run_id,
                epoch=captured.epoch,
                status="SAVED_INCOMPLETE_IDENTITY_BOUND",
                actual_configuration_sha256=captured.actual_configuration_sha256,
                initial_configuration_sha256=captured.initial_configuration_sha256,
                scope="actual incomplete failure snapshot; no audit or completed-prefix claim",
                path=str(failure_directory.relative_to(R)),
            )
        )
    except BaseException as saved_exc:
        preservation.append(
            dict(
                unit=current_unit,
                status="UNKNOWN_NO_IDENTITY_BOUND_COMPLETE_COPY",
                preservation_error=repr(saved_exc),
                scope="no PASS, no substituted previous-row snapshot",
            )
        )

finally:
    elapsed = perf_counter() - kit_began
    within = elapsed <= protocol["cumulative_kit_wall_budget_s"]
    if not within:
        success = False
    cumulative = dict(
        elapsed_s=elapsed,
        budget_s=protocol["cumulative_kit_wall_budget_s"],
        within_budget=within,
        completed_rows=completed_rows,
        current_unit=current_unit,
        failed_unit=None if success else current_unit,
        success=success,
        failure=failure,
        preservation=preservation,
        scope="one actual shared process, four fresh prefixes; timer starts before SimulationApp import and ends before app.close; outer timer includes shutdown",
        cooperative_nonpreemptive=True,
    )
    try:
        (OUTPUT / "kit-cumulative-r5.json").write_text(
            json.dumps(cumulative, indent=2), encoding="utf-8"
        )
    except BaseException:
        import traceback

        traceback.print_exc()
        success = False
    code = 0 if success else 1
    if app is not None:
        app.close(exit_code=code)
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(code)
