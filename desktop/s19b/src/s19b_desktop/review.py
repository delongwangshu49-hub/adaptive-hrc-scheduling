"""Display-only facts and evidence. Never imported by a planner or observation codec."""

import gzip
import hashlib
import json
import math
import time
from pathlib import Path

from .model import InputError, atomic_json, configuration_digest, read_json, validate_request


class DisplayRequestError(RuntimeError):
    """A failed display acknowledgment, not a failed production operation."""


def guarded_display(callback, record_error):
    try:
        return callback()
    except (OSError, ValueError, DisplayRequestError) as error:
        record_error(error)
        return None


EVIDENCE = (
    "request.json",
    "started.json",
    "configuration.json",
    "sources.json",
    "predeclared-online-limits.json",
    "report.json",
    "state.json",
    "audit.json",
    "decision-audit.json",
    "online-journal.json",
    "online-timing.json",
    "events.jsonl.gz",
    "decisions.jsonl.gz",
    "entity-catalog.json",
    "scene-before.png",
    "scene-after.png",
    "kit-ui-frame.png",
    "receiver-samples.json",
    "location-scene.png",
    "scene-support-diagnostic.json",
    "control-state.json",
    "start-command.json",
    "worker-claim.json",
    "reason-summary.json",
    "display-errors.json",
)
REQUIRED = EVIDENCE[:14]

EVIDENCE_LABELS = {
    "control-state.json": ("后端控制确认与最终状态", "Backend control receipts and final state"),
    "start-command.json": ("确认后的启动命令", "Confirmed start command"),
    "worker-claim.json": ("唯一后端声明", "Exclusive worker claim"),
    "request.json": ("运行前输入与请求身份", "Pre-run input and request identity"),
    "started.json": ("实际后端进程身份", "Actual backend process identity"),
    "configuration.json": ("生产配置", "Production configuration"),
    "sources.json": ("实际捕获源码摘要", "Captured source digests"),
    "predeclared-online-limits.json": ("事前在线预算", "Predeclared online budgets"),
    "report.json": ("检查点结果与关闭限制", "Checkpoint result and close limits"),
    "state.json": ("保存的生产事实", "Saved production facts"),
    "audit.json": ("独立执行审计", "Independent execution audit"),
    "decision-audit.json": ("独立决策审计", "Independent decision audit"),
    "online-journal.json": ("实际决策原因与回执", "Actual decision reasons and receipts"),
    "online-timing.json": ("原在线计时", "Original online timings"),
    "events.jsonl.gz": ("执行事件", "Execution events"),
    "decisions.jsonl.gz": ("决策记录", "Decision records"),
    "entity-catalog.json": ("只读实体映射", "Read-only entity mappings"),
    "evidence-index.json": ("保存文件完整性索引", "Saved file integrity index"),
    "process-exit.json": ("Qt实际退出回执", "Qt actual exit receipt"),
    "view-confirmation.json": ("显示相机确认", "Display camera confirmation"),
    "location-confirmation.json": ("只读定位确认", "Read-only location confirmation"),
    "scene-support-diagnostic.json": (
        "悬浮支承只读诊断（非结构证明）",
        "Read-only floating-support diagnosis (not structural proof)",
    ),
    "reason-summary.json": ("最终决策原因摘要", "Final decision reason summary"),
    "display-errors.json": ("显示请求错误记录", "Display request errors"),
}


def evidence_label(name, locale):
    pair = EVIDENCE_LABELS.get(name, ("场景/显示证据", "Scene / display evidence"))
    return name + " · " + pair[0 if locale == "zh-CN" else 1]


def sha256(path):
    with Path(path).open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256")
    return digest.hexdigest()


def safe_file(directory, name):
    if name not in (
        *EVIDENCE,
        "evidence-index.json",
        "process-exit.json",
        "live.json",
        "view-confirmation.json",
        "location-confirmation.json",
    ):
        raise InputError("EVIDENCE_PATH_REJECTED")
    root = Path(directory).resolve()
    path = root / name
    if path.resolve().parent != root:
        raise InputError("EVIDENCE_PATH_REJECTED")
    return path


def seal_evidence(directory, request):
    """Seal saved backend outputs; dynamic display messages and Qt exit are separate."""
    directory = Path(directory)
    atomic_json(
        directory / "evidence-index.json",
        dict(
            protocol="S19B-EVIDENCE-1",
            run_id=request["run_id"],
            request_id=request["request_id"],
            epoch=0,
            completeness=(
                "COMPLETE"
                if all(safe_file(directory, n).is_file() for n in REQUIRED)
                else "PARTIAL"
            ),
            files={
                name: sha256(safe_file(directory, name))
                for name in EVIDENCE
                if safe_file(directory, name).is_file()
            },
            scope="LOCAL_BYTE_INTEGRITY_NOT_SIGNED_AUTHENTICITY",
        ),
    )


def evidence_status(directory, report):
    directory = Path(directory)
    index_path = safe_file(directory, "evidence-index.json")
    if not index_path.exists():
        return "unsealed", [name for name in EVIDENCE if safe_file(directory, name).is_file()]
    index = read_json(index_path)
    if (
        index.get("protocol") != "S19B-EVIDENCE-1"
        or index.get("run_id") != report.get("run_id")
        or index.get("request_id") != report.get("request_id")
        or type(index.get("epoch")) is not int
        or index["epoch"] != 0
    ):
        raise InputError("EVIDENCE_IDENTITY_MISMATCH")
    files = index.get("files")
    if not isinstance(files, dict) or (
        not set(REQUIRED) <= files.keys() and index.get("completeness") != "PARTIAL"
    ):
        raise InputError("EVIDENCE_REQUIRED_MISSING")
    for name, digest in files.items():
        path = safe_file(directory, name)
        if not path.is_file() or sha256(path) != digest:
            raise InputError("EVIDENCE_MISSING_OR_DAMAGED:" + name)
    return (
        "partial_evidence" if not set(REQUIRED) <= files.keys() else "integrity_checked",
        ["evidence-index.json", *files],
    )


def bind_record(directory, report):
    """Check every available identity; absence in legacy records remains explicit."""
    directory = Path(directory)
    identity = (report.get("run_id"), report.get("request_id"))
    for name in ("request.json", "started.json", "process-exit.json"):
        path = safe_file(directory, name)
        if path.is_file():
            value = read_json(path)
            if not isinstance(value, dict):
                raise InputError("RECORD_SHAPE:" + name)
            if (value.get("run_id"), value.get("request_id")) != identity:
                raise InputError("RECORD_IDENTITY_MISMATCH:" + name)
            if name == "request.json":
                validate_request(value)
                if value["backend"] != report.get("backend"):
                    raise InputError("RECORD_BACKEND_MISMATCH")
    manifest = report.get("manifest", {})
    if manifest.get("run_id") and manifest["run_id"] != identity[0]:
        raise InputError("MANIFEST_IDENTITY_MISMATCH")
    if (directory / "process-exit.json").is_file():
        receipt = read_json(directory / "process-exit.json")
        if type(receipt.get("exit_code")) is not int:
            raise InputError("EXIT_RECEIPT_INVALID")
    for name, key in (("audit.json", "audit"), ("decision-audit.json", "decision_audit")):
        if manifest.get(key) and (directory / name).is_file():
            if read_json(directory / name).get("status") != manifest[key]:
                raise InputError("RECORD_AUDIT_MISMATCH:" + name)
    state_path = directory / "state.json"
    if state_path.is_file():
        state = read_json(state_path, 20_000_000)
        if not isinstance(state, dict) or not isinstance(state.get("products"), list):
            raise InputError("STATE_SHAPE")
        if manifest.get("time_h") is not None and state.get("time_h") != manifest["time_h"]:
            raise InputError("STATE_TIME_MISMATCH")
        for row in state["products"]:
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("product_id"), str)
                or any(type(row.get(k)) is not bool for k in ("released", "cancelled"))
            ):
                raise InputError("STATE_PRODUCT")
    return bool(all(identity))


def validate_binding(directory, live, backend):
    if live.get("backend") != backend:
        raise InputError("LIVE_BACKEND_MISMATCH")
    if configuration_digest(
        read_json(Path(directory) / "configuration.json", 15_000_000)
    ) != live.get("config_sha256"):
        raise InputError("LIVE_CONFIGURATION_MISMATCH")
    if sha256(Path(directory) / "sources.json") != live.get("source_version"):
        raise InputError("LIVE_SOURCE_MISMATCH")
    return live


def bind_live_bundle(directory, live, backend):
    """Worker-thread only: publish no cache until every immutable source is bound."""
    directory = Path(directory)
    paths = [directory / n for n in ("configuration.json", "sources.json", "entity-catalog.json")]
    before = [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]
    validate_binding(directory, live, backend)
    catalog = read_json(paths[2])
    if not isinstance(catalog, dict) or (
        catalog.get("run_id"),
        catalog.get("request_id"),
        catalog.get("config_sha256"),
    ) != (live["run_id"], live["request_id"], live["config_sha256"]):
        raise InputError("ENTITY_CATALOG_IDENTITY_MISMATCH")
    rows = catalog.get("entities")
    if not isinstance(rows, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in rows
    ):
        raise InputError("ENTITY_CATALOG_SHAPE")
    if before != [(p.stat().st_size, p.stat().st_mtime_ns) for p in paths]:
        raise InputError("BINDING_FILES_CHANGED")
    return rows


def display_sequence(directory, request):
    """Reconcile observed display envelopes; never submit or replay one."""
    highest = 0
    for name in ("view-request.json", "view-confirmation.json", "location-confirmation.json"):
        path = Path(directory) / name
        if path.is_file():
            value = read_json(path)
            validate_display_request(value, request, -1)
            highest = max(highest, value["sequence"])
    return highest


def data_age(live, now=None, monotonic_now=None):
    # Explicit wall-clock injection remains available for legacy records/tests.
    # Live records on this host share the OS monotonic clock across processes.
    if now is None and "published_monotonic_s" in live:
        clock = live["published_monotonic_s"]
        current = time.monotonic() if monotonic_now is None else monotonic_now
        if type(clock) not in (int, float) or not math.isfinite(clock) or not 0 <= clock <= current:
            raise InputError("LIVE_CLOCK")
        return current - clock
    clock = live.get("published_wall_s")
    now = time.time() if now is None else now
    if type(clock) not in (int, float) or not math.isfinite(clock) or clock > now + 2:
        raise InputError("LIVE_CLOCK")
    return max(0, now - clock)


def history_reason(directory):
    """Read a bounded summary, or stream legacy JSON arrays one record at a time."""
    directory = Path(directory)
    summary = directory / "reason-summary.json"
    if summary.is_file():
        value = read_json(summary)
        report = read_json(directory / "report.json")
        if (value.get("run_id"), value.get("request_id")) != (
            report.get("run_id"),
            report.get("request_id"),
        ):
            raise InputError("REASON_SUMMARY_IDENTITY")
        return value.get("reason")
    path = directory / "online-journal.json"
    if not path.is_file():
        return None
    decoder = json.JSONDecoder()
    with path.open(encoding="utf-8") as stream:
        buffer, last, started, ended, expect_value, after_comma = (
            "",
            None,
            False,
            False,
            True,
            False,
        )
        while True:
            chunk = stream.read(65536)
            buffer += chunk
            while True:
                buffer = buffer.lstrip()
                if not started:
                    if not buffer:
                        break
                    if buffer[0] != "[":
                        raise InputError("JOURNAL_SHAPE")
                    started, buffer = True, buffer[1:]
                    continue
                if ended or not buffer:
                    break
                if buffer[0] == "]":
                    if after_comma:
                        raise InputError("JOURNAL_SHAPE")
                    ended, buffer = True, buffer[1:]
                    continue
                if not expect_value:
                    if buffer[0] != ",":
                        raise InputError("JOURNAL_SHAPE")
                    expect_value, after_comma, buffer = True, True, buffer[1:]
                    continue
                try:
                    row, consumed = decoder.raw_decode(buffer)
                except ValueError:
                    break
                if not isinstance(row, dict):
                    raise InputError("JOURNAL_SHAPE")
                last, buffer, expect_value, after_comma = row, buffer[consumed:], False, False
            if len(buffer) > 20_000_000:
                raise InputError("JOURNAL_RECORD_TOO_LARGE")
            if not chunk:
                if not ended or buffer.strip():
                    raise InputError("JOURNAL_INCOMPLETE")
                return reason_fact([last]) if last is not None else None


def reason_fact(journal):
    if not journal:
        return None
    row = journal[-1]
    return dict(
        code=row.get("final_reason") or row.get("plan_reason") or "",
        operation=row.get("plan_operation"),
        time_h=row.get("time_h"),
        observation_id=row.get("observation_id"),
        sequence=row.get("sequence"),
        receipt_kind=row.get("receipt_kind"),
        receipt_id=row.get("receipt_id"),
        failures=row.get("failures", []),
        selected_source=row.get("selected_source"),
        source="online-journal.json",
    )


REASONS = {
    "DEVICE_FAILED": ("设备发生故障", "Device has failed"),
    "PATH_BLOCKED": ("运输通道被阻挡", "Transport route is blocked"),
    "MATERIAL_NOT_RELEASED": (
        "材料未到货/识别/释放",
        "Material has not arrived, been identified, or been released",
    ),
    "MATERIAL_NOT_RESERVED": ("材料尚未预留", "Material is not reserved"),
    "MATERIAL_SHORTAGE": ("可用材料不足", "Insufficient available material"),
    "QUALITY_HOLD": ("质量门尚未放行", "Quality gate has not released the work"),
    "UNKNOWN_QUALIFICATION": (
        "所需资格尚未核验通过",
        "Required qualification has not been verified",
    ),
    "DEVICE_BUSY": ("设备被占用", "Device is busy"),
    "PERSON_BUSY": ("人员被占用", "Person is busy"),
    "RESOURCE_BUSY": ("所需资源被占用", "Required resource is busy"),
    "PREPARE": ("先准备所需人员或设备位置", "Prepare the required person or device position first"),
    "NO_PENDING_OPERATION": ("没有待派工动作", "No pending operation to dispatch"),
    "PERSON_NOT_PRESENT": ("所需人员尚未到位", "Required person is not at the work location"),
    "DEVICE_NOT_AT_SOURCE": ("设备尚未到起点", "Device is not at the source location"),
    "HUMAN_CAP": ("当前人因负荷限制阻止派工", "Current human load limit prevents dispatch"),
    "KIT_INPUT_NOT_RELEASED": ("配套输入尚未释放", "Kit inputs have not been released"),
    "DECISION_BUDGET": ("决策预算已到", "Decision budget reached"),
    "PREDECESSORS": ("前置动作尚未完成", "Predecessor actions are incomplete"),
    "EDD": ("按最早交期规则选择", "Selected by earliest due date"),
    "DECISION_DEADLINE": (
        "决策预算已到，等待下一次观察",
        "Decision budget reached; await the next observation",
    ),
    "STALE_OBSERVATION": (
        "观察版本已过期，派工被拒绝",
        "Observation version expired; dispatch rejected",
    ),
    "DISPATCH_SHIELD": ("派工前核验未通过", "Pre-dispatch validation rejected the plan"),
    "DEVICE_UNAVAILABLE": ("设备当前不可用", "Device is unavailable"),
    "RULE_ERROR": ("回退规则报错，当前等待", "Fallback rule failed; currently waiting"),
    "RELEASE": ("产品尚未释放", "Product has not been released"),
    "PAUSED": ("后端报告暂停", "Backend reports paused"),
    "CANCELLED": ("后端报告取消", "Backend reports cancelled"),
    "REJECTED": ("后端拒绝此请求", "Backend rejected this request"),
}


def explain_reason(code, locale):
    """Translate known tokens only; preserve raw code and exact object association."""
    index = 0 if locale == "zh-CN" else 1
    if not code:
        return ("原因未知：后端未提供", "Reason unknown: backend supplied none")[index]
    explanations = []
    for token in code.split(";"):
        parts = token.split(":")
        known = next((part for part in parts if part in REASONS), None)
        subject = (
            parts[0] if len(parts) > 1 and parts[0] not in REASONS and parts[0] != "S19" else ""
        )
        message = (
            REASONS[known][index]
            if known
            else ("原因尚未翻译", "Reason has no reviewed translation")[index]
        )
        text = (subject + " · " if subject else "") + message
        if text not in explanations:
            explanations.append(text)
    return "\n".join(explanations)


def entity_catalog(configuration, mapping=None):
    """Exact existing USD mappings only, including related targets for operations."""
    mapping = mapping or {}
    rows = {}
    for kind, key in (
        ("product", "products"),
        ("person", "people"),
        ("device", "devices"),
        ("entity", "entities"),
        ("material", "lots"),
    ):
        for item in configuration.get(key, []):
            ident = item["id"]
            rows[ident] = dict(
                id=ident,
                kind=kind,
                targets=[ident],
                paths=[mapping[ident]] if ident in mapping else [],
            )
    for op in configuration.get("operations", []):
        targets = list(
            dict.fromkeys(x for x in (op.get("entity_id"), *op.get("equipment", [])) if x)
        )
        rows[op["id"]] = dict(
            id=op["id"],
            kind="operation",
            targets=targets,
            paths=list(dict.fromkeys(mapping[x] for x in targets if x in mapping)),
        )
    return list(rows.values())


def validate_display_request(data, request, last_sequence):
    if (
        not isinstance(data, dict)
        or data.get("run_id") != request["run_id"]
        or data.get("request_id") != request["request_id"]
        or type(data.get("epoch")) is not int
        or data["epoch"] != 0
        or type(data.get("sequence")) is not int
        or data["sequence"] <= last_sequence
    ):
        raise InputError("DISPLAY_IDENTITY_OR_SEQUENCE")
    if data.get("action") not in ("camera", "locate", "close_display"):
        raise InputError("DISPLAY_ACTION_UNSUPPORTED")
    return data


def validate_confirmation(value, pending):
    if not isinstance(value, dict):
        raise InputError("DISPLAY_CONFIRMATION_INVALID")
    for key in ("run_id", "request_id", "epoch", "sequence", "action"):
        if type(value.get(key)) is not type(pending.get(key)) or value.get(key) != pending.get(key):
            raise InputError("DISPLAY_CONFIRMATION_MISMATCH")
    for key in ("camera", "entity_id"):
        if key in pending and value.get(key) != pending[key]:
            raise InputError("DISPLAY_CONFIRMATION_MISMATCH")
    if type(value.get("accepted")) is not bool or value.get("scope") != "DISPLAY_ONLY":
        raise InputError("DISPLAY_CONFIRMATION_INVALID")
    if value["accepted"] and pending["action"] == "locate":
        paths = value.get("paths")
        if (
            not isinstance(paths, list)
            or not paths
            or any(not isinstance(p, str) or not p.startswith("/World/") for p in paths)
            or set(value.get("selected_paths", [])) != set(paths)
        ):
            raise InputError("LOCATION_READBACK_MISSING")
        for kind in ("usd", "state"):
            before, after = value.get(kind + "_before_sha256"), value.get(kind + "_after_sha256")
            if not isinstance(before, str) or len(before) != 64 or before != after:
                raise InputError("LOCATION_READBACK_MISSING")
    if value["accepted"] and pending["action"] == "camera":
        error = value.get("view_matrix_max_error")
        if type(error) not in (float, int) or not math.isfinite(error) or not 0 <= error < 1e-4:
            raise InputError("CAMERA_READBACK_MISSING")
    return value


def preview_evidence(directory, name):
    path = safe_file(directory, name)
    if name.endswith(".png"):
        return path
    if name.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            return stream.read(24_000) + "\n[preview limited to 24000 characters]"
    if path.stat().st_size > 20_000_000:
        with path.open(encoding="utf-8") as stream:
            return stream.read(24_000) + "\n[raw prefix; preview limited to 24000 characters]"
    value = read_json(path, limit=20_000_000)
    return json.dumps(value, ensure_ascii=False, indent=2)[:24_000]
