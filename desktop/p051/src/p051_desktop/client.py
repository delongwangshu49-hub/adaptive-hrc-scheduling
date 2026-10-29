"""Thin file transport around P04 contracts; no scheduler or state mutation."""

import math
import time
import uuid
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from adaptive_hrc_scheduling.contracts.session import (
    digest,
    loads,
    request_digest,
    validate_request,
)
from adaptive_hrc_scheduling.control.session import submit_file
from adaptive_hrc_scheduling.dynamic_orders import template_registry
from adaptive_hrc_scheduling.timeline import TimelineConsumer
from adaptive_hrc_scheduling.workforce_session import arrival_payload

from .gantt import ScheduleReader, enrich
from .projection import WorkColors, person_results


class Client:
    """Used by one background executor. Only validated packets become UI state."""

    def __init__(self, directory, *, writable=False):
        self.directory = Path(directory).resolve()
        if (
            not (self.directory / "run-spec.json").exists()
            and (self.directory / "session/run-spec.json").exists()
        ):
            self.directory = self.directory / "session"
        self.spec = loads((self.directory / "run-spec.json").read_bytes())
        self.consumer = TimelineConsumer(self.spec["run_id"], self.spec["epoch"], digest(self.spec))
        self.colors = WorkColors(self.spec["run_id"], self.spec["epoch"])
        self.offset = 0
        self.packet = None
        self.receipts = {}
        self.writable = writable and self.spec["mode"] == "INTERACTIVE_PRODUCTION"
        self.client_path = self.directory / "p051-client.json"
        self.journal = dict(producer_id="P051-" + uuid.uuid4().hex, sequence=0, requests={})
        if self.client_path.exists():
            self.journal = loads(self.client_path.read_bytes())
        self.error = None
        self.configuration_key = None
        self.display_configuration = None
        self.poll_metrics = {}
        self.view_cache_key = None
        self.view_cache = None
        self.binding_results = {}
        self.schedules = ScheduleReader()

    def poll(self):
        began = time.perf_counter()
        consumed = 0
        path = self.directory / "timeline.jsonl"
        try:
            self.load_bindings()
            if path.stat().st_size < self.offset:
                raise ValueError("TIMELINE_TRUNCATED")
            with path.open("rb") as stream:
                stream.seek(self.offset)
                # Bound each background slice; incomplete final lines wait for
                # atomic publisher completion and never advance the byte cursor.
                for _ in range(32):
                    line = stream.readline(128_000_001)
                    if not line or not line.endswith(b"\n"):
                        if len(line) > 128_000_000:
                            raise ValueError("TIMELINE_PACKET_TOO_LARGE")
                        break
                    p = loads(line)
                    self.consumer.consume(p)
                    self.offset = stream.tell()
                    self.packet = self.consumer.materialized_packet
                    for r in p["receipts"]:
                        self.receipts[r["request_id"]] = r
                    consumed += 1
                    # Amortize the full display projection over a short backlog
                    # slice. Every packet is still checked and committed in order.
                    if time.perf_counter() - began > 0.5:
                        break
            self.error = None
        except FileNotFoundError:
            self.error = "WAITING_TIMELINE"
            self.consumer.status = "UNKNOWN" if self.consumer.sequence == 0 else "STALE_CORRUPT"
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error = str(exc)
            self.consumer.status = "STALE_CORRUPT"
        try:
            result = self.snapshot()
        except (OSError, ValueError, TypeError, KeyError) as exc:
            self.error = str(exc)
            self.consumer.status = "STALE_CORRUPT"
            result = dict(
                self.view_cache or {}, status="STALE_CORRUPT", error=self.error, writable=False
            )
        if result.get("envelope"):
            age = time.monotonic() - result["envelope"]["sampled_monotonic_s"]
            result["source_age_s"] = max(0, age) if age >= 0 else None
        self.poll_metrics = dict(
            elapsed_s=time.perf_counter() - began,
            packets=consumed,
            byte_cursor=self.offset,
            sequence=self.consumer.sequence,
        )
        result["reader_metrics"] = self.poll_metrics
        return result

    def load_bindings(self):
        for path in (self.directory / "p051-confirmations/results").glob("*.json"):
            result = loads(path.read_bytes())
            key = result["request_id"]
            if key in self.journal["requests"] and key not in self.binding_results:
                if result["status"] == "BOUND":
                    final = validate_request(result["request"])
                    reviewed = self.journal["requests"][key]
                    if request_digest(final) != final["request_digest"] or {
                        k: v
                        for k, v in final.items()
                        if k
                        not in (
                            "expected_state_revision",
                            "expected_catalog_version",
                            "request_digest",
                        )
                    } != {
                        k: v
                        for k, v in reviewed.items()
                        if k
                        not in (
                            "expected_state_revision",
                            "expected_catalog_version",
                            "request_digest",
                        )
                    }:
                        raise ValueError("CONFIRMATION_RESULT_CHANGED")
                    self.journal["requests"][key] = final
                else:
                    self.receipts[key] = dict(
                        request_id=key, status="REJECTED", reason=result["reason"], sim_h=None
                    )
                self.binding_results[key] = result
                self.view_cache_key = None

    def snapshot(self):
        self.schedules.drain()
        key = (self.consumer.sequence, self.journal["sequence"], self.schedules.revision)
        if self.view_cache_key != key or self.view_cache is None:
            self.view_cache = self.project_snapshot()
            self.view_cache_key = key
        view = dict(self.view_cache)
        view["status"] = self.consumer.status
        if self.packet:
            view["envelope"] = deepcopy(self.consumer.envelope)
            age = time.monotonic() - view["envelope"]["sampled_monotonic_s"]
            view["source_age_s"] = max(0, age) if age >= 0 else None
            if age < 0:
                view["status"] = "AGE_UNKNOWN"
            elif age > 5 and view["status"] == "VERIFIED":
                view["status"] = "STALE"
        view["forecast_audit_pending"] = len(self.schedules.pending)
        view.update(error=self.error, writable=self.writable and view["status"] == "VERIFIED")
        return view

    def project_snapshot(self):
        view = self.consumer.view()
        if not self.packet:
            return dict(view, error=self.error, writable=False, receipts=[], business_results=[])
        # Publisher and desktop share the Windows monotonic clock. Archived
        # packets must not look fresh merely because this reader just replayed.
        age = time.monotonic() - view["envelope"]["sampled_monotonic_s"]
        if age < 0:
            view["status"] = "AGE_UNKNOWN"
        elif age > 5 and view["status"] == "VERIFIED":
            view["status"] = "STALE"
        view["source_age_s"] = max(0, age) if age >= 0 else None
        from adaptive_hrc_scheduling.contracts.codec import as_data
        from adaptive_hrc_scheduling.contracts.production import decode
        from adaptive_hrc_scheduling.domain.production import Configuration
        from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory

        key = digest(self.packet["source"]["generations"])
        if self.configuration_key != key:
            initial = decode(Configuration, self.consumer.basis["configuration"])
            self.display_configuration = as_data(
                WorkforceHistory(initial, self.packet["source"]["generations"]).current
            )
            self.configuration_key = key
        config = self.display_configuration
        forecasts = self.schedules.read(self)
        view = enrich(dict(view, rows=view["rows"] + forecasts), config, self.consumer.events)
        view = self.colors.project(view, config)
        from adaptive_hrc_scheduling.dynamic_workforce import registry

        return dict(
            view,
            error=self.error,
            writable=self.writable and view["status"] == "VERIFIED",
            receipts=list(self.receipts.values()),
            submitted=list(self.journal["requests"].values()),
            business_results=deepcopy(self.packet["business_results"])
            + person_results(self.consumer.events),
            people=deepcopy(self.packet["people"]),
            devices=deepcopy(self.packet["devices"]),
            workforce_statistics=deepcopy(self.packet["workforce_statistics"]),
            plan=deepcopy(self.packet["plan"]),
            catalog=deepcopy(self.packet["catalog"]),
            clock=deepcopy(self.spec["clock"]),
            backend=self.spec["backend"],
            full_schedule=deepcopy(self.packet.get("full_schedule")),
            ui_options=dict(
                locations=[p["id"] for p in config["places"]],
                repair_evidence=[p["id"] for p in config["evidence"] if p["status"] == "PASS"],
                person_templates=list(registry()),
            ),
            closed=any(
                r["status"] == "APPLIED"
                and self.journal["requests"].get(r["request_id"], {}).get("kind") == "CLOSE_INPUT"
                for r in self.receipts.values()
            ),
        )

    def build_request(self, form):
        view = self.snapshot()
        if not view["writable"]:
            raise ValueError("READ_ONLY_OR_STALE")
        e = view["envelope"]
        kind, target = form["kind"], form["target_id"].strip()
        objects = self.packet["catalog"]["objects"]
        payload = deepcopy(form.get("payload", {}))
        if kind == "ORDER_CREATE":
            template = payload["template_id"]
            payload.update(
                order_id=target,
                template_revision="v1",
                template_sha256=template_registry()[template],
                material_plan_id=payload.get("material_plan_id", "TEMPLATE-JIT-v1"),
                arrival_rule="REQUEST_EFFECTIVE_TIME",
            )
        elif kind == "ORDER_UPDATE":
            payload["order_id"] = target
        elif kind == "PERSON_ARRIVE":
            from adaptive_hrc_scheduling.contracts.production import decode
            from adaptive_hrc_scheduling.domain.production import Configuration

            c = decode(Configuration, self.consumer.basis["configuration"])
            payload = arrival_payload(
                c,
                target,
                payload.get("template_id", "P043-W1-v1"),
                location=payload.get("arrival_location", "F1"),
                initial_f=payload.get("initial_f", 0.1),
            )
            if self.spec["backend"] == "ISAAC":
                payload["scene_reference"]["prim_path"] = "/World/P043/People/" + target
        if kind in ("CLOSE_INPUT", "STOP_REQUEST"):
            target = self.spec["run_id"]
        request = dict(
            run_id=self.spec["run_id"],
            epoch=self.spec["epoch"],
            request_id="P051-" + uuid.uuid4().hex,
            producer_id=self.journal["producer_id"],
            client_sequence=self.journal["sequence"] + 1,
            source="GUI",
            kind=kind,
            target_id=target,
            payload=payload,
            expected_catalog_version=e["catalog_version"],
            expected_state_revision=e["state_revision"],
            expected_target_revision=objects.get(target, {}).get("revision", 0),
            time_rule=form.get("time_rule", "IMMEDIATE"),
            expires_sim_h=form.get("expires_sim_h", self.spec["clock"]["session_until_h"]),
            submitted_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        if request["time_rule"] == "AT_SIM_H":
            request["requested_sim_h"] = form["requested_sim_h"]
        request["request_digest"] = request_digest(request)
        return validate_request(request)

    def submit(self, request):
        """The confirmed exact preview is persisted before publication. No auto retry."""
        validate_request(request)
        if request["request_digest"] != request_digest(request):
            raise ValueError("PREVIEW_CHANGED")
        if (request["run_id"], request["epoch"], request["producer_id"]) != (
            self.spec["run_id"],
            self.spec["epoch"],
            self.journal["producer_id"],
        ):
            raise ValueError("CLIENT_IDENTITY")
        if request["request_id"] in self.journal["requests"]:
            raise ValueError("QUERY_ORIGINAL_ID; DO_NOT_RESUBMIT")
        if (
            request["client_sequence"] != self.journal["sequence"] + 1
            or not self.snapshot()["writable"]
        ):
            raise ValueError("READ_ONLY_OR_SEQUENCE_CHANGED")
        from s19b_desktop.model import atomic_json

        # The reviewed business parameters remain fixed. Bind optimistic global
        # read versions at confirmation, rather than to the wall time spent
        # reading a preview. A changed target requires a new review.
        view = self.snapshot()
        target = self.packet["catalog"]["objects"].get(request["target_id"], {})
        if target.get("revision", 0) != request["expected_target_revision"]:
            raise ValueError("TARGET_CHANGED_SINCE_PREVIEW")
        submitted = deepcopy(request)
        submitted["expected_catalog_version"] = view["envelope"]["catalog_version"]
        submitted["expected_state_revision"] = view["envelope"]["state_revision"]
        submitted["request_digest"] = request_digest(submitted)
        self.journal.setdefault("confirmation_bindings", {})[request["request_id"]] = dict(
            preview_digest=request["request_digest"],
            submitted_digest=submitted["request_digest"],
            preview_state_revision=request["expected_state_revision"],
            submitted_state_revision=submitted["expected_state_revision"],
            business_payload_unchanged=submitted["payload"] == request["payload"],
        )
        self.journal["sequence"] = request["client_sequence"]
        self.journal["requests"][request["request_id"]] = submitted
        atomic_json(self.client_path, self.journal)
        # A failure after the durable local journal means UNKNOWN. Reconnect
        # queries this ID and never creates another business request.
        # Confirmed business payloads are bound once at the real consumption
        # boundary. Session still checks the resulting exact wire request.
        (self.directory / "p051-confirmations/inbox").mkdir(parents=True, exist_ok=True)
        submit_file(self.directory / "p051-confirmations", submitted)
        return dict(request_id=request["request_id"], status="SUBMITTED", business="UNKNOWN")


def prepare_launch(root, runs, form):
    """Construct the existing RunSpec and worker request from typed UI fields."""
    from build_simulation_production import configuration as base
    from s19b_desktop.control import command, confirmation, submit
    from s19b_desktop.model import PROTOCOL, Draft, atomic_json
    from s19b_desktop.model import validate_request as validate_launch

    from adaptive_hrc_scheduling.control.online import Limits
    from adaptive_hrc_scheduling.control.session_budget import Profile
    from adaptive_hrc_scheduling.control.session_lifecycle import enable
    from adaptive_hrc_scheduling.dynamic_workforce import registry
    from adaptive_hrc_scheduling.workforce_session import configuration, make_spec

    count = form.get("products", 1)
    draft = Draft(form.get("variant", "SR-W1"), count, (0.0,) * count).validate()
    method, backend = form.get("method", "ADAPTIVE"), form.get("backend", "isaac")
    if method not in ("EDD", "ADAPTIVE") or backend not in ("isaac", "light"):
        raise ValueError("LAUNCH_OPTIONS")
    rate = float(form.get("simulation_rate", 0.01))
    if not math.isfinite(rate) or not 0 < rate <= 100:
        raise ValueError("SIMULATION_RATE")
    config = configuration(base(products=count, variant=draft.variant))
    from adaptive_hrc_scheduling.full_schedule import configuration as fixed_configuration

    config = fixed_configuration(config)
    witness = form.get("witness_recipe")
    if witness is not None:
        from adaptive_hrc_scheduling.p052_witness import RECIPE
        from adaptive_hrc_scheduling.p052_witness import configuration as witness_configuration

        if witness != RECIPE:
            raise ValueError("WITNESS_RECIPE_UNSUPPORTED")
        config = witness_configuration(base(products=count, variant=draft.variant))
    profile = Profile(
        "P051-FULL-JOINT-r1",
        Limits(decision_seconds=5, search_seconds=1),
        10800 if witness else 3600,
        6 if witness else 4,
        "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
    )
    run_id = ("P051-E20-" if witness else "P051-") + uuid.uuid4().hex
    directory = Path(runs) / run_id
    directory.mkdir(parents=True, exist_ok=False)
    spec = enable(
        make_spec(
            config,
            profile,
            run_id=run_id,
            method=method,
            backend="ISAAC" if backend == "isaac" else "CPU",
            rates={k: 10 for k in [*[p.id for p in config.people], *registry()]},
        ),
        simulation_rate=rate,
        boundary_poll_wall_s=0.25,
        session_until_h=float(form.get("session_until_h", 720)),
        wall_budget_s=float(form.get("wall_budget_s", 3600)),
        idle_step_h=2.0,
    )
    if "witness_wip_products" in form:
        from adaptive_hrc_scheduling.contracts.session import validate_spec

        limit = form["witness_wip_products"]
        if not witness or type(limit) is not int or limit not in (3, 4):
            raise ValueError("WITNESS_CAPACITY_UNSUPPORTED")
        spec["capacity"]["max_wip_products"] = limit
        validate_spec(spec)
    request = dict(
        protocol=PROTOCOL,
        run_id=run_id,
        request_id=uuid.uuid4().hex,
        backend=backend,
        draft=draft.data(),
        created_at=datetime.now(timezone.utc).isoformat(),
        display_hold_s=0,
        session=dict(spec=spec, profile=asdict(profile), fixed_requests=[]),
    )
    request["control"] = confirmation(request, root, directory)
    validate_launch(request)
    atomic_json(directory / "request.json", request)
    start_command = command(request, "start", 1)
    atomic_json(directory / "start-command.json", start_command)
    submit(directory, start_command)
    return directory, request
