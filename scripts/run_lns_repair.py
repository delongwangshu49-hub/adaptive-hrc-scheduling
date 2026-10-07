"""S17 limited repair witnesses; synthetic prefixes, not full production or Kit runs."""

import argparse
import functools
import json
import random
from dataclasses import asdict
from pathlib import Path
from time import perf_counter
from types import SimpleNamespace
from unittest.mock import patch

from build_production_contracts import Builder

from adaptive_hrc_scheduling.algorithms.lns import Options, Repair, Verification, search
from adaptive_hrc_scheduling.algorithms.production_lns import ProductionProblem, parent
from adaptive_hrc_scheduling.algorithms.static_lns import StaticProblem
from adaptive_hrc_scheduling.contracts import codec
from adaptive_hrc_scheduling.contracts.codec import ContractError
from adaptive_hrc_scheduling.control import production_loop as loop
from adaptive_hrc_scheduling.control.production_decisions import check_decisions, record
from adaptive_hrc_scheduling.planning.production import choose, planning_input
from adaptive_hrc_scheduling.production_backend import ProductionBackend
from adaptive_hrc_scheduling.production_checker import check_run
from adaptive_hrc_scheduling.reference.baselines import enumerate_independent
from adaptive_hrc_scheduling.reference.cases import tiny_cases
from adaptive_hrc_scheduling.reference.checker import check
from adaptive_hrc_scheduling.reference.domain import Alternative, Entry, Instance, Resource, Task


def write(output, name, value):
    (output / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def static_completion(output):
    instance = tiny_cases()[0]
    lock = Entry("A", "H", 1, 3)
    problem = StaticProblem(instance, {"A": "H", "B": "H"}, committed=(lock,))
    result = search(problem, Options(seed=17, iterations=4))
    assert result.status == "FEASIBLE" and result.best[0] == lock
    assert check(instance, result.best).valid
    write(
        output,
        "committed-initial.json",
        {"instance": asdict(instance), "lock": asdict(lock), "result": asdict(result)},
    )
    rng = random.Random(1707)
    cases, returned = [], 0
    for index in range(64):
        tasks = tuple(
            Task(
                chr(65 + j),
                (Alternative("H", rng.choice((1, 2)), (("M", 1),)),),
                (chr(64 + j),) if j and rng.random() < 0.4 else (),
                release=rng.choice((0, 0, 1)),
            )
            for j in range(rng.choice((2, 3)))
        )
        domain = Instance("AUDIT-" + str(index), 5, tasks, (Resource("M", rng.choice((1, 2))),))
        modes = {t.id: "H" for t in tasks}
        oracle = enumerate_independent(domain)
        locks = ()
        if oracle:
            schedules = sorted(oracle, key=lambda s: tuple((e.start, e.end) for e in s))
            known = max(schedules, key=lambda s: check(domain, s).objective)
            locks = known[:1]
        candidate = search(
            StaticProblem(domain, modes, committed=locks),
            Options(seed=17, iterations=3, repair_trials=200, wall_seconds=30),
        )
        if oracle:
            assert candidate.status == "FEASIBLE" and candidate.best in oracle
            assert candidate.best[0] == locks[0]
            returned += 1
        else:
            assert candidate.best is None and candidate.status == "WAIT"
        cases.append(
            {
                "id": domain.id,
                "complete_set_count": len(oracle),
                "status": candidate.status,
                "objective": candidate.best_score,
                "commitment": asdict(locks[0]) if locks else None,
            }
        )
    assert returned == 61
    write(output, "committed-complete-sets.json", cases)
    return {
        "counterexample_completion": 3,
        "extra_complete_set_cases": 64,
        "feasible_locked_domains_returned": returned,
        "empty_domains_waiting": 64 - returned,
        "no_supplied_complete_initial": True,
        "all_checked": "PASS",
    }


def rejected_prefix(output, products):
    config = Builder(products=products).configuration()
    world = ProductionBackend(config)
    observation = world.observe()
    world.deliver()
    plan = choose(config, planning_input(config, observation, 10000))

    def reject(command):
        raise ContractError("PATH_BLOCKED")

    receipt = world.dispatch(plan.commands[0], preflight=reject)
    assert receipt.kind == "DEFERRED"
    past = record(
        SimpleNamespace(
            observation=observation, plan=plan, rejected_parents=(), receipt_id=receipt.id
        )
    )
    fresh = world.observe()
    world.deliver()
    rejected = (parent(plan),)
    problem = ProductionProblem(
        config,
        planning_input(config, fresh, 10000),
        world.snapshot(),
        decisions=(past,),
        sequence=1,
        rejected=rejected,
    )
    before = world.snapshot()
    result = search(problem, Options(seed=17, iterations=2, repair_trials=2, wall_seconds=30))
    assert result.status == "FEASIBLE" and problem.verify(result.best).valid
    assert world.snapshot() == before
    actual = world.dispatch(result.best.commands[0]) if result.best.commands else None
    decision = record(
        SimpleNamespace(
            observation=fresh,
            plan=result.best,
            rejected_parents=rejected,
            receipt_id=actual.id if actual else None,
        )
    )
    rows = (past, decision)
    if actual:
        assert actual.kind == "STARTED" and actual.command.product_id == "PRODUCT-2"
        final = world.observe()
        world.deliver()
        rows += (record(ProductionProblem._terminal(final)),)
    else:
        assert result.best.status == "WAIT"
    assert check_run(config, world.snapshot()).status == "PASS"
    assert check_decisions(config, world.snapshot(), rows).status == "PASS"
    write(
        output,
        f"rejection-{products}.json",
        {"result": asdict(result), "prefix": asdict(world.snapshot()), "decisions": rows},
    )
    return {
        "products": products,
        "plan_status": result.best.status,
        "receipt": actual.kind if actual else None,
        "selected_product": actual.command.product_id if actual else None,
        "execution_audit": "PASS",
        "decision_audit": "PASS",
        "original_prefix_unchanged_by_search": True,
    }


def short_continuation(output):
    class RejectOnce(ProductionBackend):
        rejected_once = False

        def dispatch(self, command, **kwargs):
            if not self.rejected_once:
                self.rejected_once = True

                def reject(value):
                    raise ContractError("PATH_BLOCKED")

                return super().dispatch(command, preflight=reject)
            return super().dispatch(command, **kwargs)

    config = Builder(products=2).configuration()
    world = RejectOnce(config)
    decisions, searches = [], []

    def planner(config, value, **kwargs):
        rejected = set(kwargs["excluded_operations"])
        if decisions and decisions[-1].plan.commands:
            previous = decisions[-1]
            receipt = next(
                e
                for e in reversed(world.events)
                if e.command_id == previous.plan.commands[0].id
                and e.kind in ("STARTED", "DEFERRED", "REJECTED")
            )
            previous.receipt_id = receipt.id
            if receipt.kind != "STARTED":
                # Carry the actual most recent rejection into this planning
                # query, even when the old environment's WORLD handling cleared
                # its local filter. This is observed history, not a fake fact.
                rejected.add(parent(previous.plan))
        # Deliberately use the standard fresh input before the old driver's
        # prefilter, so the adapter itself must handle observed rejected parents.
        fresh = planning_input(config, value.observation, value.budget_ms)
        problem = ProductionProblem(
            config,
            fresh,
            world.snapshot(),
            decisions=tuple(record(d) for d in decisions),
            sequence=kwargs["sequence"],
            rejected=tuple(sorted(rejected)),
        )
        result = search(problem, Options(seed=17, iterations=1, repair_trials=1, wall_seconds=30))
        assert result.status == "FEASIBLE" and problem.verify(result.best).valid
        searches.append(
            {
                "time_h": world.s.time_h,
                "rejected": tuple(sorted(rejected)),
                "result": asdict(result),
            }
        )
        decisions.append(
            SimpleNamespace(
                observation=value.observation,
                plan=result.best,
                rejected_parents=tuple(sorted(rejected)),
                receipt_id=None,
            )
        )
        return result.best

    with patch.object(loop, "choose", planner):
        result = loop.run(world, loop.Scenario(id="S17_REJECTED_CURRENT_WINDOW", until_h=1))
    assert result.audit.status == result.decision_audit.status == "PASS"
    assert result.manifest["termination"] == "WINDOW_CENSORED"
    assert any(s["rejected"] and s["result"]["best"]["commands"] for s in searches)
    write(
        output,
        "short-continuation.json",
        {
            "manifest": result.manifest,
            "searches": searches,
            "snapshot": asdict(result.snapshot),
            "decisions": [record(d) for d in result.decisions],
        },
    )
    return {
        "until_h": 1,
        "termination": result.manifest["termination"],
        "lns_calls": len(searches),
        "completed_static_operations": result.manifest["completed_static_operations"],
        "ready": result.manifest["ready"],
        "received": result.manifest["received"],
        "execution_audit": "PASS",
        "decision_audit": "PASS",
        "scope": "SHORT_CENSORED_PREFIX_NOT_FULL_CHAIN",
    }


class DimensionProblem:
    def initial(self, deadline):
        return Repair(2)

    def mutable(self, candidate):
        return ("NEXT",)

    def repair(self, candidate, removed, rng, trials, deadline):
        return Repair(1)

    def verify(self, candidate):
        return Verification(True, (2,) if candidate == 2 else (1, 1))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    began = perf_counter()
    static = static_completion(args.output)
    dimensions = search(DimensionProblem(), Options(iterations=1))
    assert dimensions.best == 2 and "OBJECTIVE_DIMENSION_CHANGED" in dimensions.history[0].reasons
    write(args.output, "dimensions.json", asdict(dimensions))
    # Annotation lookup only; all record decodes, admissions and audits execute.
    with patch.object(
        codec, "get_type_hints", functools.lru_cache(maxsize=None)(codec.get_type_hints)
    ):
        rejected = [rejected_prefix(args.output, n) for n in (1, 2)]
        continuation = short_continuation(args.output)
    summary = {
        "schema_version": "S17-REPAIR-EVIDENCE-1",
        "closed_findings": ["F1", "F2", "C1"],
        "static": static,
        "observed_rejection_prefixes": rejected,
        "short_continuation": continuation,
        "dimension_change_fallback": "PASS",
        "executor_and_checker_unmodified": True,
        "new_full_production_or_kit_run": False,
        "wall_seconds": perf_counter() - began,
    }
    write(args.output, "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
