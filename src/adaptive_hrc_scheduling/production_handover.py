"""Charged S18 model-stop handover and check/recovery, using existing W1/W2."""

from adaptive_hrc_scheduling.contracts.codec import require
from adaptive_hrc_scheduling.domain import production as m


def operation(config, change, ident):
    require(config.research is not None, "SIM_HANDOVER_ONLY")
    scope = next(
        (s for s in config.research.scope_bindings if s.activity_id == change.activity_id), None
    )
    require(
        scope is not None
        and change.definition_id == scope.h_definition
        and {change.outgoing, change.incoming} == {"W1", "W2"},
        "HANDOVER_SCOPE_OR_PEOPLE",
    )
    mode = next(
        mode
        for a in config.core_activities
        if a.id == scope.activity_id
        for mode in a.modes
        if mode.kind == "H"
    )
    require(change.after_unit < len(mode.units) - 1, "HANDOVER_MODEL_STOP")
    people = (
        (change.outgoing, change.incoming) if change.phase == "HANDOVER" else (change.incoming,)
    )
    return m.Operation(
        id=ident,
        product_id=scope.product_id,
        activity_id=scope.activity_id,
        action=change.phase,
        phase=change.phase,
        prerequisites=(),
        roles=tuple(m.Role(p, "WELD") for p in people),
        role_locations=tuple(m.PersonPosition(p, "J2") for p in people),
        equipment=("WELD-J2", "FIX-J2"),
        location="J2",
        target=None,
        route_id=None,
        entity_id=scope.component_id,
        material_inputs=(),
        material_outputs=(),
        scrap_quantity=0,
        base_h=0.1,
        kappa=0,
        qualification_ids=("ML-METHOD",),
        quality_gates=(),
        wait_gate=None,
        hold_device=None,
        release_device=None,
        unit_index=change.after_unit,
        production_mode="H-team" if change.phase == "HANDOVER" else "H",
        handover=change,
    )


def owner(change):
    return f"ATTEMPT:{change.activity_id}:0:v1"
