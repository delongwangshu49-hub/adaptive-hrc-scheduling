"""S08 authorization, delayed/partial observations and nonanticipation checks."""

import unittest
from dataclasses import replace

from test_events import config_and_snapshot, process_state

from adaptive_hrc_scheduling.contracts.codec import ContractError, dumps, loads
from adaptive_hrc_scheduling.contracts.messages import HiddenScenario, PlanningInput, WorldEvent
from adaptive_hrc_scheduling.domain.models import Configuration
from adaptive_hrc_scheduling.observation import (
    ObservationGrant,
    online_order_ids,
    planning_view,
    sample_observation,
)


class ObservationTests(unittest.TestCase):
    def setUp(self):
        self.config, self.state = config_and_snapshot()
        self.grant = ObservationGrant(("J1",), (), (), (), (), (), False)

    def sample(self, state=None, grant=None, received=0.0, name="packet.one"):
        return sample_observation(
            self.config,
            state or self.state,
            grant or self.grant,
            packet_id=name,
            received_min=received,
        )

    def view(self, packets, at=0.0):
        return planning_view(
            self.config, packets, as_of_min=at, observation_id="view.one", run_id=self.state.run_id
        )

    def test_no_grant_no_worker_truth_or_execution_frame(self):
        view = self.view((self.sample(),))
        self.assertEqual(view.observation.estimates, ())
        self.assertIsNone(view.observation.execution)
        self.assertEqual(online_order_ids(view), ("J1",))
        self.assertEqual(
            loads(PlanningInput, dumps(view, config=self.config), config=self.config), view
        )

    def test_packet_not_visible_until_received(self):
        packet = self.sample(received=4.0)
        before = self.view((packet,), 3.0)
        after = self.view((packet,), 4.0)
        self.assertEqual(before.visible_configuration.orders, ())
        self.assertEqual(before.visible_configuration.operations, ())
        self.assertEqual(before.visible_configuration.materials, ())
        self.assertEqual(online_order_ids(after), ("J1",))

    def test_delayed_packet_keeps_sampled_value_not_current_truth(self):
        grant = replace(self.grant, fatigue_ids=("W1",))
        packet = self.sample(grant=grant, received=4.0)
        changed_truth = replace(
            self.state,
            sim_time_min=4.0,
            workers=(replace(self.state.workers[0], fatigue=0.7), self.state.workers[1]),
        )
        view = self.view((packet,), 4.0)
        self.assertEqual(view.observation.estimates[0].fatigue_estimate, 0.1)
        self.assertNotEqual(
            view.observation.estimates[0].fatigue_estimate, changed_truth.workers[0].fatigue
        )
        self.assertEqual(
            (view.observation.estimates[0].sampled_min, view.observation.estimates[0].received_min),
            (0.0, 4.0),
        )

    def test_each_estimate_field_requires_its_own_grant(self):
        for field, grant_field in (
            ("fatigue_estimate", "fatigue_ids"),
            ("exposure_estimate_min", "exposure_ids"),
            ("available_estimate", "availability_ids"),
        ):
            grant = replace(self.grant, **{grant_field: ("W1",)})
            estimate = self.sample(grant=grant).observation.estimates[0]
            for other in ("fatigue_estimate", "exposure_estimate_min", "available_estimate"):
                self.assertEqual(getattr(estimate, other) is not None, other == field)

    def test_execution_frame_is_explicit_partial_authorization(self):
        state = process_state(self.config, self.state)
        group = state.bindings[0].group_id
        grant = replace(self.grant, execution_group_ids=(group,))
        packet = self.sample(state, grant, received=3.0)
        frame = self.view((packet,), 3.0).observation.execution
        self.assertEqual(frame.phases, state.phases)
        self.assertEqual(frame.bindings, state.bindings)
        self.assertEqual(frame.materials, ())
        self.assertEqual((frame.sampled_min, frame.received_min), (2.0, 3.0))
        self.assertEqual(packet.observation.estimates, ())

    def test_unknown_order_never_leaks_via_execution_or_materials(self):
        state = process_state(self.config, self.state)
        grant = replace(
            self.grant,
            order_ids=(),
            execution_group_ids=(state.bindings[0].group_id,),
            material_ids=(state.materials[0].material_id,),
        )
        view = self.view((self.sample(state, grant, received=2.0),), 2.0)
        self.assertEqual(view.observation.execution.phases, ())
        self.assertEqual(view.observation.execution.preparations, ())
        self.assertEqual(view.observation.execution.materials, ())
        self.assertEqual(view.visible_configuration.orders, ())

    def test_out_of_order_delivery_cannot_undo_cancel_or_newer_estimate(self):
        old = self.sample(
            grant=replace(self.grant, fatigue_ids=("W1",)), received=5.0, name="packet.old"
        )
        current = replace(
            self.state,
            sim_time_min=2.0,
            orders=(replace(self.state.orders[0], cancelled=True),),
            workers=(replace(self.state.workers[0], fatigue=0.3), self.state.workers[1]),
        )
        new = self.sample(current, replace(self.grant, fatigue_ids=("W1",)), 2.0, "packet.new")
        result = self.view((old, new), 5.0)
        self.assertEqual(online_order_ids(result), ())
        self.assertEqual(result.observation.known_orders[0].cancel_observed_min, 2.0)
        self.assertEqual(result.observation.estimates[0].fatigue_estimate, 0.3)
        self.assertEqual(result, self.view((new, old), 5.0))

    def test_zero_time_cancel_is_sticky(self):
        cancelled = replace(self.state, orders=(replace(self.state.orders[0], cancelled=True),))
        first = self.sample(cancelled, name="packet.first")
        stale = self.sample(received=2.0, name="packet.stale")
        self.assertEqual(
            self.view((first, stale), 2.0).observation.known_orders[0].cancel_observed_min, 0.0
        )

    def test_cancel_enters_K_only_on_receipt_and_keeps_cleanup_configuration(self):
        initial = self.sample()
        state = replace(
            self.state, sim_time_min=2.0, orders=(replace(self.state.orders[0], cancelled=True),)
        )
        cancellation = self.sample(state, received=4.0, name="packet.cancel")
        self.assertEqual(online_order_ids(self.view((initial, cancellation), 3.0)), ("J1",))
        after = self.view((initial, cancellation), 4.0)
        self.assertEqual(online_order_ids(after), ())
        self.assertEqual(after.visible_configuration.orders, self.config.orders)

    def test_new_partial_frame_does_not_merge_old_locks_into_current_truth(self):
        state = process_state(self.config, self.state)
        grant = replace(self.grant, execution_group_ids=(state.bindings[0].group_id,))
        old = self.sample(state, grant, 3.0, "packet.old")
        partial = replace(
            state,
            sim_time_min=4.0,
            phases=(),
            locks=(),
            bindings=(),
            preparations=self.state.preparations,
        )
        new = self.sample(partial, grant, 4.0, "packet.new")
        frame = self.view((old, new), 4.0).observation.execution
        self.assertEqual(frame.locks, ())
        self.assertEqual(frame.sampled_min, 4.0)
        # Empty means unknown; no API returns a fabricated complete/free snapshot.

    def test_invalid_grants_times_and_cross_run_packets_rejected(self):
        for grant in (
            replace(self.grant, fatigue_ids=("R1",)),
            replace(self.grant, order_ids=("hidden.unknown",)),
            replace(self.grant, order_ids=("J1", "J1")),
        ):
            with self.assertRaises(ContractError):
                self.sample(grant=grant)
        with self.assertRaises(ContractError):
            self.sample(replace(self.state, sim_time_min=2.0), received=1.0)
        packet = self.sample()
        with self.assertRaises(ContractError):
            self.view(
                (replace(packet, observation=replace(packet.observation, run_id="other.run")),)
            )
        with self.assertRaises(ContractError):
            self.view((packet, packet))
        with self.assertRaises(ContractError):
            self.view((self.state,))

    def test_ungranted_hidden_truth_changes_do_not_change_planning_view(self):
        original = self.view((self.sample(),))
        for f in (0.0, 0.2, 0.7):
            changed = replace(
                self.state,
                workers=(
                    replace(self.state.workers[0], fatigue=f, exposure_min=10.0),
                    self.state.workers[1],
                ),
                resources=tuple(
                    replace(r, failed=True) if r.resource_id == "R1" else r
                    for r in self.state.resources
                ),
            )
            self.assertEqual(original, self.view((self.sample(changed),)))

    def test_future_scenarios_do_not_change_view_or_deterministic_proposal(self):
        packet = self.sample()
        scenarios = [
            HiddenScenario(
                "S06-1.1",
                "hidden_scenario",
                self.config.id,
                self.config.units,
                seed,
                (WorldEvent("future.event", 10.0 + seed, kind, entity, flag),),
            )
            for seed in range(5)
            for kind, entity, flag in (("cancel", "J1", None), ("failure", "CS1_M", True))
        ]

        def proposal(view):
            # A deterministic consumer witness, not a production scheduler.
            return tuple(
                o.id for o in view.visible_configuration.orders if o.id in online_order_ids(view)
            )

        baseline = self.view((packet,))
        for hidden in scenarios:
            dumps(hidden, config=self.config)
            result = self.view((packet,))  # hidden scenario is never an argument
            self.assertEqual(dumps(result, config=self.config), dumps(baseline, config=self.config))
            self.assertEqual(proposal(result), proposal(baseline))

    def test_hidden_future_orders_removed_from_projection(self):
        from test_events import FIXTURES

        config = loads(Configuration, (FIXTURES / "structural.json").read_text(encoding="utf-8"))
        view = planning_view(
            config, (), as_of_min=0.0, observation_id="empty.view", run_id="run.one"
        )
        self.assertEqual(view.visible_configuration.orders, ())
        self.assertEqual(view.visible_configuration.operations, ())
        self.assertEqual(view.visible_configuration.materials, ())
        self.assertFalse(hasattr(view, "evaluation_order_ids"))
        self.assertFalse(hasattr(view, "scenario"))

    def test_resting_worker_not_estimated_as_available(self):
        state = replace(
            self.state,
            workers=(replace(self.state.workers[0], activity="rest"), self.state.workers[1]),
        )
        packet = self.sample(state, replace(self.grant, availability_ids=("W1",)))
        self.assertIs(packet.observation.estimates[0].available_estimate, False)

    def test_hidden_order_attributes_do_not_change_visible_configuration(self):
        from test_events import FIXTURES

        from adaptive_hrc_scheduling.contracts.messages import KnownOrder, PlanningObservation
        from adaptive_hrc_scheduling.observation import ObservationPacket

        config = loads(Configuration, (FIXTURES / "structural.json").read_text(encoding="utf-8"))
        first = config.orders[0]
        observation = PlanningObservation(
            "S06-1.1",
            "planning_observation",
            "packet.one",
            "run.one",
            config.id,
            config.units,
            first.release_min,
            (KnownOrder(first.id, first.release_min, None, None, None),),
            (),
            (),
            None,
        )
        packet = ObservationPacket(first.release_min, first.release_min, observation)
        baseline = planning_view(
            config,
            (packet,),
            as_of_min=first.release_min,
            observation_id="view.one",
            run_id="run.one",
        )
        changed = replace(
            config,
            orders=tuple(
                o
                if o.id == first.id
                else replace(
                    o,
                    release_min=o.release_min + 100.0,
                    due_min=o.due_min + 500.0,
                    weight=o.weight + 10.0,
                )
                for o in config.orders
            ),
        )
        result = planning_view(
            changed,
            (packet,),
            as_of_min=first.release_min,
            observation_id="view.one",
            run_id="run.one",
        )
        self.assertEqual(baseline, result)

    def test_event_history_rejects_future_and_filters_ungranted_entities(self):
        from adaptive_hrc_scheduling.contracts.messages import ExecutionEvent

        event = ExecutionEvent(
            "S06-1.1",
            "execution_event",
            self.state.run_id,
            self.config.id,
            "observed.event",
            self.config.units,
            0.0,
            "released",
            "J1",
            None,
            "pending",
            "released",
            "external",
        )
        grant = replace(self.grant, include_event_history=True)
        packet = sample_observation(
            self.config,
            self.state,
            grant,
            packet_id="packet.events",
            received_min=0.0,
            event_history=(event,),
        )
        self.assertEqual(packet.observation.observed_event_ids, ("observed.event",))
        hidden = sample_observation(
            self.config,
            self.state,
            replace(grant, order_ids=()),
            packet_id="packet.hidden",
            received_min=0.0,
            event_history=(event,),
        )
        self.assertEqual(hidden.observation.observed_event_ids, ())
        with self.assertRaises(ContractError):
            sample_observation(
                self.config,
                self.state,
                grant,
                packet_id="packet.future",
                received_min=0.0,
                event_history=(replace(event, sim_time_min=1.0),),
            )


if __name__ == "__main__":
    unittest.main()
