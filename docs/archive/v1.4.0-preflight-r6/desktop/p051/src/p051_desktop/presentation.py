"""Portable view exports with source identity and unmodified interval lengths."""

import csv
from pathlib import Path


def selected_lanes(snapshot, data):
    rows = {r["row_id"]: r for r in snapshot.get("rows", [])}
    lanes = []
    for lane in data.get("lanes", [])[:100000]:
        known = [rows[key] for key in lane.get("row_ids", []) if key in rows]
        if known:
            lanes.append((str(lane.get("name", ""))[:250], known))
    return lanes


def interval(row):
    a = row.get("start_h", row.get("sim_h"))
    b = row.get("end_h", row.get("observed_until_h", row.get("forecast_until_h")))
    return (a, b) if isinstance(a, (int, float)) and isinstance(b, (int, float)) else None


def export_view(
    path, snapshot, data, *, language="zh", historical=False, scene_image=None, scene_meta=None
):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import (
        QColor,
        QFont,
        QImage,
        QPageLayout,
        QPageSize,
        QPainter,
        QPdfWriter,
        QPen,
    )

    path = Path(path)
    lanes = selected_lanes(snapshot, data)
    envelope = snapshot.get("envelope") or {}
    version = (snapshot.get("verified_full_schedule") or {}).get("version", "—")
    en = language == "en"
    meta = f"{'Historical / read only' if historical else 'Delivered snapshot'} | {envelope.get('run_id', '—')} | plan v{version} | t={envelope.get('sampled_sim_h', '—')} h"
    if path.suffix.lower() == ".csv":
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["source", meta])
            writer.writerow(["filter", data.get("filter_summary", "")])
            writer.writerow(
                ["name", "row_id", "state", "start_h", "end_h", "plan_version", "product_id"]
            )
            for name, rows in lanes:
                for row in rows:
                    a, b = interval(row) or ("", "")
                    writer.writerow(
                        [
                            name,
                            row["row_id"],
                            row.get("schedule_state"),
                            a,
                            b,
                            row.get("plan_version", ""),
                            row.get("product_id", ""),
                        ]
                    )
        return
    start, span = float(data.get("start", 0)), float(data.get("span", 50))
    if not (0 <= start < 1e9 and 0.002 <= span <= 1e9):
        raise ValueError("EXPORT_RANGE")
    width, height = 1600, max(520, 200 + 34 * len(lanes))
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor("#ffffff"))
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setFont(QFont("Microsoft YaHei UI", 16))
    painter.setPen(QColor("#202020"))
    painter.drawText(32, 42, "Production Workbench · " + ("Timeline" if en else "生产计划与执行"))
    painter.setFont(QFont("Microsoft YaHei UI", 10))
    painter.drawText(32, 70, meta)
    painter.drawText(32, 94, str(data.get("filter_summary", ""))[:200])
    painter.drawText(
        32,
        118,
        "Filled = actual · Outline = plan · h = simulation hours"
        if en
        else "实心＝实际执行 · 空心＝计划 · h＝模拟小时；仅导出当前显示行，不代表完整档案",
    )
    left, right, top = 385, width - 30, 150

    def x(h):
        return left + (h - start) / span * (right - left)

    for i in range(6):
        px = left + i * (right - left) / 5
        painter.setPen(QColor("#dddddd"))
        painter.drawLine(int(px), top, int(px), height - 45)
        painter.setPen(QColor("#333333"))
        painter.drawText(
            int(px) - (55 if i == 5 else 0), height - 20, f"{start + i * span / 5:.4g} h"
        )
    for i, (name, rows) in enumerate(lanes):
        y = top + i * 34
        painter.setPen(QColor("#333333"))
        painter.drawText(QRectF(32, y, left - 45, 32), Qt.TextFlag.TextWordWrap, name)
        for row in sorted(rows, key=lambda r: r.get("schedule_state") == "ACTUAL"):
            iv = interval(row)
            if not iv or iv[1] < start or iv[0] > start + span:
                continue
            a, b = max(left, x(iv[0])), min(right, x(iv[1]))
            color = QColor(row.get("color", "#786643"))
            if not color.isValid():
                color = QColor("#786643")
            painter.setPen(QPen(color, 1.5))
            painter.setBrush(
                color if row.get("schedule_state") == "ACTUAL" else Qt.BrushStyle.NoBrush
            )
            painter.drawRect(QRectF(a, y + 8, max(1, b - a), 15))
    painter.end()
    if scene_image is not None:
        scene = QImage(str(scene_image))
        if scene.isNull():
            raise ValueError("SCENE_EXPORT_IMAGE_INVALID")
        scene_meta = scene_meta or {}
        combined = QImage(width * 2, max(height, 1120), QImage.Format.Format_RGB32)
        combined.fill(QColor("#ffffff"))
        painter = QPainter(combined)
        painter.setPen(QColor("#202020"))
        painter.setFont(QFont("Microsoft YaHei UI", 16))
        painter.drawText(32, 42, "Isaac · " + ("Production scene" if en else "生产仿真场景"))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(
            32, 70, f"{scene_meta.get('run_id', '—')} | frame {scene_meta.get('frame_number', '—')}"
        )
        painter.drawText(
            32,
            94,
            f"Scene: t={scene_meta.get('sampled_sim_h', '—')} h · revision {scene_meta.get('source_state_revision', '—')}",
        )
        painter.drawText(
            32,
            118,
            "Independent capture times; simulation continued during export."
            if en
            else "场景与甘特分别标注来源时刻；导出过程未暂停生产，不宣称同帧。",
        )
        scaled = scene.scaled(
            width - 64,
            900,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        painter.drawImage(32, 150, scaled)
        painter.drawText(32, 1080, "SHA256: " + str(scene_meta.get("image_sha256", "—")))
        painter.drawImage(width, 0, image)
        painter.end()
        image = combined
        width, height = image.width(), image.height()
    if path.suffix.lower() == ".pdf":
        writer = QPdfWriter(str(path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A3))
        writer.setPageOrientation(QPageLayout.Orientation.Landscape)
        writer.setResolution(120)
        painter = QPainter(writer)
        scale = min(writer.width() / width, writer.height() / height)
        painter.scale(scale, scale)
        painter.drawImage(0, 0, image)
        painter.end()
    elif not image.save(str(path), "PNG"):
        raise OSError("EXPORT_WRITE_FAILED")
