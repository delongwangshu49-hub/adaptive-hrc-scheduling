"""S16 equivalence proofs and independent negative checks on the declared static domain."""

import unittest
from dataclasses import asdict, replace
from decimal import Decimal
from fractions import Fraction

from adaptive_hrc_scheduling.reference.baselines import enumerate_independent, rule_schedule
from adaptive_hrc_scheduling.reference.cases import all_cases, buffer_case, tiny_cases
from adaptive_hrc_scheduling.reference.checker import check, check_hours, to_hours
from adaptive_hrc_scheduling.reference.cpsat import Options, enumerate_cp, solve
from adaptive_hrc_scheduling.reference.domain import (
    Alternative,
    Entry,
    Instance,
    Person,
    Resource,
    Task,
    digest,
    from_dict,
    quantize,
    validate,
)


class CPSATReferenceTests(unittest.TestCase):
    def test_complete_feasible_sets_equal_independent_cartesian_enumeration(self):
        for instance in tiny_cases():
            with self.subTest(instance=instance.id):
                expected = enumerate_independent(instance)
                actual, complete = enumerate_cp(instance)
                self.assertTrue(complete)
                self.assertEqual(actual, expected)
                result = solve(instance)
                optimum = min(check(instance, s).objective for s in expected)
                self.assertEqual(result.status, "OPTIMAL")
                self.assertEqual(result.objective, optimum)
                self.assertEqual(result.best_bound, optimum)
                self.assertEqual(result.relative_gap, 0)

    def test_hand_computed_objectives(self):
        # Unary: length 3; precedence: length 3; bindings share WELD_B, length 3;
        # receipt: makespan 4 + 2*(4-3) + logistics 2 = 8.
        self.assertEqual([solve(i).objective for i in tiny_cases()], [3, 3, 3, 8])

    def test_B_plus_one_buffer_and_actual_receiver_release(self):
        instance = buffer_case(2)
        result = solve(instance)
        self.assertEqual(result.status, "OPTIMAL")
        self.assertEqual(result.objective, 17)  # makespan 11 + three transport costs 2
        rows = {e.task_id: e for e in result.schedule}
        self.assertEqual([rows[f"READY{i}"].end for i in range(1, 4)], [1, 3, 5])
        self.assertGreaterEqual(rows["STORE3"].start, 9)
        self.assertEqual(solve(buffer_case(3)).objective, 15)
        # All READY records and inventory remain until actual RECEIVE completion.
        witness = tuple(
            Entry(t, a, s, e)
            for t, a, s, e in (
                ("READY1", "H", 0, 1),
                ("STORE1", "MOVE", 1, 2),
                ("RECEIVE1", "GATE", 8, 9),
                ("READY2", "H", 2, 3),
                ("STORE2", "MOVE", 3, 4),
                ("RECEIVE2", "GATE", 8, 9),
                ("READY3", "H", 4, 5),
                ("STORE3", "MOVE", 9, 10),
                ("RECEIVE3", "GATE", 10, 11),
            )
        )
        self.assertTrue(check(instance, witness).valid)
        invalid = tuple(replace(e, start=8, end=9) if e.task_id == "STORE3" else e for e in witness)
        self.assertIn("CAPACITY:FG:8", check(instance, invalid).findings)

    def test_matched_rules_share_instance_and_checker(self):
        for instance in all_cases()[:-1]:
            for rule in ("EDD", "SPT", "FASTEST_MODE"):
                with self.subTest(instance=instance.id, rule=rule):
                    result = rule_schedule(instance, rule)
                    self.assertEqual(result.status, "FEASIBLE")
                    self.assertTrue(check(instance, result.schedule).valid)
                    self.assertEqual(result.instance_sha256, solve(instance).instance_sha256)
                    self.assertGreaterEqual(result.objective, solve(instance).objective)

    def test_infeasible_capacity_has_no_incumbent_or_gap(self):
        result = solve(all_cases()[-1])
        self.assertEqual(result.status, "INFEASIBLE")
        self.assertEqual(result.termination, "PROVEN_INFEASIBLE")
        self.assertEqual(result.schedule, ())
        self.assertIsNone(result.objective)
        self.assertIsNone(result.best_bound)
        self.assertIsNone(result.relative_gap)
        self.assertEqual(rule_schedule(all_cases()[-1]).status, "NO_PLAN_FOUND")

    def test_zero_solver_budget_returns_unknown_no_fake_gap(self):
        result = solve(buffer_case(2), Options(wall_seconds=0))
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.termination, "BUDGET_OR_SOLVER_STOP")
        self.assertIsNone(result.relative_gap)
        self.assertIsNone(result.objective)
        self.assertIsNone(result.best_bound)
        self.assertEqual(result.schedule, ())

    def test_real_callback_stop_reports_feasible_not_proven_optimal(self):
        instance = tiny_cases()[2]
        result = solve(instance, Options(stop_after_solutions=1, presolve=False))
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.termination, "SOLUTION_LIMIT")
        self.assertTrue(check(instance, result.schedule).valid)
        self.assertLessEqual(result.best_bound, result.objective)
        self.assertGreaterEqual(result.relative_gap, 0)

    def test_enumeration_limit_never_claims_exhaustive(self):
        schedules, complete = enumerate_cp(tiny_cases()[0], max_solutions=1)
        self.assertEqual(len(schedules), 1)
        self.assertFalse(complete)
        with self.assertRaises(ValueError):
            enumerate_independent(buffer_case(2))

    def test_rule_budget_not_infeasible(self):
        result = rule_schedule(buffer_case(2), max_trials=1)
        self.assertEqual(result.status, "BUDGET_EXHAUSTED")
        self.assertIsNone(result.objective)

    def test_input_roundtrip_and_digest_bind_all_constraints(self):
        instance = tiny_cases()[3]
        self.assertEqual(from_dict(asdict(instance)), instance)
        self.assertEqual(digest(from_dict(asdict(instance))), digest(instance))
        self.assertNotEqual(digest(replace(instance, cost_weight=2)), digest(instance))
        with self.assertRaises(TypeError):
            from_dict({**asdict(instance), "hidden_scenario": {}})
        with self.assertRaises(ValueError):
            validate({})

    def test_integerization_exact_and_conservative_error(self):
        self.assertEqual(quantize("0.3", "0.1"), (3, "0"))
        self.assertEqual(quantize("0.31", "0.1", "lower"), (4, "9/100"))
        self.assertEqual(quantize("0.31", "0.1", "upper"), (3, "-1/100"))
        for v, tick, direction in (
            ("0.31", "0.1", "exact"),
            (1, 0, "exact"),
            (-1, 1, "exact"),
            (1, 1, "nearest"),
        ):
            with self.assertRaises(ValueError):
                quantize(v, tick, direction)

    def test_exact_hours_inverse_checked_in_same_domain(self):
        instance = replace(tiny_cases()[0], tick_h="0.1")
        result = solve(instance)
        self.assertEqual(
            check_hours(instance, to_hours(instance, result.schedule)),
            check(instance, result.schedule),
        )
        with self.assertRaises(ValueError):
            check_hours(instance, (("A", "H", "0.01", "0.21"),))

    def test_hr_and_unknown_qualification_not_relaxed(self):
        instance = tiny_cases()[0]
        for alt in (
            Alternative("HR", 1, kind="HR-seq"),
            Alternative("H", 1, roles=(("WELD", "NOBODY"),)),
        ):
            with self.assertRaises(ValueError):
                validate(replace(instance, tasks=(Task("A", (alt,)),)))

    def test_distinct_team_roles_and_person_instance_exclusivity(self):
        instance = Instance(
            "TEAM",
            3,
            (
                Task("A", (Alternative("H", 2, roles=(("W", "P1"), ("W", "P2")), kind="H-team"),)),
                Task("B", (Alternative("H", 1, roles=(("W", "P2"),)),)),
            ),
            (),
            (Person("P1", ("W",), ((0, 3),)), Person("P2", ("W",), ((0, 3),))),
        )
        result = solve(instance)
        self.assertEqual(result.objective, 3)
        illegal = (Entry("A", "H", 0, 2), Entry("B", "H", 1, 2))
        self.assertIn("CAPACITY:P2:1", check(instance, illegal).findings)
        with self.assertRaises(ValueError):
            validate(
                replace(
                    instance,
                    tasks=(Task("A", (Alternative("H", 2, roles=(("W", "P1"), ("W", "P1"))),)),),
                )
            )

    def test_independent_constraint_negative_injections(self):
        unary, precedence, binding, product = tiny_cases()
        probes = (
            (unary, (Entry("A", "H", 0, 2), Entry("B", "H", 1, 2)), "CAPACITY:CUT1"),
            (precedence, (Entry("A", "H", 1, 3), Entry("B", "H", 0, 1)), "PRECEDENCE"),
            (binding, (Entry("A", "FAST", 2, 3), Entry("B", "H", 0, 1)), "CALENDAR"),
            (
                product,
                (
                    Entry("READY", "H", 0, 1),
                    Entry("STORE", "MOVE", 1, 2),
                    Entry("RECEIVE", "GATE", 2, 3),
                ),
                "RELEASE",
            ),
            (unary, (Entry("A", "H", 0, 1), Entry("B", "H", 2, 3)), "TIME"),
            (unary, (Entry("A", "UNKNOWN", 0, 2), Entry("B", "H", 2, 3)), "ALTERNATIVE"),
            (unary, (Entry("A", "H", 0, 2),), "INCOMPLETE"),
            (unary, (Entry("A", "H", 0, 2), Entry("A", "H", 2, 4)), "TASK_ID"),
            (unary, (Entry("A", "H", 3, 5), Entry("B", "H", 0, 1)), "TIME"),
        )
        for instance, schedule, prefix in probes:
            with self.subTest(prefix=prefix):
                self.assertTrue(
                    any(f.startswith(prefix) for f in check(instance, schedule).findings)
                )

    def test_output_residency_blocks_next_READY(self):
        instance = buffer_case(3)
        witness = solve(instance).schedule
        illegal = tuple(replace(e, start=2, end=3) if e.task_id == "STORE1" else e for e in witness)
        self.assertTrue(
            any(f.startswith("CAPACITY:OUT1") for f in check(instance, illegal).findings)
        )

    def test_latest_end_hard_deadline_has_independent_negative(self):
        instance = replace(
            tiny_cases()[0], tasks=(Task("A", (Alternative("H", 2),), latest_end=1),)
        )
        self.assertEqual(solve(instance).status, "INFEASIBLE")
        self.assertIn("LATEST_END:A", check(instance, (Entry("A", "H", 0, 2),)).findings)

    def test_missing_person_calendar_proves_infeasible(self):
        instance = Instance(
            "OFF",
            2,
            (Task("A", (Alternative("H", 1, roles=(("W", "P1"),)),)),),
            (),
            (Person("P1", ("W",), ()),),
        )
        self.assertEqual(solve(instance).status, "INFEASIBLE")

    def test_capacity_two_and_demands_match_exhaustive_oracle(self):
        instance = Instance(
            "CAP2",
            3,
            (
                Task("A", (Alternative("H", 2, (("BAY", 2),)),)),
                Task("B", (Alternative("H", 1, (("BAY", 1),)),)),
            ),
            (Resource("BAY", 2),),
        )
        schedules, complete = enumerate_cp(instance)
        self.assertTrue(complete)
        self.assertEqual(schedules, enumerate_independent(instance))

    def test_ambiguous_identity_cycles_and_invalid_numbers_rejected(self):
        instance = tiny_cases()[0]
        malformed = (
            replace(instance, horizon=True),
            replace(instance, cost_weight=-1),
            replace(instance, resources=(Resource("CUT1", 0),)),
            replace(instance, tasks=(replace(instance.tasks[0], predecessors=("A",)),)),
            replace(
                instance, tasks=(replace(instance.tasks[0], alternatives=(Alternative("H", 0),)),)
            ),
        )
        for item in malformed:
            with self.assertRaises(ValueError):
                validate(item)

    def test_solver_invalid_budget_rejected_not_unknown(self):
        for options in (
            Options(wall_seconds=-1),
            Options(wall_seconds=float("nan")),
            Options(seed=-1),
            Options(stop_after_solutions=0),
        ):
            with self.assertRaises(ValueError):
                solve(tiny_cases()[0], options)
        with self.assertRaises(ValueError):
            rule_schedule(tiny_cases()[0], wall_seconds=float("nan"))

    def test_unknown_nested_person_field_rejected(self):
        data = asdict(tiny_cases()[2])
        data["people"][0]["hidden_fatigue"] = 0
        with self.assertRaises(TypeError):
            from_dict(data)


def receiver_due_instance():
    tasks, products = [], []
    from adaptive_hrc_scheduling.reference.domain import Product

    for prefix, due, output, device, person in (
        ("A_LONG", 10, "OUT1", "CR1", "P1"),
        ("Z_SHORT", 3, "OUT2", "CR2", "P2"),
    ):
        ready, store, receive = prefix + "_READY", prefix + "_STORE", prefix + "_RECEIVE"
        tasks.extend(
            (
                Task(ready, (Alternative("H", 1, ((output, 1),)),)),
                Task(
                    store,
                    (Alternative("MOVE", 1, ((device, 1),), (("MOVE", person),), kind="MOVE"),),
                    (ready,),
                ),
                Task(
                    receive,
                    (Alternative("GATE", 1, (("RECEIVER", 1),), kind="GATE"),),
                    (store,),
                    release=2,
                ),
            )
        )
        products.append(Product(prefix, ready, store, receive, output, "FG", due))
    return Instance(
        "RECEIVER_EDD",
        6,
        tuple(tasks),
        (
            Resource("OUT1"),
            Resource("OUT2"),
            Resource("FG", 2),
            Resource("RECEIVER"),
            Resource("CR1"),
            Resource("CR2"),
        ),
        (Person("P1", ("MOVE",), ((0, 6),)), Person("P2", ("MOVE",), ((0, 6),))),
        tuple(products),
    )


class S16LimitedRepairTests(unittest.TestCase):
    def test_r2_exact_grid_type_rejected_at_domain_and_decoder(self):
        for grid in (0.1, True, False, 1, Fraction(1, 10), Decimal("0.1"), None):
            with self.subTest(grid=repr(grid)):
                with self.assertRaises(ValueError):
                    validate(replace(tiny_cases()[0], tick_h=grid))
                data = asdict(tiny_cases()[0])
                data["tick_h"] = grid
                with self.assertRaises(ValueError):
                    from_dict(data)

    def test_r2_quantize_and_inverse_share_strict_grid_policy(self):
        for grid in (0.1, True, 1, None):
            with self.assertRaises(ValueError):
                quantize("0.3", grid)
        for grid in ("0.1", "1/10", "0.10"):
            instance = replace(tiny_cases()[0], tick_h=grid)
            result = solve(instance)
            self.assertEqual(
                check_hours(instance, to_hours(instance, result.schedule)),
                check(instance, result.schedule),
            )

    def test_r2_direct_person_scalar_qualification_rejected(self):
        instance = Instance(
            "QUAL",
            2,
            (Task("A", (Alternative("H", 1, roles=(("WE", "P1"),)),)),),
            (),
            (Person("P1", "WELD", ((0, 2),)),),
        )
        with self.assertRaises(ValueError):
            validate(instance)

    def test_r2_qualification_scalar_never_creates_role(self):
        instance = Instance(
            "QUAL",
            2,
            (Task("A", (Alternative("H", 1, roles=(("W", "P1"),)),)),),
            (),
            (Person("P1", ("WELD",), ((0, 2),)),),
        )
        data = asdict(instance)
        data["people"][0]["qualifications"] = "WELD"
        with self.assertRaises(ValueError):
            from_dict(data)
        with self.assertRaises(ValueError):
            validate(instance)

    def test_r2_predecessors_scalar_is_not_split_into_ids(self):
        instance = Instance(
            "PRED", 4, tuple(Task(i, (Alternative("H", 1),)) for i in ("A", "B", "C")), ()
        )
        data = asdict(instance)
        data["tasks"][2]["predecessors"] = "AB"
        with self.assertRaises(ValueError):
            from_dict(data)

    def test_r2_role_row_scalar_is_not_split_into_pair(self):
        instance = Instance(
            "ROLE", 2, (Task("A", (Alternative("H", 1),)),), (), (Person("P", ("W",), ((0, 2),)),)
        )
        data = asdict(instance)
        data["tasks"][0]["alternatives"][0]["roles"] = ["WP"]
        with self.assertRaises(ValueError):
            from_dict(data)

    def test_r2_top_level_and_record_scalar_shapes_rejected(self):
        base = asdict(tiny_cases()[0])
        for value in ("tasks", [], None):
            with self.assertRaises(ValueError):
                from_dict(value)
        for key in ("tasks", "resources", "people", "products"):
            for value in ("AB", {}, None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        from_dict({**base, key: value})
        for key in ("tasks", "resources", "people", "products"):
            with self.assertRaises(ValueError):
                from_dict({**base, key: ["AB"]})

    def test_r2_nested_windows_or_demand_rows_rejected(self):
        for path, value in (
            ("windows", "02"),
            ("windows", ["02"]),
            ("qualifications", {"W": True}),
        ):
            data = asdict(tiny_cases()[2])
            data["people"][0][path] = value
            with self.assertRaises(ValueError):
                from_dict(data)
        for key, value in (
            ("resources", "CUT1"),
            ("resources", [["CUT1"]]),
            ("roles", {"W": "P1"}),
            ("roles", [["W", "P1", "EXTRA"]]),
        ):
            data = asdict(tiny_cases()[0])
            data["tasks"][0]["alternatives"][0][key] = value
            with self.assertRaises(ValueError):
                from_dict(data)

    def test_r2_json_roundtrip_preserves_atomic_strings_and_empty_sequences(self):
        import json

        for instance in (tiny_cases()[0], receiver_due_instance()):
            decoded = from_dict(json.loads(json.dumps(asdict(instance))))
            self.assertEqual(decoded, instance)
            self.assertEqual(digest(decoded), digest(instance))

    def test_r2_edd_orders_receiver_by_product_due(self):
        instance = receiver_due_instance()
        result = rule_schedule(instance, "EDD")
        self.assertEqual(result.status, "FEASIBLE")
        self.assertEqual(result.objective, 4)
        rows = {e.task_id: e for e in result.schedule}
        self.assertEqual(rows["Z_SHORT_RECEIVE"].start, 2)
        self.assertEqual(rows["A_LONG_RECEIVE"].start, 3)
        self.assertEqual(solve(instance).objective, result.objective)

    def test_r2_due_later_than_horizon_order_is_preserved(self):
        instance = receiver_due_instance()
        instance = replace(
            instance,
            products=tuple(
                replace(p, due=20 if p.id == "A_LONG" else 10) for p in instance.products
            ),
        )
        rows = {e.task_id: e for e in rule_schedule(instance, "EDD").schedule}
        self.assertLess(rows["Z_SHORT_RECEIVE"].start, rows["A_LONG_RECEIVE"].start)

    def test_r2_due_propagation_independent_of_task_input_order(self):
        instance = receiver_due_instance()
        first = rule_schedule(instance, "EDD")
        second = rule_schedule(replace(instance, tasks=tuple(reversed(instance.tasks))), "EDD")
        self.assertEqual(
            {e.task_id: e for e in first.schedule}, {e.task_id: e for e in second.schedule}
        )

    def test_r2_edd_fastest_modes_are_distinct_and_feasible(self):
        instance = Instance(
            "MODES", 3, (Task("A", (Alternative("A_SLOW", 2), Alternative("Z_FAST", 1))),), ()
        )
        edd, fastest = rule_schedule(instance, "EDD"), rule_schedule(instance, "FASTEST_MODE")
        self.assertEqual(edd.schedule[0].alternative_id, "A_SLOW")
        self.assertEqual(fastest.schedule[0].alternative_id, "Z_FAST")
        self.assertEqual((edd.objective, fastest.objective), (2, 1))
        self.assertTrue(check(instance, edd.schedule).valid)
        self.assertTrue(check(instance, fastest.schedule).valid)

    def test_r2_named_abstract_version_bound_and_old_version_rejected(self):
        instance = tiny_cases()[0]
        self.assertEqual(getattr(instance, "layout_version", None), "S16-ABSTRACT-GRAPH-1")
        self.assertEqual(instance.schema_version, "S16-STATIC-1.1")
        for key in ("schema_version", "purpose", "layout_version"):
            data = asdict(instance)
            del data[key]
            with self.assertRaises(ValueError):
                from_dict(data)
        data = asdict(instance)
        data["layout_version"] = "S13-TARGET-R5-2"
        with self.assertRaises(ValueError):
            from_dict(data)
        data = asdict(instance)
        data["schema_version"] = "S16-STATIC-1.0"
        with self.assertRaises(ValueError):
            from_dict(data)

    def test_r2_corrected_rules_keep_same_instance_and_cost_domain(self):
        instance = receiver_due_instance()
        instance = replace(
            instance,
            tasks=tuple(
                replace(t, alternatives=tuple(replace(a, cost=2) for a in t.alternatives))
                if t.id.endswith("STORE")
                else t
                for t in instance.tasks
            ),
        )
        optimal = solve(instance)
        self.assertEqual(optimal.objective, 8)
        for rule in ("EDD", "SPT", "FASTEST_MODE"):
            result = rule_schedule(instance, rule)
            self.assertEqual(result.instance_sha256, optimal.instance_sha256)
            self.assertEqual(result.status, "FEASIBLE")
            self.assertTrue(check(instance, result.schedule).valid)
            self.assertGreaterEqual(result.objective, optimal.objective)


if __name__ == "__main__":
    unittest.main()
