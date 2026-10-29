"""Read-only bounded candidate verification subprocess; no UI or dispatch."""

import json
import sys

from adaptive_hrc_scheduling.gantt_schedule import verify


def main():
    data = json.load(sys.stdin)
    if data.pop("full_schedule", False):
        from adaptive_hrc_scheduling.full_schedule import verify_saved

        rows = verify_saved(**data)
    else:
        rows = verify(**data)
    json.dump(rows, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
