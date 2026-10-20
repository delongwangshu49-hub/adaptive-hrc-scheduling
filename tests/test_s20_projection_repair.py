"""Reject unobserved model facts, missing public samples and false method labels."""

import copy
import json
import unittest
from dataclasses import replace

from test_s20_extensions import allowance, configuration

from adaptive_hrc_scheduling.contracts.codec import ContractError, as_data
from adaptive_hrc_scheduling.control.production_decisions import record
from adaptive_hrc_scheduling.control.production_loop import Scenario, run
from adaptive_hrc_scheduling.control.research_projection import (
    ModelAnchor,
    ObservationSettings,
    ProjectedPolicy,
    ProjectionContract,
    audit_projection_history,
    audit_saved_projection,
    export_projection,
    restore_world,
)
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_backend import ProductionBackend


class ProjectionRepairTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = configuration()
        cls.results = {}
        for method in ("ADAPTIVE_JOINT", "FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE"):
            policy = ProjectedPolicy(cls.config, allowance(), end_h=1, method=method)
            result = run(ProductionBackend(cls.config), Scenario(until_h=1), joint_policy=policy)
            cls.results[method] = policy, result, tuple(record(d) for d in result.decisions)
        policy = ProjectedPolicy(
            cls.config, allowance(), end_h=1, settings=ObservationSettings(missing_probability=1)
        )
        result = run(ProductionBackend(cls.config), Scenario(until_h=1), joint_policy=policy)
        cls.missing = policy, result, tuple(record(d) for d in result.decisions)

    def saved(self, method="ADAPTIVE_JOINT"):
        p, r, rows = self.results[method]
        return p, r, rows, json.loads(json.dumps(export_projection(p)))

    def test_four_methods_and_legacy_format_require_external_contract(self):
        for method in self.results:
            p, r, rows, data = self.saved(method)
            for version in ("S20-PROJECTION-EVIDENCE-r1", "S20-PROJECTION-EVIDENCE-r2"):
                with self.subTest(method=method, version=version):
                    saved = copy.deepcopy(data)
                    saved["version"] = version
                    if version.endswith("r1"):
                        saved.pop("contract")
                    self.assertEqual(
                        audit_saved_projection(
                            self.config, r.snapshot, rows, saved, expected=p.contract
                        )["status"],
                        "PASS",
                    )
        p, r, rows, data = self.saved()
        with self.assertRaises(TypeError):
            audit_saved_projection(self.config, r.snapshot, rows, data)
        with self.assertRaisesRegex(ContractError, "TRUSTED_CONTRACT_REQUIRED"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=None)

    def test_external_world_fact_and_net_neutral_world_history_rejected(self):
        p, _, _, _ = self.saved()
        for kinds in (("FAILURE",), ("CANCEL",), ("FAILURE", "REPAIR")):
            with self.subTest(kinds=kinds):
                anchor = ModelAnchor(self.config, p.frames[0], p.settings, 0.75)
                _, prefix, rows = anchor.at(0.75)
                world = restore_world(self.config, prefix)
                for index, kind in enumerate(kinds):
                    world.apply_world(
                        m.WorldEvent(
                            f"UNDELIVERED-{index}",
                            world.run_id,
                            world.epoch,
                            0.75,
                            kind,
                            "R1",
                            "PRODUCT-1",
                            0,
                            "UNKNOWN",
                            "ML-METHOD",
                        )
                    )
                with self.assertRaisesRegex(ContractError, "UNAUTHORIZED_MODEL_EVOLUTION"):
                    anchor.problem(
                        self.config, world.observe(), world.snapshot(), decisions=rows, end_h=1
                    )

    def test_saved_prefix_injected_fact_or_state_is_rejected(self):
        p, r, rows, original = self.saved()
        anchor = p.candidate_proofs[0][0]
        for kind in ("WORLD", "STATE"):
            data = copy.deepcopy(original)
            world = restore_world(self.config, anchor.snapshot)
            if kind == "WORLD":
                world.apply_world(
                    m.WorldEvent(
                        "UNDELIVERED",
                        world.run_id,
                        world.epoch,
                        world.s.time_h,
                        "FAILURE",
                        "R1",
                        "PRODUCT-1",
                        0,
                        "UNKNOWN",
                        "ML-METHOD",
                    )
                )
            else:
                world.s = replace(world.s, failed_resources=("R1",))
            data["candidates"][0]["prefix"] = as_data(world.snapshot())
            with self.subTest(kind=kind):
                with self.assertRaisesRegex(ContractError, "UNAUTHORIZED_MODEL_EVOLUTION"):
                    audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_model_observation_digest_is_rebuilt(self):
        p, r, rows, data = self.saved()
        next(e for e in data["trace"] if "model_observation_sha256" in e)[
            "model_observation_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(ContractError, "MODEL_OBSERVATION_BINDING"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_missing_unreferenced_public_samples_are_rejected(self):
        p, r, rows = self.missing
        for remove in ("ALL", 1, -1):
            data = json.loads(json.dumps(export_projection(p)))
            if remove == "ALL":
                data["frames"] = []
            else:
                data["frames"].pop(remove)
            with self.subTest(remove=remove):
                with self.assertRaisesRegex(ContractError, "PUBLIC_SAMPLE_COVERAGE"):
                    audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_empty_zero_loss_cannot_certify_unknown_or_skip_settings_validation(self):
        p, r, rows = self.missing
        data = json.loads(json.dumps(export_projection(p)))
        data["frames"] = []
        data["settings"]["missing_probability"] = 0
        expected = ProjectionContract.create(
            self.config,
            allowance(),
            method=p.method,
            settings=ObservationSettings(),
        )
        data["contract"] = as_data(expected)
        with self.assertRaisesRegex(ContractError, "PUBLIC_SAMPLE_COVERAGE"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=expected)
        data["settings"]["period_h"] = 0
        with self.assertRaisesRegex(ContractError, "PROJECTION_SETTINGS"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=expected)

    def test_fractional_early_stop_keeps_all_expected_samples(self):
        p = ProjectedPolicy(
            self.config,
            allowance(),
            end_h=0.625,
            settings=ObservationSettings(missing_probability=1),
        )
        r = run(ProductionBackend(self.config), Scenario(until_h=0.625), joint_policy=p)
        self.assertEqual([f.ordinal for f in p.frames], [0, 1, 2])
        self.assertEqual(
            audit_projection_history(
                self.config, r.snapshot, tuple(record(d) for d in r.decisions), p
            )["status"],
            "PASS",
        )

    def test_method_relabel_and_unknown_method_rejected(self):
        p, r, rows, original = self.saved()
        for method in ("FIXED_H", "FIXED_HR", "NO_OBSERVATION_UPDATE", "UNREGISTERED"):
            data = copy.deepcopy(original)
            data["method"] = data["contract"]["method"] = method
            with self.subTest(method=method):
                with self.assertRaisesRegex(ContractError, "PROJECTION_METHOD"):
                    audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_mode_objective_and_declared_budget_bindings(self):
        p, r, rows, original = self.saved()
        for mutation, reason in (
            ("MODE", "FIXED_MODE_BINDING"),
            ("OBJECTIVE", "OBJECTIVE_BINDING"),
            ("BUDGET", "BUDGET_BINDING"),
        ):
            data = copy.deepcopy(original)
            if mutation == "MODE":
                data["candidates"][0]["fixed_mode"] = "H"
            elif mutation == "OBJECTIVE":
                data["candidates"][0]["objective"] = {
                    "weight": 0.5,
                    "horizon_h": 720,
                    "version": "D_WEIGHTED_r1",
                }
            else:
                data["budget"]["declared"]["max_calls"] += 1
            with self.subTest(mutation=mutation):
                with self.assertRaisesRegex(ContractError, reason):
                    audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)

    def test_contract_config_and_saved_contract_copy_must_match(self):
        p, r, rows, data = self.saved()
        with self.assertRaisesRegex(ContractError, "CONTRACT_CONFIG"):
            audit_saved_projection(
                self.config,
                r.snapshot,
                rows,
                data,
                expected=replace(p.contract, config_sha256="0" * 64),
            )
        data["contract"]["settings"]["delay_h"] = 1
        with self.assertRaisesRegex(ContractError, "SAVED_CONTRACT_BINDING"):
            audit_saved_projection(self.config, r.snapshot, rows, data, expected=p.contract)


if __name__ == "__main__":
    unittest.main()
