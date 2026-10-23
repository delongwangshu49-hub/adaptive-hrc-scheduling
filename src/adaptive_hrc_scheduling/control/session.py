"""Shared P04 worker: versioned requests around the existing production executor.

Device changes, cancellation and P042 order generation use real transactions.
P043 personnel transitions and opt-in P044 continuous lifetime share the writer.
The catalog is a sidecar: C0, old commands and execution prefixes never get re-signed.
"""

import hashlib
import math
import os
from copy import deepcopy
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty, Queue
from time import monotonic

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data, require
from adaptive_hrc_scheduling.contracts.production import digest as config_digest
from adaptive_hrc_scheduling.contracts.session import (
    canonical,
    digest,
    loads,
    validate_bundle,
    validate_record,
    validate_request,
    validate_spec,
)
from adaptive_hrc_scheduling.control.online import OnlinePolicy
from adaptive_hrc_scheduling.control.production_loop import Scenario
from adaptive_hrc_scheduling.control.session_budget import BudgetAccount
from adaptive_hrc_scheduling.domain import production as m


def source_identity():
    root = Path(__file__).resolve().parents[1]
    return digest(
        {
            p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob("*"))
            if p.suffix in (".py", ".json")
        }
    )


def registries(config):
    from adaptive_hrc_scheduling.dynamic_orders import template_registry

    templates = template_registry()
    qualification = {
        p.id: dict(qualifications=list(p.qualifications), valid_until_h=p.valid_until_h)
        for p in config.people
    }
    return templates, qualification


def save_atomic(path, data):
    temp = path.with_suffix(".tmp")
    with temp.open("wb") as stream:
        stream.write(canonical(data))
        stream.flush()
        os.fsync(stream.fileno())
    temp.replace(path)


def make_spec(
    config,
    profile,
    *,
    run_id,
    method="ADAPTIVE",
    mode="INTERACTIVE_PRODUCTION",
    scenario="INTERACTIVE",
    backend="CPU",
    until_h=720,
    rates,
    fixed_requests=None,
    replay_source=None,
):
    """Client convenience; the worker independently binds all inputs again."""
    templates, qualifications = registries(config)
    c0 = config_digest(config)
    cost = dict(
        policy_id="PRESENCE_LABOUR-r2",
        currency="MODEL_UNIT",
        rates=[dict(template_id=p.id, rate_per_h=rates[p.id]) for p in config.people],
        person_template_ids=[p.id for p in config.people],
        legacy_resource_cost_source_sha256=c0,
    )
    cost["policy_sha256"] = digest(cost)
    initial_orders = {}
    for product in config.products:
        row = dict(
            order_id=product.order_id,
            template_id=product.variant,
            template_revision="v1",
            quantity=0,
            due_sim_h=product.due_h,
            priority="NORMAL",
        )
        if product.order_id in initial_orders:
            prior = initial_orders[product.order_id]
            require(
                all(prior[k] == row[k] for k in row if k != "quantity"),
                "INITIAL_ORDER_INCONSISTENT",
            )
        else:
            initial_orders[product.order_id] = row
        initial_orders[product.order_id]["quantity"] += 1
    spec = dict(
        schema_version="P03.2-CONTRACT-r3",
        canonical_version="P032-CANONICAL-1",
        run_id=run_id,
        epoch=0,
        mode=mode,
        scenario=scenario,
        backend=backend,
        method=method,
        budget_profile_id=profile.id,
        source_sha256=source_identity(),
        initial_config_sha256=c0,
        template_registry_sha256=digest(templates),
        qualification_registry_sha256=digest(qualifications),
        profile_sha256=profile.sha256,
        initial_orders=list(initial_orders.values()),
        initial_people=[
            dict(
                person_id=p.id,
                parameter_template_id=p.id,
                calendar_id=p.id,
                initial_f=p.initial_f,
                qualification_evidence_id=p.id,
            )
            for p in config.people
        ],
        cost=cost,
        capacity=dict(
            max_lifetime_products=4, max_open_products=4, max_queued_products=4, max_wip_products=3
        ),
        clock=dict(
            idle_policy="ADVANCE_METERED",
            session_until_h=until_h,
            wall_budget_s=3600,
            idle_step_h=0.01,
            simulation_rate=0.01,
            boundary_poll_wall_s=0.1,
        ),
    )
    if mode == "FIXED_PROTOCOL":
        spec["fixed_event_manifest_sha256"] = digest(fixed_requests or [])
    if replay_source is not None:
        spec["replay_source_sha256"] = digest(replay_source)
    return validate_spec(spec)


class Session:
    """Single writer. Queue producers never touch live state or receive future facts."""

    capabilities = (
        "ORDER_CREATE",
        "DEVICE_FAIL",
        "DEVICE_REPAIR",
        "ORDER_CANCEL",
        "CLOSE_INPUT",
        "STOP_REQUEST",
    )

    def __init__(
        self, spec, backend, profile, output, *, source="CLI", fixed_requests=(), replay_source=None
    ):
        self.spec = validate_spec(spec)
        spec = self.spec
        self.backend = backend
        self.world = getattr(backend, "world", backend)
        c = self.world.config
        self.workforce_enabled = c.schema_version == "P043-PROD-1.0"
        if self.workforce_enabled and hasattr(backend, "world"):
            backend.port.workforce_world = self.world
        if self.workforce_enabled:
            from adaptive_hrc_scheduling.dynamic_workforce import KINDS

            self.capabilities = (*self.capabilities, *KINDS)
        require(
            len(c.products) <= spec["capacity"]["max_lifetime_products"], "INITIAL_LIFETIME_LIMIT"
        )
        require(len(c.products) <= spec["capacity"]["max_open_products"], "INITIAL_QUEUE_LIMIT")
        self.order_products = {}
        for product in c.products:
            self.order_products.setdefault(product.order_id, []).append(product.id)
        require(
            not set(self.order_products) & {x.id for x in (*c.products, *c.people, *c.devices)},
            "INITIAL_ORDER_ID_COLLISION",
        )
        self.launch_event_count = len(self.world.events)
        self._prefix_hasher = hashlib.sha256(b"[")
        self._prefix_events = []
        require(
            (self.world.run_id, self.world.epoch) == (spec["run_id"], spec["epoch"]),
            "LAUNCH_IDENTITY",
        )
        require(spec["initial_config_sha256"] == config_digest(c), "INITIAL_CONFIGURATION")
        require(spec["source_sha256"] == source_identity(), "SOURCE_BINDING")
        require(
            spec["profile_sha256"] == profile.sha256 and spec["budget_profile_id"] == profile.id,
            "PROFILE_BINDING",
        )
        templates, qualifications = registries(c)
        require(
            spec["template_registry_sha256"] == digest(templates)
            and spec["qualification_registry_sha256"] == digest(qualifications),
            "REGISTRY_BINDING",
        )
        require(
            spec["backend"] == ("ISAAC" if hasattr(backend, "world") else "CPU"), "BACKEND_BINDING"
        )
        expected = make_spec(c, profile, run_id=spec["run_id"], rates={p.id: 0 for p in c.people})
        require(
            [dict(r, priority="NORMAL") for r in spec["initial_orders"]]
            == expected["initial_orders"]
            and spec["initial_people"] == expected["initial_people"],
            "INITIAL_OVERRIDE_NOT_MATERIALIZED",
        )
        cost = spec["cost"]
        if self.workforce_enabled:
            from adaptive_hrc_scheduling.dynamic_workforce import registry

            require(
                set(cost["person_template_ids"]) == {p.id for p in c.people} | set(registry()),
                "WORKFORCE_RATE_REGISTRY",
            )
        require(
            cost["policy_sha256"]
            == digest({k: v for k, v in cost.items() if k != "policy_sha256"}),
            "COST_POLICY_DIGEST",
        )
        self.fixed_requests = tuple(deepcopy(fixed_requests))
        if spec["mode"] == "FIXED_PROTOCOL":
            require(
                digest(self.fixed_requests) == spec["fixed_event_manifest_sha256"], "FIXED_MANIFEST"
            )
        if spec["mode"] == "INTERACTIVE_REPLAY":
            validate_bundle(
                dict(
                    spec=spec,
                    profile=asdict(profile),
                    fixed_requests=list(fixed_requests),
                    replay_source=replay_source,
                )
            )
        self.replay_source = deepcopy(replay_source)
        self.replay_received = set()
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=False)
        (self.output / "inbox").mkdir()
        self.ingress_seen = {}
        self.protocol_errors = []
        self.queue = Queue()
        self.source = source
        self.account = BudgetAccount(profile)
        self.policy = OnlinePolicy(
            c, profile.limits, end_h=spec["clock"]["session_until_h"], budget_account=self.account
        )
        if spec["method"] == "EDD":
            # Same shield/choice/dispatch path; only joint search is disabled.
            self.policy._search_allowed = lambda trigger: False
        self.catalog = dict(
            configuration_sha256=config_digest(c),
            objects={
                x.id: dict(revision=0, kind=kind, available=True)
                for kind, rows in (
                    ("product", c.products),
                    ("person", c.people),
                    ("device", c.devices),
                )
                for x in rows
            },
        )
        for order, products in self.order_products.items():
            self.catalog["objects"][order] = dict(
                revision=0, kind="order", available=True, product_ids=products
            )
        self.initial_catalog = deepcopy(self.catalog)
        self.versions = [digest(self.catalog)]
        self.deltas, self.receipts, self.admissions, self.requests = [], [], {}, {}
        self.sequences, self.command_bindings, self.observation_bindings = {}, {}, []
        self.transitions, self.scene_bindings = [], []
        from adaptive_hrc_scheduling.dynamic_orders import CatalogHistory

        self.history = CatalogHistory(c)
        if self.workforce_enabled:
            from adaptive_hrc_scheduling.dynamic_workforce import WorkforceHistory

            self.history = WorkforceHistory(c)
        self.policy.catalog_context = self.history
        self.active_products = {
            p.id
            for p in sorted(c.products, key=lambda p: (p.due_h, p.id))
            if self.world._product(p.id).released
        }
        self.active_products = set(
            sorted(
                self.active_products,
                key=lambda pid: next((p.due_h, p.id) for p in c.products if p.id == pid),
            )[: spec["capacity"]["max_wip_products"]]
        )
        require(
            len(c.products) - len(self.active_products) <= spec["capacity"]["max_queued_products"],
            "INITIAL_QUEUE_LIMIT",
        )
        self.world.dispatch_products = self.active_products
        self.history.active_products = self.active_products
        self.material_due = {}
        self.capacity_events = []
        self.business_results = []
        self.workforce_results = []
        self.closed = self.stopped = False
        self.close_sequence = None
        self.accept_count = 0
        self.terminal = False
        self.terminal_queries = {}
        self.binding = dict(
            session_format="P043-SESSION-r2" if self.workforce_enabled else "P041-SESSION-r2",
            launch_event_count=self.launch_event_count,
            launch_prefix_hash=digest([as_data(e) for e in self.world.events]),
            run_id=spec["run_id"],
            epoch=spec["epoch"],
            case=spec["scenario"],
            method=spec["method"],
            mode=spec["mode"],
            backend=spec["backend"],
            profile_id=profile.id,
            profile_sha256=profile.sha256,
            run_spec_sha256=digest(self.spec),
            source=source,
            source_sha256=spec["source_sha256"],
            capabilities=list(self.capabilities),
            objective=profile.objective,
            rule=(
                "P042_URGENCY_THEN_EDD_THEN_LEGAL_CHOICE"
                if profile.objective == "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1"
                else "EDD_DUE_H_THEN_LEGAL_CHOICE"
            ),
            legality="P043_WORKFORCE_WITH_UNCHANGED_PHYSICAL_MODEL"
            if self.workforce_enabled
            else "UNCHANGED_PRODUCTION_ADMISSION_AND_EXECUTION_CHECKERS",
        )
        self.policy.method = spec["method"]
        save_atomic(self.output / "run-spec.json", self.spec)
        save_atomic(self.output / "profile.json", asdict(profile))
        save_atomic(self.output / "launch-binding.json", self.binding)
        save_atomic(self.output / "configuration.json", as_data(c))
        from .session_lifecycle import IDENTITY, Lifecycle

        self.lifecycle = Lifecycle(self) if spec["schema_version"] == IDENTITY else None
        self.projection = None
        if self.lifecycle is not None:
            from adaptive_hrc_scheduling.timeline import TimelinePublisher

            self.projection = TimelinePublisher(self)
            source_root = Path(__file__).resolve().parents[1]
            source_files = {
                p.relative_to(source_root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sorted(source_root.rglob("*"))
                if p.suffix in (".py", ".json")
            }
            require(digest(source_files) == spec["source_sha256"], "LAUNCH_SOURCE_CHANGED")
            save_atomic(self.output / "launch-sources.json", source_files)
        self.persist()

    @property
    def version(self):
        return len(self.deltas)

    def persist(self):
        # Every durable checkpoint includes a current capacity projection.
        self.refresh_capacity()
        workforce = {}
        if self.workforce_enabled:
            from adaptive_hrc_scheduling.workforce_metrics import project

            workforce = dict(
                workforce_results=self.workforce_results,
                workforce_statistics=project(self.spec, self.history, self.world.snapshot()),
            )
        save_atomic(
            self.output / "session-state.json",
            dict(
                session_format="P043-SESSION-r2" if self.workforce_enabled else "P041-SESSION-r2",
                launch_event_count=self.launch_event_count,
                replay_source=self.replay_source,
                binding=self.binding,
                initial_catalog=self.initial_catalog,
                catalog=self.catalog,
                versions=self.versions,
                deltas=self.deltas,
                receipts=self.receipts,
                admissions=self.admissions,
                requests=self.requests,
                producer_sequences=self.sequences,
                command_bindings=self.command_bindings,
                observations=self.observation_bindings,
                cache_transitions=self.transitions,
                scene_bindings=self.scene_bindings,
                closed=self.closed,
                close_accept_sequence=self.close_sequence,
                stopped=self.stopped,
                terminal=self.terminal,
                execution=as_data(self.world.snapshot()),
                ingress_seen=self.ingress_seen,
                protocol_errors=self.protocol_errors,
                budget=self.account.report(),
                dynamic_format="P043-WORKFORCE-2" if self.workforce_enabled else "P042-DYNAMIC-2",
                generations=self.history.generations,
                active_products=sorted(self.active_products),
                material_due=self.material_due,
                capacity_events=self.capacity_events,
                business_results=self.business_results,
                lifecycle=self.lifecycle.data() if getattr(self, "lifecycle", None) else None,
                **workforce,
            ),
        )
        self._last_persist_wall = monotonic()

    def _receipt(self, req, status, reason, *, sequence=None, event=None, before=None):
        receipt = dict(
            receipt_id=f"RECEIPT-{len(self.receipts) + 1}",
            receipt_sequence=len(self.receipts) + 1,
            request_id=req["request_id"],
            request_digest=req["request_digest"],
            status=status,
            sim_h=self.world.s.time_h,
            at_utc=datetime.now(timezone.utc).isoformat(),
            reason=reason,
            catalog_version_before=self.version if before is None else before,
            catalog_version_after=self.version,
            state_revision=self.world.s.revision,
            previous_receipt_hash=digest(self.receipts[-1]) if self.receipts else "0" * 64,
        )
        if sequence is not None:
            receipt["accept_sequence"] = sequence
        if event is not None:
            receipt["event_id"] = event.id
        if status == "APPLIED":
            receipt["actual_applied_sim_h"] = self.world.s.time_h
        validate_record("Receipt", receipt)
        if self.terminal and self.lifecycle:
            with (self.output / "terminal-receipts.jsonl").open("ab") as stream:
                stream.write(canonical(receipt) + b"\n")
            return deepcopy(receipt)
        self.receipts.append(receipt)
        self.persist()
        return deepcopy(receipt)

    def submit(self, request):
        self.queue.put(deepcopy(request))

    def receive(self, request):
        req = validate_request(request)
        try:
            require(
                (req["run_id"], req["epoch"]) == (self.spec["run_id"], self.spec["epoch"]),
                "IDENTITY_EPOCH",
            )
            previous = self.requests.get(req["request_id"])
            if previous:
                require(previous == req, "IDEMPOTENCY_CONFLICT")
                return deepcopy(
                    next(
                        r
                        for r in reversed(self.receipts)
                        if r["request_id"] == req["request_id"]
                        and r["request_digest"] == req["request_digest"]
                    )
                )
            if self.terminal and self.lifecycle:
                key = (req["request_id"], req["request_digest"])
                if key not in self.terminal_queries:
                    self.terminal_queries[key] = self._receipt(req, "REJECTED", "SESSION_TERMINAL")
                return deepcopy(self.terminal_queries[key])
            self.requests[req["request_id"]] = req
            require(not self.terminal, "SESSION_TERMINAL")
            require(
                not self.stopped and not getattr(self.lifecycle, "stop_intake", False),
                "SESSION_STOPPED",
            )
            mode = self.spec["mode"]
            require(
                (
                    mode == "FIXED_PROTOCOL"
                    and req in self.fixed_requests
                    and req["source"] == "FIXED_MANIFEST"
                )
                or (
                    mode == "INTERACTIVE_REPLAY"
                    and req["source"] == "REPLAY"
                    and req in self.replay_source["requests"]
                )
                or (mode == "INTERACTIVE_PRODUCTION" and req["source"] in ("GUI", "CLI")),
                "PROTOCOL_LOCKED",
            )
            require(req["kind"] in self.capabilities, "CAPABILITY_NOT_IMPLEMENTED")
            require(
                req["client_sequence"] > self.sequences.get(req["producer_id"], 0),
                "CLIENT_SEQUENCE_OLD",
            )
            require(req["expected_catalog_version"] == self.version, "CATALOG_STALE")
            require(req["expected_state_revision"] == self.world.s.revision, "STATE_STALE")
            target = self.catalog["objects"].get(req["target_id"])
            if req["kind"] == "ORDER_CREATE":
                require(not self.closed, "INPUT_CLOSED")
                require(target is None, "ORDER_ID_USED")
                require(req["target_id"] == req["payload"]["order_id"], "TARGET_PAYLOAD_MISMATCH")
                self.check_order(req["payload"])
            elif req["kind"].startswith("PERSON_"):
                from adaptive_hrc_scheduling.workforce_session import check_request

                check_request(self, req)
            elif req["kind"] in ("CLOSE_INPUT", "STOP_REQUEST"):
                require(req["target_id"] == self.spec["run_id"], "TARGET_PAYLOAD_MISMATCH")
            else:
                require(target is not None, "UNKNOWN_TARGET")
                require(
                    target["kind"] == ("order" if req["kind"] == "ORDER_CANCEL" else "device"),
                    "TARGET_KIND",
                )
            require(
                req["expected_target_revision"] == (target["revision"] if target else 0),
                "TARGET_STALE",
            )
            now = self.world.s.time_h
            due = req.get("requested_sim_h", now)
            require(due >= now, "PAST_TIME")
            require(req["expires_sim_h"] >= due, "EXPIRED")
            if req["kind"] == "DEVICE_REPAIR":
                require(
                    req["payload"]["repair_evidence_id"]
                    in {e.id for e in self.world.config.evidence if e.status == "PASS"},
                    "REPAIR_EVIDENCE_INVALID",
                )
            self.accept_count += 1
            read_set = (
                [
                    dict(
                        object_id=req["target_id"],
                        revision=target["revision"],
                        sha256=digest(target),
                    )
                ]
                if target
                else []
            )
            self.requests[req["request_id"]] = req
            self.sequences[req["producer_id"]] = req["client_sequence"]
            self.admissions[req["request_id"]] = dict(
                sequence=self.accept_count,
                due_h=due,
                read_set=read_set,
                read_set_hash=digest(read_set),
                accepted_version=self.version,
                accepted_revision=self.world.s.revision,
            )
            return self._receipt(req, "ACCEPTED", "QUEUED", sequence=self.accept_count)
        except ContractError as exc:
            return self._receipt(req, "REJECTED", str(exc))

    def boundary(self):
        if self.lifecycle and self.replay_source:
            for req in self.replay_source["requests"]:
                key = req["request_id"]
                if (
                    key not in self.replay_received
                    and self.replay_source["received_sim_h"][key] <= self.world.s.time_h
                ):
                    self.submit(req)
                    self.replay_received.add(key)
        # Directory enumeration is the writer's observed arrival order, recorded
        # durably here. Neither filenames nor client clocks impose causal order.
        for path in (self.output / "inbox").glob("*.json"):
            raw = path.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            if path.name in self.ingress_seen:
                require(self.ingress_seen[path.name] == sha, "INBOX_MUTATED")
                continue
            try:
                request = loads(raw)
                validate_request(request)
                self.submit(request)
            except (ContractError, ValueError, TypeError) as exc:
                self.protocol_errors.append(dict(file=path.name, sha256=sha, reason=str(exc)))
            self.ingress_seen[path.name] = sha
        for _ in range(self.queue.qsize()):
            try:
                queued = self.queue.get_nowait()
            except Empty:
                break
            try:
                self.receive(queued)
            except (ContractError, ValueError, TypeError) as exc:
                self.protocol_errors.append(dict(ingress="QUEUE", reason=str(exc)))
        pending = []
        for key, admission in self.admissions.items():
            last = next(
                r
                for r in reversed(self.receipts)
                if r["request_id"] == key and r.get("accept_sequence") == admission["sequence"]
            )
            if last["status"] in ("ACCEPTED", "WAITING_BOUNDARY"):
                pending.append((self.requests[key], admission))
        rank = {
            "DEVICE_FAIL": 0,
            "PERSON_ABSENT": 0,
            "ORDER_CANCEL": 1,
            "PERSON_DEPART": 1,
            "STOP_REQUEST": 1,
        }
        pending.sort(key=lambda pair: (rank.get(pair[0]["kind"], 2), pair[1]["sequence"]))
        touched = set()
        for req, admission in pending:
            seq = admission["sequence"]
            now = self.world.s.time_h
            if now > req["expires_sim_h"]:
                self._receipt(req, "REJECTED", "EXPIRED", sequence=seq)
                continue
            if now < admission["due_h"]:
                if not any(
                    r["request_id"] == req["request_id"] and r["status"] == "WAITING_BOUNDARY"
                    for r in self.receipts
                ):
                    self._receipt(req, "WAITING_BOUNDARY", "FUTURE_BOUNDARY", sequence=seq)
                continue
            try:
                require(
                    not (self.stopped or getattr(self.lifecycle, "stop_intake", False))
                    or req["kind"] == "STOP_REQUEST",
                    "SESSION_STOPPED",
                )
                require(req["target_id"] not in touched, "SAME_TICK_CONFLICT")
                for dep in admission["read_set"]:
                    require(
                        digest(self.catalog["objects"][dep["object_id"]]) == dep["sha256"],
                        "TARGET_CONFLICT",
                    )
                self._apply(req, admission)
                touched.add(req["target_id"])
            except ContractError as exc:
                self._receipt(req, "REJECTED", str(exc), sequence=seq)
        if self.workforce_enabled:
            from adaptive_hrc_scheduling.workforce_session import settle_departures

            settle_departures(self)
        # Receipts and transactions force a durable save above. Ordinary
        # execution checkpoints are metered; final run always flushes again.
        if monotonic() - self._last_persist_wall >= 10:
            self.persist()

    def capacity(self):
        states = self.world.s.products
        open_ids = {p.product_id for p in states if not p.cancelled and p.received_h is None}
        physical = {
            x.product_id
            for x in (*self.world.config.lots, *self.world.config.entities)
            if self.world._mass(x.id) > 1e-9
            and self.world._position(x.id).location
            not in (
                "SUPPLIER",
                "UNPRODUCED",
                "UNFABRICATED",
                "UNASSEMBLED",
                "EXTERNAL",
                "INCORPORATED",
            )
        }
        return dict(
            count_registered=len(states),
            count_open=len(open_ids),
            count_queued=len(open_ids - self.active_products),
            count_instantiated=len(states),
            count_space_reserved=len(self.active_products),
            count_wip=len(physical),
            count_scene_entities=len(self.world.config.entities) + len(self.world.config.lots),
        )

    def check_order(self, payload):
        from adaptive_hrc_scheduling.dynamic_orders import MATERIAL_PLANS, template_registry

        require(payload["order_id"] not in self.catalog["objects"], "ORDER_ID_USED")
        require(
            self.account.profile.objective == "P042_URGENCY_DUE_PROGRESS_EXPOSURE-r1",
            "DYNAMIC_OBJECTIVE_PROFILE_REQUIRED",
        )
        require(
            payload["order_id"]
            not in {
                x.id
                for x in (
                    *self.world.config.lots,
                    *self.world.config.entities,
                    *self.world.config.operations,
                )
            },
            "ORDER_ID_USED",
        )
        require(not self.world.config.rework_enabled, "DYNAMIC_REWORK_TEMPLATE_UNSUPPORTED")
        require(
            template_registry().get(payload["template_id"]) == payload["template_sha256"],
            "TEMPLATE_DIGEST",
        )
        require(payload["material_plan_id"] in MATERIAL_PLANS, "MATERIAL_PLAN_UNSUPPORTED")
        require(payload["due_sim_h"] > self.world.s.time_h, "DUE_PASSED")
        counts, cap, quantity = self.capacity(), self.spec["capacity"], payload["quantity"]
        require(
            counts["count_registered"] + quantity <= cap["max_lifetime_products"], "LIFETIME_LIMIT"
        )
        require(counts["count_open"] + quantity <= cap["max_open_products"], "QUEUE_LIMIT")
        # All generated products first enter the logical queue, then compete for WIP.
        require(counts["count_queued"] + quantity <= cap["max_queued_products"], "QUEUE_LIMIT")

    def create_order(self, req, admission):
        import copy

        from adaptive_hrc_scheduling.dynamic_orders import MATERIAL_PLANS, append_world, generate

        self.check_order(req["payload"])
        before, revision = self.version, self.world.s.revision
        config, products = generate(self.world.config, req["payload"], self.world.s.time_h)
        require(
            not set(products) & self.catalog["objects"].keys()
            and req["target_id"] not in self.catalog["objects"],
            "GENERATION_ID_COLLISION",
        )
        # Stage the complete transaction without mutating the running executor.
        candidate = copy.copy(self.world)
        for name in ("operations", "routes", "places", "lots", "entities"):
            setattr(candidate, name, dict(getattr(self.world, name)))
        append_world(candidate, config, products)
        retained = replace(
            candidate.s,
            lots=self.world.s.lots,
            positions=self.world.s.positions,
            products=self.world.s.products,
            masses=self.world.s.masses,
            research=self.world.s.research,
        )
        require(retained == self.world.s, "ORIGINAL_STATE_CHANGED")
        row = dict(
            request_id=req["request_id"],
            request_digest=req["request_digest"],
            payload=deepcopy(req["payload"]),
            sim_h=self.world.s.time_h,
            product_ids=list(products),
            before_config_sha256=self.world.config_hash,
            config_sha256=config_digest(config),
            event_id=f"EV-{len(self.world.events) + 1}",
            catalog_version=before + 1,
            template_registry_sha256=self.spec["template_registry_sha256"],
            before_event_count=len(self.world.events),
            before_prefix_sha256=self.event_prefix_hash(),
            protected_before_sha256=digest(as_data(self.world.s)),
            protected_after_sha256=digest(as_data(retained)),
        )
        # Preparation may create only invisible empty USD objects. Failure leaves
        # C0/progress untouched and the accepted request waiting for a later boundary.
        if hasattr(self.backend, "world"):
            try:
                scene_rows = self.backend.port.append_catalog(config, products, before + 1)
            except Exception as exc:
                self.business_results.append(
                    dict(
                        request_id=req["request_id"],
                        status="WAITING_SCENE",
                        reason=str(exc),
                        sim_h=self.world.s.time_h,
                    )
                )
                self._receipt(
                    req, "WAITING_BOUNDARY", "WAITING_SCENE", sequence=admission["sequence"]
                )
                return
        else:
            scene_rows = [
                dict(
                    domain_id=x.id,
                    scene_entity_id=x.id,
                    prim_path="CPU:N/A",
                    template_revision="v1",
                    catalog_version=before + 1,
                )
                for x in (*config.lots, *config.entities)
                if x.product_id in products
            ]
        self.history.append(row)
        for name in (
            "config",
            "config_hash",
            "s",
            "operations",
            "routes",
            "places",
            "lots",
            "entities",
        ):
            setattr(self.world, name, getattr(candidate, name))
        event = self.world.apply_world(
            m.WorldEvent(
                "REGISTER-" + req["request_id"],
                self.world.run_id,
                self.world.epoch,
                self.world.s.time_h,
                "CATALOG_REGISTER",
                req["target_id"],
                products[0],
                0,
                "PASS",
                "P042-TEMPLATE-v1",
            )
        )
        require(event.id == row["event_id"], "GENERATION_EVENT")
        for pid in products:
            self.backend.apply_world(
                m.WorldEvent(
                    "ARRIVE-" + req["request_id"] + "-" + pid,
                    self.world.run_id,
                    self.world.epoch,
                    self.world.s.time_h,
                    "ORDER_ARRIVAL",
                    pid,
                    pid,
                    0,
                    "PASS",
                    "P042-ORDER",
                )
            )
            self.catalog["objects"][pid] = dict(revision=0, kind="product", available=True)
            self.material_due[pid] = (
                self.world.s.time_h + MATERIAL_PLANS[req["payload"]["material_plan_id"]]
            )
        self.order_products[req["target_id"]] = list(products)
        self.catalog["objects"][req["target_id"]] = dict(
            revision=0, kind="order", available=True, product_ids=list(products)
        )
        payload = dict(
            delta_id=f"DELTA-{before + 1}",
            request_id=req["request_id"],
            request_digest=req["request_digest"],
            kind="ORDER_CREATE",
            accept_sequence=admission["sequence"],
            actual_sim_h=self.world.s.time_h,
            read_set_hash=admission["read_set_hash"],
            state_revision_before=revision,
            state_revision_after=self.world.s.revision,
            object_ids=[req["target_id"], *products],
            generation_sha256=digest(row),
            commit_event_id=event.id,
        )
        h = digest(dict(previous_hash=self.versions[-1], version=before + 1, delta=payload))
        delta = dict(
            payload,
            old_version=before,
            new_version=before + 1,
            old_hash=self.versions[-1],
            new_hash=h,
            materialized_catalog_sha256=digest(self.catalog),
        )
        validate_record("CatalogDelta", delta)
        self.deltas.append(delta)
        self.versions.append(h)
        self.policy.config = config
        # A new competing order affects every uncommitted scheduling choice.
        promises = digest(as_data(self.policy.committed))
        running = tuple(r.command for r in self.world.s.running)
        known = {
            c.id for c in self.policy.pending if c not in self.policy.committed and c not in running
        }
        invalid = self.policy.catalog_changed(
            [p.id for p in config.products], self.world.operations, [event.id], running
        )
        self.transitions.append(
            dict(
                old_catalog_version=before,
                new_catalog_version=self.version,
                affected_object_ids=list(products),
                invalidated_keys=invalid,
                known_uncommitted_keys=sorted(known),
                revalidated_keys=[],
                reused_keys=[],
                surviving_commands={},
                cache_sha256=self.policy.cache_hash,
                reuse_proofs=[],
                protected_before_hash=promises,
                protected_after_hash=digest(as_data(self.policy.committed)),
                reason_event_ids=[event.id],
                rebase_from_version=admission["accepted_version"],
                read_set_hash=admission["read_set_hash"],
            )
        )
        self.scene_bindings.extend(
            dict(x, event_id=event.id, scope="DYNAMIC_EMPTY_ENTITY_READBACK") for x in scene_rows
        )
        if hasattr(self.backend, "world"):
            self.backend.ledger.catalog = self.history
            self.backend.ledger.config = config
        self.business_results.append(
            dict(
                request_id=req["request_id"],
                product_ids=list(products),
                status="REGISTERED",
                event_id=event.id,
                catalog_version=self.version,
                sim_h=self.world.s.time_h,
            )
        )
        self.refresh_capacity()
        self._receipt(
            req,
            "APPLIED",
            "ORDER_REGISTERED",
            sequence=admission["sequence"],
            event=event,
            before=before,
        )

    def refresh_capacity(self):
        def cleared(pid):
            return not any(r.command.product_id == pid for r in self.world.s.running) and not any(
                self.world._mass(x.id) > 1e-9
                and self.world._position(x.id).location
                not in ("EXTERNAL", "SUPPLIER", "UNPRODUCED", "INCORPORATED")
                for x in (*self.world.config.lots, *self.world.config.entities)
                if x.product_id == pid
            )

        for p in self.world.s.products:
            if p.received_h is not None or p.cancelled and cleared(p.product_id):
                self.active_products.discard(p.product_id)
        candidates = [
            p
            for p in self.world.s.products
            if p.released
            and not p.cancelled
            and p.received_h is None
            and p.product_id not in self.active_products
        ]
        products = {p.id: p for p in self.world.config.products}
        candidates.sort(
            key=lambda p: (
                self.history.priorities.get(p.product_id) != "URGENT",
                products[p.product_id].due_h,
                p.product_id,
            )
        )
        for p in candidates:
            if len(self.active_products) < self.spec["capacity"]["max_wip_products"]:
                self.active_products.add(p.product_id)
                self.capacity_events.append(
                    dict(
                        product_id=p.product_id,
                        status="WIP_ADMITTED",
                        sim_h=self.world.s.time_h,
                        event_count=len(self.world.events),
                        counts=self.capacity(),
                    )
                )
        counts = self.capacity()
        if not self.capacity_events or self.capacity_events[-1].get("counts") != counts:
            self.capacity_events.append(
                dict(
                    status="WAITING_SPACE" if counts["count_queued"] else "CAPACITY",
                    sim_h=self.world.s.time_h,
                    event_count=len(self.world.events),
                    counts=counts,
                )
            )

    def material_ready(self, product_id):
        return product_id in self.active_products and self.world.s.time_h >= self.material_due.get(
            product_id, 0
        )

    def _apply(self, req, admission):
        before = self.version
        kind, target = req["kind"], req["target_id"]
        if kind.startswith("PERSON_"):
            from adaptive_hrc_scheduling.workforce_session import apply_request

            return apply_request(self, req, admission)
        if kind == "ORDER_CREATE":
            return self.create_order(req, admission)
        if kind in ("CLOSE_INPUT", "STOP_REQUEST"):
            if kind == "CLOSE_INPUT":
                if not self.closed:
                    self.closed, self.close_sequence = (
                        True,
                        (self.accept_count if self.lifecycle else admission["sequence"]),
                    )
            else:
                self.stopped = True
            self._receipt(req, "APPLIED", kind, sequence=admission["sequence"])
            return
        state_before = self.world.s.revision
        entities = self.order_products[target] if kind == "ORDER_CANCEL" else [target]
        entity = entities[0]
        affected = [target, entity] if entity != target else [target]
        world_kind = {
            "DEVICE_FAIL": "FAILURE",
            "DEVICE_REPAIR": "REPAIR",
            "ORDER_CANCEL": "CANCEL",
        }[kind]
        event = self.backend.apply_world(
            m.WorldEvent(
                "REQUEST-" + req["request_id"],
                self.world.run_id,
                self.world.epoch,
                self.world.s.time_h,
                world_kind,
                entity,
                entity if kind == "ORDER_CANCEL" else self.world.config.products[0].id,
                0,
                "PASS",
                req["payload"].get("repair_evidence_id", "P041-REQUEST"),
            )
        )
        for extra in entities[1:]:
            self.backend.apply_world(
                m.WorldEvent(
                    "REQUEST-" + req["request_id"] + "-" + extra,
                    self.world.run_id,
                    self.world.epoch,
                    self.world.s.time_h,
                    "CANCEL",
                    extra,
                    extra,
                    0,
                    "PASS",
                    "P042-REQUEST",
                )
            )
            affected.append(extra)
        self.catalog["objects"][target]["revision"] += 1
        self.catalog["objects"][target]["available"] = kind == "DEVICE_REPAIR"
        if entity != target:
            for extra in entities:
                self.catalog["objects"][extra]["revision"] += 1
                self.catalog["objects"][extra]["available"] = False
        # Hash payload is explicitly separate from chain/materialized hashes.
        payload = dict(
            delta_id=f"DELTA-{before + 1}",
            request_id=req["request_id"],
            request_digest=req["request_digest"],
            kind=kind,
            accept_sequence=admission["sequence"],
            actual_sim_h=self.world.s.time_h,
            read_set_hash=admission["read_set_hash"],
            state_revision_before=state_before,
            state_revision_after=self.world.s.revision,
            object_ids=affected,
            generation_sha256=digest(req["payload"]),
            commit_event_id=event.id,
        )
        new_hash = digest(dict(previous_hash=self.versions[-1], version=before + 1, delta=payload))
        delta = dict(
            payload,
            old_version=before,
            new_version=before + 1,
            old_hash=self.versions[-1],
            new_hash=new_hash,
            materialized_catalog_sha256=digest(self.catalog),
        )
        validate_record("CatalogDelta", delta)
        self.deltas.append(delta)
        self.versions.append(new_hash)
        promises = digest(as_data(self.policy.committed))
        running = tuple(r.command for r in self.world.s.running)
        known = {
            c.id for c in self.policy.pending if c not in self.policy.committed and c not in running
        }
        invalid = self.policy.catalog_changed(affected, self.world.operations, [event.id], running)
        self.transitions.append(
            dict(
                old_catalog_version=before,
                new_catalog_version=self.version,
                affected_object_ids=affected,
                invalidated_keys=invalid,
                revalidated_keys=[],
                reused_keys=[],
                surviving_commands={c.id: as_data(c) for c in self.policy.pending if c.id in known},
                cache_sha256=self.policy.cache_hash,
                reuse_proofs=[],
                known_uncommitted_keys=sorted(known),
                protected_before_hash=promises,
                protected_after_hash=digest(as_data(self.policy.committed)),
                reason_event_ids=[event.id],
                rebase_from_version=admission["accepted_version"],
                read_set_hash=admission["read_set_hash"],
            )
        )
        self.scene_bindings.append(
            dict(
                domain_id=target,
                scene_entity_id=entity,
                prim_path="CPU:N/A"
                if self.spec["backend"] == "CPU"
                else self.backend.port.mapping[entity],
                template_revision="C0",
                catalog_version=self.version,
                event_id=event.id,
                scope="EXISTING_OBJECT_WORLD_ADAPTER",
            )
        )
        self._receipt(
            req,
            "APPLIED",
            "WORLD_COMMITTED",
            sequence=admission["sequence"],
            event=event,
            before=before,
        )

    def bind_observation(self, observation):
        require(observation.event_ids == tuple(e.id for e in self.world.events), "OBSERVED_PREFIX")
        row = dict(
            run_id=observation.run_id,
            epoch=observation.epoch,
            observation_id=observation.id,
            catalog_version=self.version,
            catalog_hash=self.versions[-1],
            state_revision=observation.state.revision,
            event_count=len(observation.event_ids),
            event_prefix_hash=self.event_prefix_hash(),
            sampled_sim_h=observation.sampled_h,
            received_sim_h=observation.received_h,
            wall_age_s=0,
        )
        validate_record("VersionedObservation", row)
        self.observation_bindings.append(row)
        return row

    def event_prefix_hash(self):
        # Exact SHA256(canonical(full event list)), computed by appending only
        # newly frozen records. No hash-chain substitution or changed wire bytes.
        require(
            len(self.world.events) >= len(self._prefix_events)
            and all(a is b for a, b in zip(self._prefix_events, self.world.events)),
            "EXECUTION_PREFIX_MUTATED",
        )
        for event in self.world.events[len(self._prefix_events) :]:
            if self._prefix_events:
                self._prefix_hasher.update(b",")
            self._prefix_hasher.update(canonical(as_data(event)))
            self._prefix_events.append(event)
        current = self._prefix_hasher.copy()
        current.update(b"]")
        return current.hexdigest()

    def bind_dispatch(self, plan, receipt, observation):
        if receipt is None or receipt.kind != "STARTED":
            return
        command = receipt.command
        self.command_bindings[command.id] = dict(
            command_id=command.id,
            command_sha256=config_digest(command),
            admitted_catalog_version=self.version,
            admitted_catalog_hash=self.versions[-1],
            observed_prefix_hash=observation["event_prefix_hash"],
            dependency_hash=digest(as_data(command)),
            state_revision=command.expected_revision,
            observation_id=observation["observation_id"],
            receipt_id=receipt.id,
        )
        # The current head was admitted and actually STARTED. Record only keys
        # adopted from the same surviving candidate, including the ID rebase.
        journal = self.policy.journal[-1] if self.policy.journal else {}
        if journal.get("selected_source") == "VERIFIED_CACHE":
            actual = as_data(command)

            def choice(value):
                return {
                    k: v
                    for k, v in value.items()
                    if k not in ("id", "issued_sim_h", "expected_revision")
                }

            for transition in self.transitions:
                if transition.get("cache_sha256") != journal.get("cache_sha256"):
                    continue
                for key, original in transition["surviving_commands"].items():
                    if choice(original) != choice(actual) or key in transition["reused_keys"]:
                        continue
                    transition["revalidated_keys"].append(key)
                    transition["reused_keys"].append(key)
                    transition["reuse_proofs"].append(
                        dict(
                            original_key=key,
                            command_id=command.id,
                            original_command_sha256=digest(original),
                            command_sha256=config_digest(command),
                            observation_id=observation["observation_id"],
                            observed_prefix_hash=observation["event_prefix_hash"],
                            catalog_version=self.version,
                            receipt_id=receipt.id,
                        )
                    )

    def scenario(self):
        # Category labels never inject hidden interventions. C0 and the frozen
        # request manifest are the complete source of initial conditions/events.
        case = self.spec["scenario"]
        if case in ("F", "C"):
            required_kind = "DEVICE_FAIL" if case == "F" else "ORDER_CANCEL"
            declared_requests = (
                self.replay_source["requests"] if self.replay_source else self.fixed_requests
            )
            require(
                any(r["kind"] == required_kind for r in declared_requests),
                "SCENARIO_FIXTURE_NOT_BOUND",
            )
        if case == "U":
            require(
                any(r["priority"] == "URGENT" for r in self.spec["initial_orders"]),
                "SCENARIO_FIXTURE_NOT_BOUND",
            )
        return Scenario(id=self.spec["scenario"], until_h=self.spec["clock"]["session_until_h"])

    def request_boundaries(self):
        replay_times = [
            t
            for key, t in (self.replay_source or {}).get("received_sim_h", {}).items()
            if key not in self.replay_received and t > self.world.s.time_h
        ]
        times = replay_times + [
            t
            for pid, t in self.material_due.items()
            if pid in self.active_products and t > self.world.s.time_h
        ]
        if self.workforce_enabled:
            for run in self.world.s.running:
                if run.status != "EXCEPTION":
                    continue
                for role in run.command.roles:
                    person = self.world.people[role.person_id]
                    human = next(h for h in self.world.s.humans if h.person_id == person.id)
                    if person.work_rate > 0:
                        contact = (
                            self.world.s.time_h
                            + max(0, self.world.config.cap - human.fatigue) / person.work_rate
                        )
                        times.append(
                            max(self.world.s.time_h, math.nextafter(contact, self.world.s.time_h))
                        )
        for key, admission in self.admissions.items():
            last = next(
                r
                for r in reversed(self.receipts)
                if r["request_id"] == key and r.get("accept_sequence") == admission["sequence"]
            )
            if last["status"] in ("ACCEPTED", "WAITING_BOUNDARY"):
                for time_h in (admission["due_h"], self.requests[key]["expires_sim_h"]):
                    if time_h > self.world.s.time_h:
                        times.append(time_h)
        return times


def submit_file(directory, request):
    """Atomic publication from GUI/CLI. A network timeout remains client UNKNOWN."""
    import uuid

    validate_request(request)
    directory = Path(directory) / "inbox"
    name = uuid.uuid4().hex
    temp = directory / (name + ".tmp")
    with temp.open("xb") as stream:
        stream.write(canonical(request))
        stream.flush()
        os.fsync(stream.fileno())
    temp.rename(directory / (name + ".json"))
    return name
