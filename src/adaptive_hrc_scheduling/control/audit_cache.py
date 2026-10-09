"""Private append-only audit checkpoints. Never substitute executor state for ledgers."""

from adaptive_hrc_scheduling.contracts.codec import _checked


def clone(value):
    if isinstance(value, dict):
        return {k: clone(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clone(v) for v in value]
    if isinstance(value, set):
        return value.copy()
    if isinstance(value, tuple):
        return tuple(clone(v) for v in value)
    # Domain dataclasses are frozen; mutable leaves are excluded at save().
    return value


class ExecutionCheckpoint:
    def __init__(self):
        self._config = self._identity = None
        self._events = ()
        self._ledger = None
        self._certified = self._report = None
        self._certified_rows = None

    def matches(self, config, snapshot):
        return (
            self._config is config
            and self._identity == (snapshot.run_id, snapshot.epoch, snapshot.config_sha256)
            and self._ledger is not None
            and len(snapshot.events) >= len(self._events)
            and all(a is b for a, b in zip(self._events, snapshot.events))
        )

    def reuse(self, config, snapshot, records=None):
        # Only the very same fully checked snapshot is a reusable result. An
        # appended event, changed header/final state or edited row requires audit.
        if (
            self._certified is not None
            and self.matches(config, snapshot)
            and snapshot == self._certified
            and (records is None or tuple(records) == self._certified_rows)
        ):
            return self._report
        return None

    def certify(self, config, snapshot, report, records=None):
        # save() already established immutable event records; do not walk the
        # entire certified history again just to establish final-state ownership.
        if (
            self.matches(config, snapshot)
            and type(snapshot.events) is tuple
            and all(
                type(getattr(snapshot, name)) in (str, int)
                for name in ("schema_version", "config_id", "config_sha256", "run_id", "epoch")
            )
            and _checked(type(snapshot.state), snapshot.state, "$ ")[1]
        ):
            self._certified, self._report = snapshot, report
            self._certified_rows = self._capture_rows(records) if records is not None else None

    def _capture_rows(self, records):
        # Private snapshots never escape without a copy. Share only an exactly
        # matching prefix, and own fresh copies of the new or changed suffix.
        saved = self._certified_rows or ()
        count = 0
        for old, new in zip(saved, records):
            if old != new:
                break
            count += 1
        return saved[:count] + tuple(clone(r) for r in records[count:])

    def interval_prefix(self, config, snapshot):
        if self._certified is None or not self.matches(config, snapshot):
            return 0
        prior = self._certified.state.intervals
        return (
            len(prior)
            if len(snapshot.state.intervals) >= len(prior)
            and all(a is b for a, b in zip(prior, snapshot.state.intervals))
            else 0
        )

    def restore(self, config, snapshot):
        if self.matches(config, snapshot):
            return len(self._events), clone(self._ledger)
        return 0, None

    def save(self, config, snapshot, ledger):
        offset = len(self._events) if self.matches(config, snapshot) else 0
        if _checked(type(config), config, "$ ")[1] and all(
            _checked(type(e), e, "$ ")[1] for e in snapshot.events[offset:]
        ):
            self._config = config
            self._identity = snapshot.run_id, snapshot.epoch, snapshot.config_sha256
            self._events = tuple(snapshot.events)
            self._ledger = clone(ledger)

    def fork(self):
        other = ExecutionCheckpoint()
        other._config, other._identity, other._events = self._config, self._identity, self._events
        # Stored ledgers are private and replaced on save; only restore exposes
        # a mutable copy. Forks may share this immutable-by-ownership checkpoint.
        other._ledger = self._ledger
        other._certified, other._report = self._certified, self._report
        return other

    def verify(self, config, snapshot):
        from adaptive_hrc_scheduling.production_checker import check_run

        return check_run(config, snapshot, checkpoint=self)


class DecisionCheckpoint(ExecutionCheckpoint):
    def __init__(self):
        super().__init__()
        self._records = ()

    def restore_rows(self, config, snapshot, records):
        offset, ledger = self.restore(config, snapshot)
        if (
            ledger is not None
            and len(records) >= len(self._records)
            and tuple(records[: len(self._records)]) == self._records
        ):
            return len(self._records), ledger
        return 0, None

    def save_rows(self, config, snapshot, records, ledger):
        self.save(config, snapshot, ledger)
        if self._config is config and self._events == snapshot.events:
            # Terminal non-dispatch observation is replaced by the next proposal.
            self._records = self._capture_rows(records[:-1])

    def fork(self):
        other = DecisionCheckpoint()
        other._config, other._identity, other._events = self._config, self._identity, self._events
        other._ledger = self._ledger
        other._records = self._records
        other._certified, other._report = self._certified, self._report
        other._certified_rows = self._certified_rows
        return other

    def verify(self, config, snapshot, records):
        from adaptive_hrc_scheduling.control.production_decisions import check_decisions

        return check_decisions(config, snapshot, records, checkpoint=self)
