"""Resolve declared process/restore costs without executing any transition."""

from dataclasses import replace

from ..contracts.codec import ContractError, require


def resolve_process_phase(config, operation_id, mode_id, phase_id):
    """Use a validated Configuration. Restore inherits the original preparation.

    This is a static description: callers must separately check whether restore
    is needed/permitted. It neither allocates IDs nor advances work or fatigue.
    """
    try:
        operation = next(o for o in config.operations if o.id == operation_id)
        require(mode_id in operation.mode_ids, "operation/mode mismatch")
        mode = next(m for m in config.modes if m.id == mode_id)
        source_id = mode.preparation_phase_id if phase_id == "restore" else phase_id
        require(source_id is not None, "mode has no robot preparation to restore")
        source = next(p for p in mode.phases if p.id == source_id)
        duration = next(
            (
                x.base_min
                for x in operation.duration_overrides
                if x.mode_id == mode_id and x.phase_id == source_id
            ),
            source.base_min,
        )
        if phase_id == "restore":
            return replace(
                source,
                id="restore",
                predecessors=(),
                base_min=duration,
                interruption="resume",
                cancel_boundary="clear",
            )
        return replace(source, base_min=duration)
    except StopIteration as error:
        raise ContractError("unknown process phase reference") from error
