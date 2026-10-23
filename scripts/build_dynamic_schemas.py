"""Export P042 wire envelopes with original S18 records retained in history."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from adaptive_hrc_scheduling.domain import production as m  # noqa: E402
from adaptive_hrc_scheduling.dynamic_orders import production_schema  # noqa: E402


def schemas():
    result = {}
    for kind in (
        m.Configuration,
        m.DispatchCommand,
        m.PlanningObservation,
        m.ExecutionEvent,
        m.ExecutionSnapshot,
        m.Plan,
    ):
        value = production_schema(kind)
        for name, definition in value["$defs"].items():
            props = definition.get("properties", {})
            if name != kind.__name__ and "schema_version" in props:
                props["schema_version"] = {"enum": ["S18-PROD-2.0", "P042-PROD-1.0"]}
        value["$comment"] = (
            "Historical nested S18 records retain their original bytes. "
            "CatalogHistory must independently resolve each applicable view; "
            "wire shape alone does not authorize an old command at a new boundary."
        )
        result[kind.__name__] = value
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.write_text(json.dumps(schemas(), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
