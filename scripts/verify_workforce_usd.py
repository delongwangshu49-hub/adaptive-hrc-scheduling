"""Read the saved real USD stage and correlate workforce identities/readbacks."""

import argparse
import json
import os
import sys
from pathlib import Path


def verify(directory, runtime):
    libs = next((Path(runtime) / "extscache").glob("omni.usd.libs-*"))
    sys.path.insert(0, str(libs))
    handle = os.add_dll_directory(str(libs / "bin"))
    from pxr import Usd, UsdGeom, UsdPhysics

    root = Path(directory)
    saved = json.loads((root / "session-state.json").read_text())
    spec = json.loads((root / "run-spec.json").read_text())
    stage = Usd.Stage.Open(str(root / "workforce-scene.usda"))
    if not stage:
        raise ValueError("USD_STAGE_REQUIRED")
    checks = []

    def check(value, reason):
        if not value:
            raise ValueError(reason)
        checks.append(reason)

    rows = [r for r in saved["generations"] if r.get("workforce_kind") == "PERSON_ARRIVE"]
    for g in rows:
        p = g["payload"]
        prim = stage.GetPrimAtPath(p["scene_reference"]["prim_path"])
        check(bool(prim), "NEW_PERSON_PRIM:" + g["target_id"])
        version = next(
            d["new_version"] for d in saved["deltas"] if d["commit_event_id"] == g["event_id"]
        )
        for key, expected in (
            ("sceneId", g["target_id"]),
            ("domainId", g["target_id"]),
            ("runId", spec["run_id"]),
            ("epoch", spec["epoch"]),
            ("catalogVersion", version),
            ("templateRevision", "v1"),
            ("p043Template", p["parameter_template_id"]),
        ):
            check(prim.GetAttribute("s13:" + key).Get() == expected, "USD_IDENTITY:" + key)
        pid = g["target_id"]
        flags = saved["execution"]["state"]["failed_resources"]
        state = next(
            (
                k
                for k in ("DEPARTED", "DEPARTURE_PENDING", "ABSENT_HOLD", "ABSENT")
                if "P043." + k + "." + pid in flags
            ),
            "PRESENT",
        )
        check(prim.GetAttribute("s13:p043Presence").Get() == state, "USD_FINAL_PRESENCE")
        departed = state in ("DEPARTED", "ABSENT")
        check(
            (UsdGeom.Imageable(prim).ComputeVisibility() == UsdGeom.Tokens.invisible) == departed,
            "USD_FINAL_VISIBILITY",
        )
        proxy = stage.GetPrimAtPath(str(prim.GetPath()) + "/Occupancy")
        check(
            bool(proxy)
            and bool(UsdPhysics.CollisionAPI(proxy).GetCollisionEnabledAttr().Get()) != departed,
            "USD_FINAL_COLLISION",
        )
    events = saved["execution"]["events"]
    completed = [
        e
        for e in events
        if e["kind"] == "COMPLETED"
        and e["command"]
        and any(r["person_id"] in {g["target_id"] for g in rows} for r in e["command"]["roles"])
        and not e["command"]["service"]
    ]
    check(
        bool(completed) and all(e["readback"]["source"] == "ISAAC_USD" for e in completed),
        "NEW_PERSON_REAL_PRODUCTION_COMPLETED",
    )
    resumed = [
        e for e in events if e["kind"] == "COMPLETED" and e["command"] and e["command"]["resume_of"]
    ]
    check(
        bool(resumed) and all(e["readback"]["source"] == "ISAAC_USD" for e in resumed),
        "HELD_ORIGINAL_COMMAND_ACTUAL_RECOVERY",
    )
    handle.close()
    return dict(
        status="PASS",
        identity="P043-USD-INDEPENDENT-r1",
        new_person_prims=len(rows),
        new_person_production_completions=len(completed),
        restored_completions=len(resumed),
        count=len(checks),
        checks=checks,
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", type=Path)
    p.add_argument("--runtime", default=os.environ.get("ISAAC_PATH"))
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    result = verify(a.directory, a.runtime)
    a.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))
