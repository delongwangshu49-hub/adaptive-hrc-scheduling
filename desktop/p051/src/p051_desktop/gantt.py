"""Business names, dependencies and verified forecast read model."""

import json
import os
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

from adaptive_hrc_scheduling.contracts.session import digest, loads


def audit_separately(payload):
    """CPU audit cannot hold the projection reader or its GIL for a rollout."""
    full_schedule = payload.get("full_schedule")
    e20 = payload.get("initial", {}).get("id", "").startswith("P051-FIXED-r1:P052-E20-r1:")
    result = subprocess.run(
        [sys.executable, "-m", "p051_desktop.forecast_worker"],
        input=json.dumps(payload, ensure_ascii=False),
        text=True,
        encoding="utf-8",
        capture_output=True,
        timeout=(1800 if e20 else 240) if full_schedule else 60,
        env=dict(os.environ, PYTHONUTF8="1", PYTHONPATH=os.pathsep.join(sys.path)),
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    if result.returncode:
        raise ValueError("GANTT_AUDIT_FAILED:" + result.stderr[-1200:])
    return json.loads(result.stdout)


# Process terms are tied to the repository's core production specification.
NAMES = {
    "KIT": ("设计/材料标识放行", "Design & material release"),
    "CUT": ("钢材准备切割", "Steel preparation / cutting"),
    "MV-IN-B": ("底框料到J2", "Bottom-frame stock to J2"),
    "W-B": ("底框装夹焊装", "Bottom-frame fitting / welding"),
    "MV-B": ("底框入BUF", "Bottom frame to buffer"),
    "MV-IN-T": ("顶框料到J2", "Top-frame stock to J2"),
    "W-T": ("顶框装夹焊装", "Top-frame fitting / welding"),
    "MV-T": ("顶框入BUF", "Top frame to buffer"),
    "JOIN-IN": ("两框及立柱汇入J3", "Frames & columns to J3"),
    "W-3D": ("三维装配焊接", "3D assembly welding"),
    "Q-STR": ("结构焊缝/尺寸/堆叠接口检查", "Structure / weld / interface inspection"),
    "COAT": ("表面修补/保护处理", "Surface repair / protection"),
    "WAIT-COAT": ("表面等待及释放", "Surface wait & release"),
    "MOVE-F": ("框架到装修位", "Frame to finishing bay"),
    "FLOOR": ("水泥板基底/隔墙骨架", "Floor substrate / partition framing"),
    "MEP-E": ("干区电气/通风接口", "Electrical / ventilation interfaces"),
    "MEP-P": ("湿区给排水粗装", "Plumbing rough-in"),
    "Q-MEP": ("隐蔽前试验检查", "Pre-concealment inspection"),
    "LINING": ("保温防火/墙顶基层封板", "Insulation / fire protection / lining"),
    "Q-LIN": ("基层封板检查", "Lining inspection"),
    "WPROOF": ("湿区防水施工", "Wet-area waterproofing"),
    "WAIT-W": ("防水等待/试验许可", "Waterproofing wait / test release"),
    "TEST-SET": ("蓄水试验设置", "Ponding test setup"),
    "WAIT-TEST": ("蓄水保持", "Ponding hold"),
    "Q-POND": ("复验排水/卸载", "Retest / drainage / unloading"),
    "TILE": ("墙地饰面铺贴", "Wall & floor tiling"),
    "WAIT-TILE": ("胶粘等待与释放", "Adhesive wait & release"),
    "EXT": ("门窗/外覆层安装", "Doors / windows / cladding"),
    "Q-EXT": ("窗水密/饰面检查", "Window tightness / finish inspection"),
    "PAINT": ("基层及面涂施工", "Substrate & finish coating"),
    "WAIT-PAINT": ("涂装干燥释放", "Paint drying release"),
    "FIT": ("吊顶/柜体/洁具及MEP收尾", "Ceiling / cabinets / fixtures / MEP finish"),
    "Q-FIN": ("完整BOM及最终功能检查", "Final BOM & functional inspection"),
    "PACK": ("保护/覆盖/身份标识", "Protection / covering / identification"),
    "Q-PACK": ("包装覆盖检查", "Packaging inspection"),
    "MOVE-OUT": ("完整模块到出厂位", "Completed module to dispatch bay"),
    "READY": ("订单产品就绪门", "Order product readiness gate"),
}


def names(code):
    if code in NAMES:
        return NAMES[code]
    if code.startswith("WELD"):
        return ("焊接 · " + code, "Welding · " + code)
    if code.startswith("COAT"):
        return ("涂装 · " + code, "Coating · " + code)
    if code.startswith("MV-"):
        return ("工序转运 · " + code, "Process transfer · " + code)
    return ("工序 · " + code, "Process · " + code)


class ScheduleReader:
    def __init__(self):
        self.verified = {}
        self.pending = {}
        self.failure = None
        self.revision = 0
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="forecast-audit")

    def drain(self):
        for key, future in list(self.pending.items()):
            if future.done():
                del self.pending[key]
                try:
                    self.verified[key] = future.result()
                except Exception as error:
                    self.failure = str(error)
                self.revision += 1
        if self.failure:
            raise ValueError(self.failure)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def read(self, client):
        full = client.packet.get("full_schedule")
        if full is not None:
            return self.read_full(client, full)
        extension = client.packet.get("display_schedule")
        if extension is None:
            return []
        if extension["format"] != "P051-SCHEDULE-1":
            raise ValueError("GANTT_EXTENSION_FORMAT")
        result = []

        # Only surviving commands remain current after invalidation. A consumed
        # candidate is linked to actual STARTED facts via the verified plan journal.
        def key(c):
            return (
                c.get("operation_id"),
                c.get("attempt"),
                c.get("mode_id", c.get("mode")),
                tuple(sorted((r["role_id"], r["person_id"]) for r in c.get("roles", []))),
            )

        pending = {key(c) for c in extension["pending_commands"]}
        committed = {key(c) for c in extension["committed_commands"]}
        started = {e["command_id"]: e for e in client.consumer.events if e["kind"] == "STARTED"}
        adopted = {}
        for entry in client.packet["source"]["plans"]:
            journal = entry.get("journal") or {}
            checksum = journal.get("cache_sha256")
            if checksum and journal.get("selected_source") in ("VERIFIED_CACHE",):
                for c in entry["plan"]["commands"]:
                    if c["id"] in started:
                        adopted[(checksum, key(c))] = started[c["id"]]
        for ref in extension["candidates"]:
            checksum = ref["artifact_sha256"]
            if not re.fullmatch(r"[0-9a-f]{64}", checksum):
                raise ValueError("GANTT_ARTIFACT_PATH")
            cache_key = digest(ref)
            if cache_key not in self.verified:
                if cache_key in self.pending:
                    continue
                path = client.directory / "gantt-schedules" / (checksum + ".json")
                if path.stat().st_size > 128_000_000:
                    raise ValueError("GANTT_ARTIFACT_SIZE")
                data = loads(path.read_bytes())
                if (data["prefix"]["run_id"], data["prefix"]["epoch"]) != (
                    client.spec["run_id"],
                    client.spec["epoch"],
                ):
                    raise ValueError("GANTT_RUN_IDENTITY")
                if cache_key not in self.pending:
                    self.pending[cache_key] = self.executor.submit(
                        audit_separately,
                        dict(
                            data=data,
                            reference=ref,
                            initial=client.consumer.basis["configuration"],
                            generations=client.packet["source"]["generations"],
                            events=client.consumer.events[: ref["event_count"]],
                        ),
                    )
                continue
            active = extension["active_candidate"] == ref["candidate_sha256"]
            for saved in self.verified[cache_key]:
                row = deepcopy(saved)
                identity = key(row)
                actual = adopted.get((ref["candidate_sha256"], identity))
                row["proposal_state"] = (
                    "ADOPTED"
                    if actual
                    else (
                        "CANDIDATE"
                        if active
                        and (identity in pending or row.get("continuation_command_id") in started)
                        else "SUPERSEDED"
                    )
                )
                if active and identity in committed:
                    row["schedule_state"] = "COMMITTED"
                if actual:
                    row["actual_command_id"] = actual["command_id"]
                    row["adoption_event_id"] = actual["id"]
                row["source_start_h"] = ref["start_h"]
                row["source_end_h"] = ref["end_h"]
                row["plan_version"] = ref["candidate_sha256"][:8]
                result.append(row)
        return result

    def read_full(self, client, ref):
        key = ref["artifact_sha256"]
        if key is None:
            return []
        if key not in self.verified:
            if key not in self.pending:
                self.pending[key] = self.executor.submit(
                    audit_separately,
                    dict(
                        full_schedule=True,
                        directory=str(client.directory),
                        reference=ref,
                        initial=client.consumer.basis["configuration"],
                        events=client.consumer.events[
                            : ref.get("anchor_events", len(client.consumer.events))
                        ],
                    ),
                )
            return []
        result = []
        for checksum, plan in self.verified.items():
            if plan.get("format") != "P051-FULL-SCHEDULE-1":
                continue
            for i, r in enumerate(plan["intervals"]):
                cmd = r["command"]
                result.append(
                    dict(
                        row_id=f"full:{plan['version']}:{i}",
                        row_kind="FULL_PLAN",
                        schedule_state="PLANNED",
                        proposal_state=(
                            "RETAINED_BLOCKED" if ref.get("failure") else "CURRENT_PLAN"
                        )
                        if checksum == key
                        else "SUPERSEDED",
                        plan_id=plan["plan_id"],
                        plan_version=plan["version"],
                        start_h=r["start_h"],
                        end_h=r["end_h"],
                        command_id=r["command_id"],
                        operation_id=r["operation_id"],
                        activity_id=r["activity_id"],
                        product_id=r["product_id"],
                        roles=r["roles"],
                        mode=cmd["mode_id"],
                        attempt=cmd["attempt"],
                        equipment=cmd["service"]["operation"]["equipment"]
                        if cmd["service"]
                        else [],
                        source="INDEPENDENT_FULL_REPLAY",
                        end_status=r.get("end_status", "PLANNED"),
                    )
                )
        return result


def enrich(view, config, events):
    """Pure display mapping over validated config/events; no fabricated schedule."""
    products = {p["id"]: p for p in config["products"]}
    activities = {a["id"]: a for a in config["core_activities"]}
    operations = {o["id"]: o for o in config["operations"]}
    starts = {e["command_id"]: e for e in events if e["kind"] == "STARTED"}
    # Input is already an isolated consumer view; only add top-level display fields.
    rows = [dict(r) for r in view["rows"]]
    for r in rows:
        if r.get("row_kind") not in ("PLAN", "FACT_PREFIX", "FORECAST", "FULL_PLAN"):
            continue
        op = operations.get(r.get("operation_id"), {})
        if r.get("row_kind") == "FULL_PLAN" and op:
            r["equipment"] = list(op.get("equipment", []))
        activity = r.get("activity_id") or op.get("activity_id")
        if activity:
            r["activity_id"] = activity
        if r.get("row_kind") == "FACT_PREFIX":
            start = starts[r["command_id"]]
            running = next(
                x for x in start["state"]["running"] if x["command"]["id"] == r["command_id"]
            )
            # Frozen start-state lower bound, never presented as a guaranteed finish.
            r["dispatch_earliest_end_h"] = running["earliest_end_h"]
            r["dispatch_estimate_source"] = start["id"]
            if r.get("execution_status") == "EXCEPTION":
                hold = next(
                    (
                        e
                        for e in events
                        if e["kind"] == "EXCEPTION" and e["command_id"] == r["command_id"]
                    ),
                    None,
                )
                if hold:
                    r["hold_from_h"] = hold["occurred_sim_h"]
        if activity in activities:
            r["group_id"] = activity
        elif r.get("product_id"):
            r["group_id"] = r["product_id"] + ":services"
        else:
            r["group_id"] = "events"
        base_name = (
            names(activities[activity]["code"])
            if activity in activities
            else ("辅助作业", "Support operation")
        )
        action = op.get("phase", op.get("action", ""))
        translated = {
            "WORK": "作业",
            "DRIVE": "运输",
            "WAIT": "等待",
            "RESERVE": "资源预留",
            "ROBOT": "机器人加工",
            "LOAD": "装夹",
            "UNLOAD": "卸载",
            "CHECK": "检查",
        }.get(action, action)
        r["operation_name_zh"] = base_name[0] + (" · " + translated if translated else "")
        r["operation_name_en"] = base_name[1] + (" · " + action.title() if action else "")
        r["operation_dependencies"] = op.get("prerequisites", [])
        r["activity_dependencies"] = op.get("activity_prerequisites", [])
    groups = []
    pending = list(activities)
    order = []
    while pending:
        ready = [
            a
            for a in pending
            if all(e["source"] in order for e in config["core_edges"] if e["target"] == a)
        ]
        if not ready:
            raise ValueError("GANTT_DEPENDENCY_CYCLE")
        order.extend(ready)
        pending = [a for a in pending if a not in ready]
    for aid in order:
        a = activities[aid]
        zh, en = names(a["code"])
        groups.append(
            dict(
                id=aid,
                product_id=a["product_id"],
                order_id=products[a["product_id"]]["order_id"],
                name_zh=zh,
                name_en=en,
            )
        )
    for p in products.values():
        groups.append(
            dict(
                id=p["id"] + ":services",
                product_id=p["id"],
                order_id=p["order_id"],
                name_zh="运输与辅助作业",
                name_en="Transport & support",
            )
        )
    groups.sort(key=lambda g: list(products).index(g["product_id"]))
    return dict(
        view,
        rows=rows,
        gantt_groups=groups,
        gantt_dependencies=deepcopy(config["core_edges"]),
        gantt_format="P051-GANTT-1",
    )
