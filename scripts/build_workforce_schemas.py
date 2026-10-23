"""Export P043 envelopes; historical nested records keep their original family."""

import argparse
import json
from pathlib import Path

from adaptive_hrc_scheduling.domain import production as m
from adaptive_hrc_scheduling.dynamic_workforce import production_schema


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
                props["schema_version"] = {
                    "enum": ["S18-PROD-2.0", "P042-PROD-1.0", "P043-PROD-1.0"]
                }
        value["$comment"] = (
            "P043 wire shape. Applicable configuration history, personnel safety and old command identity require independent semantic verification."
        )
        result[kind.__name__] = value
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    a.output.write_text(json.dumps(schemas(), indent=2) + "\n", encoding="utf-8")
