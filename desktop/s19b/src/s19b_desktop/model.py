"""Small, language-independent prototype input and read-only record contract."""

import hashlib
import json
import math
import re
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

PROTOCOL = "S19B-PROTOTYPE-1"
CAMERAS = (
    "Overview",
    "Top",
    "Supply",
    "Equipment",
    "Crossing",
    "Finished",
    "Gantry",
    "F1",
    "Fork",
    "Test",
)


class InputError(ValueError):
    pass


@dataclass(frozen=True)
class Draft:
    variant: str = "SR-W1"
    products: int = 1
    release_times: tuple[float, ...] = (0.0,)
    note: str = ""

    def validate(self):
        if self.variant not in ("SR-W1", "SR-W2"):
            raise InputError("VARIANT")
        if type(self.products) is not int or self.products not in (1, 2, 3):
            raise InputError("PRODUCT_COUNT")
        if len(self.release_times) != self.products:
            raise InputError("RELEASE_COUNT")
        if any(
            type(t) not in (int, float) or not math.isfinite(t) or not 0 <= t < 720
            for t in self.release_times
        ):
            raise InputError("RELEASE_TIME")
        if not isinstance(self.note, str) or len(self.note) > 500:
            raise InputError("NOTE_LENGTH")
        return self

    @classmethod
    def from_data(cls, data):
        if not isinstance(data, dict) or set(data) != {
            "variant",
            "products",
            "release_times",
            "note",
        }:
            raise InputError("DRAFT_FIELDS")
        if not isinstance(data["release_times"], (list, tuple)):
            raise InputError("RELEASE_COUNT")
        return cls(**{**data, "release_times": tuple(data["release_times"])}).validate()

    def data(self):
        return asdict(self.validate())


def canonical_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def read_json(path, limit=1_000_000):
    path = Path(path)
    if path.stat().st_size > limit:
        raise InputError("RECORD_TOO_LARGE")

    def pairs(rows):
        value = {}
        for key, item in rows:
            if key in value:
                raise InputError("DUPLICATE_JSON_KEY")
            value[key] = item
        return value

    def constant(_value):
        raise InputError("NONFINITE_JSON")

    deadline = time.monotonic() + 1.0
    while True:
        try:
            raw = path.read_text(encoding="utf-8")
            break
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def atomic_json(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8"
    )
    deadline = time.monotonic() + 1.0
    while True:
        try:
            temp.replace(path)
            return
        except PermissionError:
            # Windows readers/AV may briefly omit FILE_SHARE_DELETE.
            # Keep the previous complete record; never publish partial JSON.
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.005)


def validate_request(data):
    required = {
        "protocol",
        "run_id",
        "request_id",
        "backend",
        "draft",
        "created_at",
        "display_hold_s",
    }
    if (
        not isinstance(data, dict)
        or set(data) not in (required, required | {"control"})
        or data["protocol"] != PROTOCOL
    ):
        raise InputError("REQUEST_FIELDS")
    for key in ("run_id", "request_id"):
        if not isinstance(data[key], str) or not re.fullmatch(r"[a-zA-Z0-9-]{1,80}", data[key]):
            raise InputError("IDENTITY")
    if data["backend"] not in ("light", "isaac"):
        raise InputError("BACKEND")
    if type(data["display_hold_s"]) is not int or not 0 <= data["display_hold_s"] <= 600:
        raise InputError("DISPLAY_HOLD")
    if not isinstance(data["created_at"], str):
        raise InputError("CREATED_AT")
    Draft.from_data(data["draft"])
    if "control" in data:
        from .control import validate_control

        validate_control(data)
    return data


def read_history(directory):
    """Read summaries only; never execute files or rewrite historical evidence."""
    directory = Path(directory)
    report = read_json(directory / "report.json")
    if not isinstance(report, dict):
        raise InputError("REPORT_SHAPE")
    manifest = report.get("manifest") or {}
    if not isinstance(manifest, dict):
        raise InputError("REPORT_MANIFEST")
    identity = report.get("run_id") or manifest.get("run_id") or "LEGACY_ID_NOT_RECORDED"
    configuration = (
        read_json(directory / "configuration.json", limit=15_000_000)
        if (directory / "configuration.json").is_file()
        else None
    )
    if configuration is not None and not isinstance(configuration, dict):
        raise InputError("CONFIGURATION_SHAPE")
    if configuration is not None and manifest.get("config_sha256"):
        if configuration_digest(configuration) != manifest["config_sha256"]:
            raise InputError("CONFIGURATION_DIGEST_MISMATCH")
    from .review import bind_record, evidence_status

    identity_complete = bind_record(directory, report)
    integrity, evidence = evidence_status(directory, report)
    for name in ("process-exit.json", "view-confirmation.json", "location-confirmation.json"):
        if (directory / name).is_file():
            value = read_json(directory / name)
            if (value.get("run_id"), value.get("request_id")) != (
                report.get("run_id"),
                report.get("request_id"),
            ):
                # Old display acknowledgments omitted request identity; never call them confirmed.
                if integrity != "unsealed" or value.get("run_id") != report.get("run_id"):
                    raise InputError("RECORD_IDENTITY_MISMATCH:" + name)
            evidence.append(name)
    return {
        "run_id": identity,
        "report": report,
        "manifest": manifest,
        "evidence": evidence,
        "configuration": configuration,
        "integrity": integrity,
        "identity_complete": identity_complete,
        "record_sha256": hashlib.sha256((directory / "report.json").read_bytes()).hexdigest(),
    }


def configuration_digest(configuration):
    # The production codec restores declared float types before hashing.
    # Raw JSON serialization alone changes 0.0 to 0 and is not its digest.
    if configuration.get("schema_version") in ("S15-PROD-1.0", "S18-PROD-2.0"):
        source = Path(__file__).resolve().parents[4] / "src"
        if str(source) not in sys.path:
            sys.path.insert(0, str(source))
        from adaptive_hrc_scheduling.contracts.production import decode, digest, validate
        from adaptive_hrc_scheduling.domain.production import Configuration

        record = decode(Configuration, configuration)
        validate(record)
        return digest(record)
    return canonical_digest(configuration)


def validate_live(data, run_id, request_id, last_sequence):
    if (
        not isinstance(data, dict)
        or data.get("protocol") != PROTOCOL
        or data.get("run_id") != run_id
        or data.get("request_id") != request_id
        or type(data.get("epoch")) is not int
        or data.get("epoch") != 0
    ):
        raise InputError("LIVE_IDENTITY_MISMATCH")
    if type(data.get("sequence")) is not int or data["sequence"] < last_sequence:
        raise InputError("LIVE_SEQUENCE_REVERSED")
    for key in (
        "time_h",
        "published_wall_s",
        *(["published_monotonic_s"] if "published_monotonic_s" in data else []),
    ):
        if type(data.get(key)) not in (float, int) or not math.isfinite(data[key]) or data[key] < 0:
            raise InputError("LIVE_CLOCK")
    if (
        not isinstance(data.get("products"), list)
        or len(data["products"]) > 3
        or not isinstance(data.get("active"), list)
        or len(data["active"]) > 100
    ):
        raise InputError("LIVE_ROWS")
    for row in data["active"]:
        if not isinstance(row, dict) or any(
            not isinstance(row.get(k), str) for k in ("product", "operation", "status")
        ):
            raise InputError("LIVE_ACTION")
    reason = data.get("reason")
    if reason is not None:
        if (
            not isinstance(reason, dict)
            or not isinstance(reason.get("code"), str)
            or reason.get("source") != "online-journal.json"
            or type(reason.get("sequence")) is not int
            or not isinstance(reason.get("failures"), list)
            or any(not isinstance(x, str) for x in reason["failures"])
        ):
            raise InputError("LIVE_REASON")
    for row in data["products"]:
        if (
            not isinstance(row, dict)
            or not isinstance(row.get("id"), str)
            or any(
                type(row.get(k)) is not bool for k in ("released", "ready", "received", "cancelled")
            )
        ):
            raise InputError("LIVE_PRODUCT")
    return data
