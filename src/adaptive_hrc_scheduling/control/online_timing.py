"""Monotonic, nested exclusive timings for S19; no simulated-time substitution."""

from collections import defaultdict
from time import perf_counter


def distribution(values):
    values = sorted(values)
    if not values:
        return dict(count=0, total_s=0.0, max_s=None, p50_s=None, p95_s=None)
    return dict(
        count=len(values),
        total_s=sum(values),
        max_s=values[-1],
        p50_s=values[(len(values) - 1) // 2],
        p95_s=values[min(len(values) - 1, int(len(values) * 0.95))],
    )


class OnlineTiming:
    def __init__(self, backend, policy):
        self.backend, self.policy = backend, policy
        self.world = getattr(backend, "world", backend)
        self.initial_event_count = len(self.world.events)
        self.stack = []
        self.samples = defaultdict(list)
        self.events = {}
        self.feedback = []
        self.delivered = set()
        self.cycle_events = ()
        self.wall_start = perf_counter()
        self.patches = []
        # The executor uses copy.copy(self) for transactional admission. Instance
        # closures bound to the original world would corrupt those transactions.
        # A per-instance subclass supplies descriptors that bind to each copy.
        self.original_world_class = type(self.world)
        self.world.__class__ = type("TimedProductionBackend", (self.original_world_class,), {})
        self.wrap_world("_event", "event_record", self.event_emitted)
        for name in ("dispatch", "advance", "apply_world", "complete", "progress", "exception"):
            self.wrap_world(name, "execution_state")
        for name in ("observe", "deliver"):
            self.wrap_world(name, "observation_delivery")
        if hasattr(backend, "port"):
            for name in ("step", "start", "preflight", "world_event", "preflight_world"):
                if hasattr(backend.port, name):
                    self.wrap(backend.port, name, "usd_kinematics_readback")
            for name in ("dispatch", "advance_to", "apply_world", "deliver", "feedback"):
                self.wrap(backend, name, "adapter_event_processing")
        begin, end, decide = policy.begin_cycle, policy.end_cycle, policy.decide

        def begin_cycle():
            self.enter("scheduler_exclusive")
            begin()

        def decide_cycle(value, *args, **kwargs):
            self.cycle_events = tuple(
                e
                for e in value.observation.event_ids
                if e not in self.delivered and e in self.events
            )
            now = perf_counter()
            for event_id in self.cycle_events:
                self.events[event_id]["observed_s"] = now - self.wall_start
            return decide(value, *args, **kwargs)

        def end_cycle(plan, receipt):
            end(plan, receipt)
            now = perf_counter()
            for event_id in self.cycle_events:
                event = self.events[event_id]
                self.feedback.append(
                    dict(
                        event_id=event_id,
                        kind=event["kind"],
                        produced_s=event["produced_s"],
                        observed_s=event["observed_s"],
                        decision_end_s=now - self.wall_start,
                        observation_latency_s=event["observed_s"] - event["produced_s"],
                        decision_latency_s=now - self.wall_start - event["produced_s"],
                    )
                )
            self.delivered.update(self.cycle_events)
            self.leave()

        for name, fn in (
            ("begin_cycle", begin_cycle),
            ("decide", decide_cycle),
            ("end_cycle", end_cycle),
        ):
            self.patches.append((policy, name, getattr(policy, name)))
            setattr(policy, name, fn)

    def enter(self, category):
        self.stack.append([category, perf_counter(), 0.0])

    def leave(self):
        category, start, children = self.stack.pop()
        elapsed = perf_counter() - start
        self.samples[category].append(max(0.0, elapsed - children))
        if self.stack:
            self.stack[-1][2] += elapsed

    def wrap(self, obj, name, category, after=None):
        original = getattr(obj, name)

        def call(*args, **kwargs):
            self.enter(category)
            try:
                result = original(*args, **kwargs)
                if after:
                    after(result)
                return result
            finally:
                self.leave()

        self.patches.append((obj, name, original))
        setattr(obj, name, call)

    def wrap_world(self, name, category, after=None):
        original = getattr(self.original_world_class, name)
        probe = self

        def call(receiver, *args, **kwargs):
            probe.enter(category)
            try:
                result = original(receiver, *args, **kwargs)
                if after:
                    after(result)
                return result
            finally:
                probe.leave()

        setattr(type(self.world), name, call)

    def event_emitted(self, event):
        self.events[event.id] = dict(kind=event.kind, produced_s=perf_counter() - self.wall_start)

    def kit_update(self, app):
        self.enter("kit_application_update")
        try:
            app.update()
        finally:
            self.leave()

    def report(self):
        return dict(
            clock="perf_counter_seconds",
            initial_event_count=self.initial_event_count,
            elapsed_s=perf_counter() - self.wall_start,
            exclusive_categories={k: distribution(v) for k, v in self.samples.items()},
            feedback_to_observation=distribution(
                [r["observation_latency_s"] for r in self.feedback]
            ),
            feedback_to_decision_end=distribution([r["decision_latency_s"] for r in self.feedback]),
            cycles=distribution(
                [r["cycle_seconds"] for r in self.policy.journal if "cycle_seconds" in r]
            ),
            unobserved_event_ids=sorted(self.events.keys() - self.delivered),
            rendering="HEADLESS_KIT_UPDATE_NOT_DISPLAY_FRAME_LATENCY"
            if hasattr(self.backend, "port")
            else "NOT_APPLICABLE_LIGHT_BACKEND",
            physics="KINEMATIC_USD_READBACK_NOT_DYNAMIC_PHYSICS_BENCHMARK",
        )

    def close(self):
        for obj, name, original in reversed(self.patches):
            setattr(obj, name, original)
        self.world.__class__ = self.original_world_class
