"""Independent journal provenance checks using saved candidates and driver commands."""

import gzip
import hashlib
import json


def plan_rows(commands):
    return [
        dict(
            operation=c["operation_id"],
            product=c["product_id"],
            attempt=c["attempt"],
            mode=c["mode_id"],
            roles=c["roles"],
            start_h=c["issued_sim_h"],
        )
        for c in commands
    ]


def candidate_sources(folder):
    captured = [
        json.loads(p.read_text(encoding="utf-8")) for p in sorted(folder.glob("candidate-*.json"))
    ]
    combined = folder / "online-candidates.json"
    if combined.exists():
        captured += [r["candidate"] for r in json.loads(combined.read_text(encoding="utf-8"))]
    result = {}
    for candidate in captured:
        sha = hashlib.sha256(
            json.dumps(candidate, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        ).hexdigest()
        result[sha] = (
            candidate["anchor_sha256"],
            plan_rows([c for step in candidate["steps"] for c in step["plan"]["commands"]]),
        )
    return result


def same_rows(actual, expected):
    # Earlier journals omitted product. Do not discard any other field, including time.
    return len(actual) == len(expected) and all(
        a == (b if "product" in a else {k: v for k, v in b.items() if k != "product"})
        for a, b in zip(actual, expected)
    )


class PlanHistory:
    def __init__(self, sources):
        self.sources = sources
        self.previous = None
        self.identity = None
        self.known = set()

    def check(self, row, state, decision):
        identity = (row["run_id"], row["epoch"])
        previous = self.previous if self.identity == identity else None
        if self.identity != identity:
            self.known = set()
        started = set(state.get("completed", [])) | {
            r["command"]["operation_id"] for r in state.get("running", [])
        }
        expected_before = (
            []
            if previous is None or previous.get("stale_dispatch_rejected")
            else [r for r in previous["after"] if r["operation"] not in started]
        )
        if not same_rows(row["before"], expected_before):
            raise ValueError("PLAN_HISTORY")
        sha = row.get("verified_candidate_sha256")
        active = row.get("cache_sha256")
        # Historical r1 only recorded a newly installed active hash.
        if sha is None and active not in self.known:
            sha = active
        if sha is not None:
            if sha not in self.sources or self.sources[sha][0] != row["observation_sha256"]:
                raise ValueError("CANDIDATE_OBSERVATION_SOURCE")
            self.known.add(sha)
        if active is not None and active not in self.known:
            raise ValueError("UNOBSERVED_CACHE_SOURCE")
        promises = row.get("commitments_after", [])
        previous_promises = previous.get("commitments_after", []) if previous else []
        if "commitments_before" in row and not same_rows(
            row["commitments_before"], previous_promises
        ):
            raise ValueError("COMMITMENT_HISTORY")
        candidate_rows = self.sources[sha][1] if sha is not None and sha == active else []
        for promise in promises:
            if not any(same_rows([promise], [old]) for old in previous_promises + candidate_rows):
                raise ValueError("COMMITMENT_PLAN_SOURCE")
        locked = {(r["operation"], r["attempt"]) for r in promises}

        def prepend(values):
            return promises + [r for r in values if (r["operation"], r["attempt"]) not in locked]

        # Every pending command must derive from a saved candidate, a continuous
        # prior plan, a protected promise, or this cycle's actual driver command.
        commands = decision["plan"]["commands"] if decision is not None else []
        source = row.get("selected_source")
        if row.get("stale_dispatch_rejected") and (
            decision is None
            or commands
            or decision["plan"].get("reason") != "S19:STALE_OBSERVATION"
        ):
            raise ValueError("STALE_DISPATCH_SOURCE")
        if source == "RULE" and promises:
            raise ValueError("RULE_BYPASSES_COMMITMENT")
        if source == "RULE":
            expected = plan_rows(commands)
        elif active is not None and sha == active:
            expected = prepend(self.sources[active][1])
        elif row.get("cache_invalidated"):
            expected = promises
        else:
            expected = prepend(expected_before)
        if row.get("plan_reason", "").startswith("S19:DISPATCH_SHIELD:"):
            if commands:
                raise ValueError("SHIELD_DISPATCH_SOURCE")
            expected = []
        if not same_rows(row["after"], expected):
            raise ValueError("PENDING_PLAN_SOURCE")
        proposal = row.get("selected_proposal")
        if commands:
            actual = plan_rows(commands)[0]
            key = (actual["operation"], actual["attempt"])
            expected_proposal = next(
                (r for r in expected if (r["operation"], r["attempt"]) == key), None
            )
            if source == "ACTUAL_RECOVERY":
                held = {
                    r["command"]["id"]
                    for r in state.get("running", [])
                    if r.get("status") == "EXCEPTION"
                }
                if commands[0].get("resume_of") not in held:
                    raise ValueError("RECOVERY_SOURCE")
                if expected_proposal is None:
                    expected_proposal = actual
            if expected_proposal is None:
                raise ValueError("DISPATCH_OUTSIDE_PLAN")
            if proposal is not None and not same_rows([proposal], [expected_proposal]):
                raise ValueError("SELECTED_PROPOSAL_SOURCE")
            if "selected_proposal" in row and proposal is None:
                raise ValueError("MISSING_SELECTED_PROPOSAL")
        elif proposal is not None:
            reason = decision["plan"].get("reason") if decision is not None else None
            if reason not in (
                "S19:STALE_OBSERVATION",
                "S19:DECISION_DEADLINE",
                "S19:PAUSED",
                "S19:CANCELLED",
            ) or not any(same_rows([proposal], [r]) for r in expected):
                raise ValueError("PROPOSAL_WITHOUT_DISPATCH")
        self.previous, self.identity = row, identity


def decision_sources(folder):
    result = {}
    with gzip.open(folder / "decisions.jsonl.gz", "rt", encoding="utf-8") as stream:
        for sequence, line in enumerate(stream):
            row = json.loads(line)
            result[(row["run_id"], row["epoch"], row["observation_id"])] = row
            result[("sequence", sequence)] = row
    return result


def decision_for(row, sources):
    if row.get("stale_dispatch_rejected"):
        decision = sources.get(("sequence", row.get("sequence")))
        if decision is not None and (
            (decision["run_id"], decision["epoch"]) != (row["run_id"], row["epoch"])
            or decision["event_count"] < row["event_count"]
            or decision["sampled_h"] < row["time_h"]
        ):
            return None
        return decision
    return sources.get((row["run_id"], row["epoch"], row["observation_id"]))


def states_at(folder, counts, initial=None):
    """Read one event state at a time, including repeated observation counts."""
    count, state = 0, initial or {}
    with gzip.open(folder / "events.jsonl.gz", "rt", encoding="utf-8") as stream:
        for target in counts:
            if type(target) is not int or target < count:
                raise ValueError("NONMONOTONE_EVENT_PREFIX")
            while count < target:
                line = stream.readline()
                if not line:
                    raise ValueError("MISSING_EVENT_PREFIX")
                state = json.loads(line)["state"]
                count += 1
            yield state
