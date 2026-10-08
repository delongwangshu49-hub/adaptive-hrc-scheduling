"""Build the explicitly approved S18 simulation version from the unchanged S15 recipe."""

from dataclasses import replace

from build_production_contracts import Builder

from adaptive_hrc_scheduling.contracts.production import validate
from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.production_admission import VERSION, profile


def configuration(*, products=1, variant="SR-W1", rework=False):
    old = Builder(products=products, variant=variant, rework=rework).configuration()
    research = profile(old)
    scopes = {s.activity_id: s for s in research.scope_bindings}
    activities = []
    for a in old.core_activities:
        if a.id not in scopes:
            activities.append(a)
            continue
        modes = tuple(
            replace(
                mode,
                enabled=True,
                units=tuple(
                    replace(
                        u,
                        roles=tuple(
                            m.Role("WELDER" if mode.kind == "H" else "OPERATOR", r.qualification)
                            for r in u.roles
                        ),
                    )
                    for u in mode.units
                ),
            )
            for mode in a.modes
        )
        activities.append(replace(a, modes=modes))
    core = {a.id: a for a in activities}
    branch_ops = {o.id: o for o in old.operations if o.activity_id in scopes}
    bindings = list(old.bindings)
    operations = []
    for op in old.operations:
        if op.activity_id in scopes:
            mode = next(mode for mode in core[op.activity_id].modes if mode.kind == "H")
            u = mode.units[op.unit_index]
            scope = scopes[op.activity_id]
            op = replace(
                op,
                roles=u.roles,
                role_locations=tuple(m.PersonPosition(r.id, "J2") for r in u.roles),
                branch=m.Branch(
                    scope.h_definition,
                    "v1",
                    "v1",
                    "S18-SIM-A1",
                    scope.joint_set_id,
                    u.phase,
                    op.unit_index == 5,
                ),
                hold_resources=u.equipment if op.unit_index != 5 else (),
                release_resources=u.equipment if op.unit_index == 5 else (),
            )
        dynamic = tuple(
            dict.fromkeys(
                branch_ops[p].activity_id
                for p in op.prerequisites
                if p in branch_ops and branch_ops[p].activity_id != op.activity_id
            )
        )
        op = replace(
            op,
            prerequisites=tuple(
                p
                for p in op.prerequisites
                if p not in branch_ops or branch_ops[p].activity_id == op.activity_id
            ),
            activity_prerequisites=dynamic,
        )
        operations.append(op)
    for aid, scope in scopes.items():
        first = next(o for o in operations if o.activity_id == aid and o.unit_index == 0)
        mode = next(mode for mode in core[aid].modes if mode.kind == "HR-seq")
        prior = first.prerequisites
        for n, u in enumerate(mode.units):
            ident = aid + ".HR." + u.id
            op = replace(
                first,
                id=ident,
                prerequisites=prior,
                roles=u.roles,
                role_locations=tuple(m.PersonPosition(r.id, "J2") for r in u.roles),
                equipment=u.equipment,
                base_h=u.base_h,
                kappa=u.kappa,
                phase="SETUP" if u.phase == "SETUP" else "WORK",
                unit_index=n,
                production_mode="HR-seq",
                branch=m.Branch(
                    scope.hr_definition,
                    "v1",
                    "v1",
                    "S18-SIM-A1",
                    scope.joint_set_id,
                    u.phase,
                    n == 2,
                ),
                hold_resources=u.equipment if n != 2 else (),
                release_resources=u.equipment if n == 2 else (),
            )
            operations.append(op)
            bindings.append(m.CoreBinding(aid, mode.id, u.id, (ident,)))
            prior = (ident,)
    c = replace(
        old,
        schema_version=VERSION,
        specification="S18-PROD-SPEC-2.0",
        id=old.id.replace("S15-", "S18-SIM-"),
        purpose="SIMULATION_RESEARCH_ONLY",
        core_activities=tuple(activities),
        operations=tuple(operations),
        bindings=tuple(bindings),
        research=research,
    )
    return validate(c)


def generated():
    import json

    from adaptive_hrc_scheduling.contracts.production import TOP_LEVEL, dumps, production_schema

    result = {
        f"schemas/production_simulation/{k.__name__}.schema.json": json.dumps(
            production_schema(k, simulation=True), sort_keys=True, indent=2
        )
        + "\n"
        for k in TOP_LEVEL
    }
    for variant in ("SR-W1", "SR-W2"):
        c = configuration(variant=variant)
        result[f"examples/production_simulation/{variant}.json"] = dumps(c)
    return result


if __name__ == "__main__":
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    for name, contents in generated().items():
        target = root / name
        if args.check:
            if not target.exists() or target.read_text(encoding="utf-8") != contents:
                raise SystemExit("Simulation generated file drift: " + name)
        else:
            target.parent.mkdir(exist_ok=True, parents=True)
            target.write_text(contents, encoding="utf-8", newline="\n")
    print("S18 simulation schemas/examples " + ("verified" if args.check else "generated"))
