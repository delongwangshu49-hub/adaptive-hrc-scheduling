"""Read-only coverage checks, additional to independent execution-rule auditing."""


def buffer_backpressure(config, events, decisions):
    """Find a positive interval with two FG products and a third READY at OUT1.

    A contemporaneous no-command decision must explicitly cite destination
    capacity for the third product's uncompleted BUFFER operation. Merely
    counting two finished products or three receptions is insufficient.
    """
    products = {p.id for p in config.products}
    buffers = {o.product_id: o for o in config.operations if o.id.endswith(".BUFFER")}
    waits = {}
    for time_h, has_commands, reason in decisions:
        if not has_commands:
            waits.setdefault(time_h, []).append(reason)
    previous = None
    for event in events:
        if previous is not None and event.occurred_sim_h > previous.occurred_sim_h:
            state = previous.state
            positions = {p.id: p for p in state.positions if p.id in products}
            finished = {
                p.id: p.location for p in positions.values() if p.location in ("FG1", "FG2")
            }
            if len(finished) == 2 and set(finished.values()) == {"FG1", "FG2"}:
                for product in state.products:
                    pid = product.product_id
                    op = buffers.get(pid)
                    if (
                        pid in finished
                        or product.cancelled
                        or product.ready_h is None
                        or product.received_h is not None
                        or op is None
                        or op.id in state.completed
                        or pid not in positions
                        or positions[pid].location != "OUT1"
                        or positions[pid].support != "OUT1"
                        or any(r.command.operation_id == op.id for r in state.running)
                    ):
                        continue
                    reason = op.id + ":CAPACITY:" + op.target
                    if any(reason in r.split(";") for r in waits.get(previous.occurred_sim_h, ())):
                        return {
                            "start_h": previous.occurred_sim_h,
                            "end_h": event.occurred_sim_h,
                            "finished_positions": finished,
                            "blocked_product": pid,
                            "location": "OUT1",
                            "ready_h": product.ready_h,
                            "operation": op.id,
                            "decision_reason": reason,
                            "state_event_sequence": previous.sequence,
                        }
        previous = event
    return None
