"""Publish the RP05 MOVE replacement arithmetic without claiming measured times."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]

from build_production_contracts import Builder  # noqa: E402

from adaptive_hrc_scheduling.contracts.production import digest  # noqa: E402


def document():
    variants = {}
    for variant in ("SR-W1", "SR-W2"):
        config = Builder(variant=variant, rework=True).configuration()
        operations = {op.id: op for op in config.operations}
        routes = {route.id: route for route in config.routes}
        rows = []
        for activity in config.core_activities:
            if activity.move is None:
                continue
            binding = next(b for b in config.bindings if b.activity_id == activity.id)
            mode = next(m for m in activity.modes if m.id == binding.mode_id)
            old = sum(unit.base_h for unit in mode.units)
            old_people, old_equipment = {}, {}
            for unit in mode.units:
                for role in unit.roles:
                    old_people[role.id] = old_people.get(role.id, 0) + unit.base_h
                for device in unit.equipment:
                    old_equipment[device] = old_equipment.get(device, 0) + unit.base_h
            new_people, new_equipment, legs = {}, {}, []
            for ident in binding.operation_ids:
                op = operations[ident]
                route = routes[op.route_id]
                horizontal = sum(
                    abs(b.x - a.x) + abs(b.y - a.y) for a, b in zip(route.points, route.points[1:])
                )
                vertical = sum(abs(b.z - a.z) for a, b in zip(route.points, route.points[1:]))
                travel = horizontal / route.speed_m_s / 3600
                travel += vertical / route.vertical_speed_m_s / 3600
                handling = config.setup_h + config.load_h + config.unload_h
                duration = op.base_h + travel + handling
                # Core MOVE has no fatigue multiplier; other work is outside this table.
                assert op.kappa == 0 and op.base_h == 0 and op.action == "TRANSFER"
                for role in op.roles:
                    new_people[role.id] = new_people.get(role.id, 0) + duration
                for device in op.equipment:
                    new_equipment[device] = new_equipment.get(device, 0) + duration
                legs.append(
                    dict(
                        operation=ident,
                        source=op.location,
                        target=op.target,
                        entity=op.entity_id,
                        horizontal_m=horizontal,
                        vertical_m=vertical,
                        travel_h=travel,
                        handling_h=handling,
                        total_h=duration,
                        people=[r.id for r in op.roles],
                        equipment=list(op.equipment),
                    )
                )

            def deltas(before, after):
                return {
                    key: dict(
                        old_h=before.get(key, 0),
                        new_h=after.get(key, 0),
                        delta_h=after.get(key, 0) - before.get(key, 0),
                    )
                    for key in sorted(before.keys() | after.keys())
                }

            total = sum(leg["total_h"] for leg in legs)
            rows.append(
                dict(
                    activity=activity.code,
                    old_h=old,
                    new_h=total,
                    delta_h=total - old,
                    legs=legs,
                    people=deltas(old_people, new_people),
                    equipment=deltas(old_equipment, new_equipment),
                )
            )
        variants[variant] = dict(config_sha256=digest(config), rows=rows)
    data = dict(
        id="S15-MOVE-MAPPING-r1",
        scope="SYNTHETIC_TEST_ONLY",
        S15_complete=False,
        variants=variants,
        generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    )
    lines = [
        "# S15 MOVE 工时替换表",
        "",
        "RP05已批准的几何物流时长替换旧MOVE包时长；本表为配置算术，不是运行实测或工业能力证明。",
        "每腿时间为水平距离/0.5 m/s + 垂直距离/0.2 m/s，换算小时后加准备、装、卸各0.02 h。"
        "JOIN-IN累计三腿；本表中的MOVE κ为0。旧包时长不再叠加。",
        "动态空返、人员走行、支承重配、等待及材料配送另按实际事件计时，不包含在本表差额内。"
        "差额是同一核心搬运的主动占用变化，不能解释为总工期或总劳动节省。",
        "用 `python scripts/build_production_motion_table.py --check` 复核；完整逐腿距离、"
        "人员和设备的旧/新/差额见同名JSON。",
        "",
    ]
    for variant, item in variants.items():
        lines += [
            f"## {variant}",
            "",
            "| 活动 | 腿数 | 旧h | 新h | 差额h | 人员 | 设备 |",
            "| --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
        for row in item["rows"]:
            lines.append(
                f"| {row['activity']} | {len(row['legs'])} | {row['old_h']:.6f} | "
                f"{row['new_h']:.6f} | {row['delta_h']:+.6f} | "
                f"{', '.join(row['people'])} | {', '.join(row['equipment'])} |"
            )
        lines.append("")
    return data, "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    data, markdown = document()
    outputs = {"json": json.dumps(data, ensure_ascii=False, indent=2) + "\n", "md": markdown}
    for suffix, text in outputs.items():
        path = ROOT / f"docs/model/S15_move_mapping_r1.{suffix}"
        if args.check:
            if path.read_text(encoding="utf-8") != text:
                raise SystemExit(f"stale generated file: {path.relative_to(ROOT)}")
        else:
            path.write_text(text, encoding="utf-8")
    print("MOVE mapping: two variants verified" if args.check else "MOVE mapping generated")


if __name__ == "__main__":
    main()
