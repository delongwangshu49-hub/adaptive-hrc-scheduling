"""Presence labour projection; legacy resource costs keep their original source."""

from .building_human import calendar_state
from .contracts.codec import as_data, require
from .contracts.session import digest


def project(spec, history, snapshot):
    end = snapshot.state.time_h
    rates = {r["template_id"]: r["rate_per_h"] for r in spec["cost"]["rates"]}
    arrivals = {
        r["target_id"]: r for r in history.generations if r.get("workforce_kind") == "PERSON_ARRIVE"
    }
    out = {}
    for p in history.current.people:
        arrival = arrivals.get(p.id)
        start = arrival["sim_h"] if arrival else 0
        tid = arrival["payload"]["parameter_template_id"] if arrival else p.id
        require(tid in rates, "COST_RATE_REQUIRED")
        changes = [(start, "PRESENT")]
        for e in snapshot.events:
            if e.world and e.world.entity_id == p.id and e.world.kind.startswith("PERSON_"):
                from .dynamic_workforce import status

                changes.append((e.occurred_sim_h, status(e.state, p.id)))
        presence, availability, activity = [], [], []
        for row in snapshot.state.intervals:
            if row.person_id != p.id:
                continue
            s = next(value for t, value in reversed(changes) if t <= row.start_h)
            present = s not in ("DEPARTED", "ABSENT")
            available = (
                s == "PRESENT"
                and calendar_state(p, row.start_h)[0] == "WAIT"
                and row.start_h < p.valid_until_h
            )
            # Split qualification expiry, which need not coincide with a calendar edge.
            until = min(row.end_h, p.valid_until_h)
            if present:
                presence.append([row.start_h, row.end_h])
            if present and available and until > row.start_h:
                availability.append([row.start_h, until])
            activity.append(dict(as_data(row), presence=present, availability=available))
        h = next(x for x in snapshot.state.humans if x.person_id == p.id)
        presence_h = sum(b - a for a, b in presence)
        out[p.id] = dict(
            defined_from_h=start,
            before_arrival="NOT_IN_CATALOG",
            template_id=tid,
            qualification_version=1 if arrival else 0,
            valid_until_h=p.valid_until_h,
            presence_intervals=presence,
            availability_intervals=availability,
            activity_intervals=activity,
            presence_h=presence_h,
            available_h=sum(b - a for a, b in availability),
            rate_per_h=rates[tid],
            labour_cost=presence_h * rates[tid],
            fatigue=h.fatigue,
            exposure=h.exposure,
            peak=h.peak,
            presence_exposure=sum(x["exposure"] for x in activity if x["presence"]),
        )
    return dict(
        identity="P043-PRESENCE-LABOUR-r1",
        policy_sha256=spec["cost"]["policy_sha256"],
        run_spec_sha256=digest(spec),
        common_window_h=[0, end],
        people=out,
        total_available_h=sum(v["available_h"] for v in out.values()),
        total_labour_cost=sum(v["labour_cost"] for v in out.values()),
        common_window_exposure=sum(v["exposure"] for v in out.values()),
        legacy_resource_cost_source_sha256=spec["initial_config_sha256"],
        legacy_cost_policy="UNCHANGED_FROZEN_RESOURCE_MODEL",
    )
