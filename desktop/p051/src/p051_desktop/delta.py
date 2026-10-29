"""UI-only row deltas; never alter or skip production packet verification."""


class ProjectionDelta:
    def __init__(self):
        self.identity = None
        self.rows = {}

    def encode(self, view):
        envelope = view.get("envelope") or {}
        identity = envelope.get("run_id"), envelope.get("epoch")
        current = {row["row_id"]: row for row in view.get("rows", [])}
        replace = self.identity != identity
        changed = [row for key, row in current.items() if replace or self.rows.get(key) != row]
        removed = [] if replace else list(self.rows.keys() - current.keys())
        self.identity, self.rows = identity, current
        return dict(
            view, rows=changed, rows_mode="replace" if replace else "upsert", row_deletes=removed
        )
