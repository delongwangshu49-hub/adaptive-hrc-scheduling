"""Lossless append transport for full-schedule progress; semantic checks stay intact."""

from copy import deepcopy

from .contracts.codec import require

FORMAT = "P051-PROGRESS-DELTA-1"
LISTS = ("intervals", "plans")
METRICS = ("activity_intervals", "presence_intervals", "availability_intervals")


def pack(packet, previous):
    """Mutate only the wire packet; retain the complete semantic source separately."""
    source = packet["source"]
    metrics = packet["workforce_statistics"]
    state = dict(source=source, metrics=metrics)
    old = previous.get("source", {})
    slim = dict(source)
    offsets = {}
    for key in LISTS:
        n = len(old.get(key, []))
        require(source[key][:n] == old.get(key, []), "PROGRESS_PREFIX_CHANGED")
        offsets[key] = n
        slim[key] = source[key][n:]
    before = old.get("command_bindings", {})
    require(
        all(source["command_bindings"].get(k) == v for k, v in before.items()),
        "PROGRESS_BINDING_CHANGED",
    )
    slim["command_bindings"] = {
        k: v for k, v in source["command_bindings"].items() if k not in before
    }
    result_metrics = dict(metrics, people={})
    metric_offsets = {}
    for pid, row in metrics["people"].items():
        prior = previous.get("metrics", {}).get("people", {}).get(pid, {})
        entry = dict(row)
        metric_offsets[pid] = {}
        for key in METRICS:
            n = len(prior.get(key, []))
            require(row[key][:n] == prior.get(key, []), "PROGRESS_METRIC_PREFIX")
            metric_offsets[pid][key] = n
            entry[key] = row[key][n:]
        result_metrics["people"][pid] = entry
    packet["source"] = slim
    packet["workforce_statistics"] = result_metrics
    packet["progress_delta"] = dict(
        format=FORMAT, offsets=offsets, metrics=metric_offsets, bindings_before=len(before)
    )
    return state


def unpack(packet, previous):
    delta = packet["progress_delta"]
    require(delta["format"] == FORMAT, "PROGRESS_FORMAT")
    old = previous.get("source", {})
    source = dict(packet["source"])
    for key in LISTS:
        require(delta["offsets"][key] == len(old.get(key, [])), "PROGRESS_OFFSET")
        source[key] = old.get(key, []) + source[key]
    bindings = old.get("command_bindings", {})
    require(
        delta["bindings_before"] == len(bindings)
        and not bindings.keys() & source["command_bindings"].keys(),
        "PROGRESS_BINDING_OFFSET",
    )
    source["command_bindings"] = dict(bindings, **source["command_bindings"])
    metrics = deepcopy(packet["workforce_statistics"])
    for pid, row in metrics["people"].items():
        prior = previous.get("metrics", {}).get("people", {}).get(pid, {})
        for key in METRICS:
            require(delta["metrics"][pid][key] == len(prior.get(key, [])), "PROGRESS_METRIC_OFFSET")
            row[key] = prior.get(key, []) + row[key]
    packet["source"], packet["workforce_statistics"] = source, metrics
    return dict(source=source, metrics=metrics)
