"""Exact memoization for the unchanged lifecycle verifier's sealed JSON inputs.

This is intentionally confined to one invocation of the pinned, read-only
verifier. Its event dictionaries are private JSON values and are never mutated
by that verifier. It is not a general cache for mutable application objects.
The original function code and every assertion execute unchanged; only repeated
pure decoding and canonical prefix hashing reuse results within that invocation.
"""

import hashlib
import json
import time
from types import FunctionType

from adaptive_hrc_scheduling.contracts.session import canonical


class ExactAuditCache:
    def __init__(self, original, progress=None):
        self.original = original
        self.original_sha = original.__globals__["sha"]
        self.original_decode = original.__globals__["decode"]
        self.event_type = original.__globals__["m"].ExecutionEvent
        self.decoded = {}
        self.prefixes = {}
        self.progress = progress
        self.last_progress = 0.0
        self.stats = dict(decode_hits=0, decode_misses=0, prefix_calls=0, encoded_events=0)

    def report(self, phase, **extra):
        if self.progress is None:
            return
        now = time.perf_counter()
        if phase == "PREFIX" and now - self.last_progress < 10:
            return
        self.last_progress = now
        data = dict(phase=phase, monotonic_s=now, **self.stats, **extra)
        temporary = self.progress.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.progress)

    def decode(self, target, value):
        if target is not self.event_type or type(value) is not dict:
            return self.original_decode(target, value)
        key = id(value)
        cached = self.decoded.get(key)
        if cached is not None and cached[0] is value:
            self.stats["decode_hits"] += 1
            return cached[1]
        result = self.original_decode(target, value)
        self.decoded[key] = (value, result)
        self.stats["decode_misses"] += 1
        return result

    def sha(self, value):
        if not (
            type(value) is list
            and value
            and all(
                type(row) is dict
                and {"id", "sequence", "run_id", "epoch", "state", "kind"} <= row.keys()
                for row in value
            )
        ):
            return self.original_sha(value)
        key = id(value)
        entry = self.prefixes.get(key)
        if (
            entry is None
            or entry[0] is not value
            or len(value) < len(entry[1])
            or any(old is not new for old, new in zip(entry[1], value))
        ):
            entry = (value, [], hashlib.sha256(b"["))
            self.prefixes[key] = entry
        _, prior, hasher = entry
        for row in value[len(prior) :]:
            if prior:
                hasher.update(b",")
            hasher.update(canonical(row))
            prior.append(row)
            self.stats["encoded_events"] += 1
        closed = hasher.copy()
        closed.update(b"]")
        self.stats["prefix_calls"] += 1
        self.report("PREFIX", event_prefix_length=len(value))
        return closed.hexdigest()

    def verify(self, directory):
        namespace = dict(self.original.__globals__)
        namespace.update(sha=self.sha, decode=self.decode)
        adapted = FunctionType(
            self.original.__code__,
            namespace,
            self.original.__name__,
            self.original.__defaults__,
            self.original.__closure__,
        )
        assert adapted.__code__ is self.original.__code__
        self.report("STARTED_ORIGINAL_FUNCTION_CODE")
        result = adapted(directory)
        self.report("PASSED_ALL_ORIGINAL_ASSERTIONS")
        return result


def replay_client(client):
    """Validate every sealed packet; project only after the complete backlog."""
    from adaptive_hrc_scheduling.contracts.session import loads

    client.load_bindings()
    with (client.directory / "timeline.jsonl").open("rb") as stream:
        while line := stream.readline(128_000_001):
            if len(line) > 128_000_000 or not line.endswith(b"\n"):
                raise ValueError("SEALED_TIMELINE_INCOMPLETE_OR_OVERSIZE")
            packet = loads(line)
            client.consumer.consume(packet)
            client.offset = stream.tell()
            client.packet = client.consumer.materialized_packet
            for receipt in packet["receipts"]:
                client.receipts[receipt["request_id"]] = receipt
    client.load_bindings()
    client.error = None
    return client.snapshot()
