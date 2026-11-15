"""Read-only identities joining native display evidence and verified schedules."""

import json
import time
from pathlib import Path


def read_bound(path, launch):
    try:
        value = json.loads(Path(path).read_text("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(value, dict) or not launch:
        return None
    if (value.get("run_id"), value.get("request_id"), value.get("epoch")) != (
        launch["run_id"],
        launch["request_id"],
        0,
    ):
        return None
    return value


def display_context(directory, launch):
    if not directory or not launch:
        return dict(entities=[], selection=None, last_command=None, startup=None)
    root = Path(directory)
    catalog = read_bound(root / "p051-scene-context.json", launch)
    command = read_bound(root / "p051-view-status.json", launch)
    startup = read_bound(root / "p051-startup.json", launch)
    return dict(
        entities=(catalog or {}).get("entities", []),
        selection=(catalog or {}).get("selection"),
        sampled_sim_h=(catalog or {}).get("sampled_sim_h"),
        source_state_revision=(catalog or {}).get("source_state_revision"),
        age_s=max(0, time.monotonic() - catalog["published_monotonic_s"])
        if catalog and isinstance(catalog.get("published_monotonic_s"), (int, float))
        else None,
        last_command=command,
        startup=startup,
    )


def queue_view(directory, launch, action, data, sequence):
    from s19b_desktop.model import atomic_json

    if action not in ("locate", "focus", "camera", "camera_back", "snapshot"):
        raise ValueError("DISPLAY_ACTION_UNSUPPORTED")
    path = Path(directory) / "p051-view-inbox"
    path.mkdir(exist_ok=True)
    existing = [int(p.stem) for p in path.glob("*.json") if p.stem.isdecimal()]
    sequence = max([sequence, *existing], default=0) + 1
    value = dict(
        run_id=launch["run_id"],
        request_id=launch["request_id"],
        epoch=0,
        sequence=sequence,
        action=action,
    )
    for key in ("entity_id", "camera"):
        if key in data:
            if not isinstance(data[key], str) or len(data[key]) > 500:
                raise ValueError("DISPLAY_TARGET")
            value[key] = data[key]
    atomic_json(path / f"{sequence:012d}.json", value)
    return sequence


def snapshot_result(directory, launch, sequence):
    """Accept only the exact capture acknowledgement and its local immutable bytes."""
    import hashlib

    root = Path(directory).resolve()
    result = read_bound(root / "p051-view-results" / f"{sequence:012d}.json", launch)
    if result is None:
        return None
    if result.get("sequence") != sequence or result.get("action") != "snapshot":
        raise ValueError("SCENE_EXPORT_IDENTITY")
    if result.get("accepted") is not True:
        raise ValueError("SCENE_EXPORT_" + str(result.get("reason", "REJECTED")))
    image = (root / str(result.get("image", ""))).resolve()
    if image.parent != root or image.suffix.lower() != ".png":
        raise ValueError("SCENE_EXPORT_PATH")
    if hashlib.sha256(image.read_bytes()).hexdigest() != result.get("image_sha256"):
        raise ValueError("SCENE_EXPORT_DIGEST")
    return image, result
