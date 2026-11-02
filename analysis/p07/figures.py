"""Five P07 figure groups from validated offline data, with source sidecars."""

import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from adapters import fatigue_polyline, require, union
from load import ROOT, pin, read, sha, write

SCENARIOS = ("N", "H", "F", "U", "C")
COLORS = ("#222222", "#999999")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=ROOT / "results/p07/r3")
    parser.add_argument("--output", type=Path, default=ROOT / "figures/p07/r3")
    args = parser.parse_args()
    data = args.data
    out = args.output
    validation = read(data / "validation.json")
    require(validation["status"] == "PASS", "FIGURES_REQUIRE_VALIDATED_DATA")
    for p in validation["inputs"] + list(validation.get("source_code", {}).values()):
        # The default validated sources retain their exact paths. Portable
        # replay uses its own new validation/manifest rather than editing pins.
        require(sha(ROOT / p["path"]) == p["sha256"], "FIGURE_INPUT_CHANGED:" + p["path"])
    out.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "figure.facecolor": "white",
            "axes.facecolor": "white",
            "savefig.facecolor": "white",
        }
    )
    index = []

    def finish(fig, identifier, group, caption, sources):
        files = []
        for ext in ("png", "svg", "pdf"):
            path = out / f"{identifier}.{ext}"
            fig.savefig(path, dpi=300, bbox_inches=None)
            files.append(pin(path))
        width, height = fig.get_size_inches()
        plt.close(fig)
        side = dict(
            id=identifier,
            group=group,
            caption=caption,
            alt=caption,
            source_data=[pin(data / x) for x in sources],
            script=pin(Path(__file__)),
            format="P07-FIGURE-PROVENANCE-1",
            files=files,
            width_inches=float(width),
            height_inches=float(height),
            raster_dpi=300,
            font_family="DejaVu Sans",
            matplotlib=matplotlib.__version__,
            palette="GRAYSCALE_WITH_LINESTYLE_MARKER_HATCH_REDUNDANCY",
            inference="Five fixed deterministic scenario pairs; no sampling CI or p values",
            journal="NOT_TARGETED; GENERAL_RESEARCH_EXPORT_NOT_JOURNAL_CERTIFICATION",
            missing_and_censoring="Explicit unknown/censored states retained in source tables",
            smoothing="NONE",
            publisher_compliance_claim=False,
        )
        write(out / f"{identifier}.json", side)
        index.append(side)

    # Group 1: native Mermaid remains interactive in supported Markdown viewers.
    architecture = """# P07 feedback architecture

```mermaid
%%{init: {"theme":"base","htmlLabels":false,"themeVariables":{"primaryColor":"#f2f2f2","primaryTextColor":"#171717","primaryBorderColor":"#333333","lineColor":"#333333"}}}%%
flowchart LR
  A[Actual execution and native readback] --> B[Delivered observation and catalog version]
  B --> C[Candidate search and independent gates]
  C --> D[Adopted arrangement or legal fallback]
  D --> A
  B --> E[Shared Gantt and scene domain]
  A --> F[Immutable evidence and failure ledger]
  F --> G[Offline metrics with explicit windows and denominators]
  G --> H[Five scenario pairs and four mechanisms]
  G --> I[Figures exports and claim evidence]
```

This is an explanatory architecture. It does not claim current performance targets,
unseen changes, whole-Kit equivalence, or a new production execution.
"""
    (out / "P07-01-feedback.md").write_text(architecture, encoding="utf-8")
    rows = read(data / "summary.json")
    costs = read(data / "costs.json")
    idx = {(r["scenario"], r["method"]): r for r in rows if r["scenario"] != "MECHANISM"}
    fig, axes = plt.subplots(2, 2, figsize=(11, 8), layout="constrained")
    fields = [
        ("on_time_received_fraction_all_released", "On-time external receipt / released products"),
        ("last_received_h", "Last actual receipt of uncancelled output (h)"),
        ("common_window_sum_E", "All-person exposure in [0,720h] (F h)"),
        ("common_window_max_E", "Maximum individual exposure in [0,720h] (F h)"),
    ]
    x = np.arange(5)
    for ax, (field, label) in zip(axes.flat, fields):
        for k, method in enumerate(("EDD", "ADAPTIVE")):
            vals = [idx[s, method][field] for s in SCENARIOS]
            ax.bar(
                x + (k - 0.5) * 0.32,
                vals,
                width=0.32,
                color=COLORS[k],
                edgecolor="#222",
                hatch="" if k == 0 else "///",
                label=method,
            )
        ax.set(xticks=x, xticklabels=SCENARIOS, ylabel=label, ylim=(0, None))
        ax.grid(axis="y", alpha=0.15)
        if field == "on_time_received_fraction_all_released":
            ax.set_ylim(0, 1)
            for k, method in enumerate(("EDD", "ADAPTIVE")):
                for i, s in enumerate(SCENARIOS):
                    value = idx[s, method][field]
                    ax.plot(
                        i + (k - 0.5) * 0.32,
                        value,
                        marker="o" if k == 0 else "s",
                        color=COLORS[k],
                        ms=4,
                    )
                    ax.annotate(
                        f"{value:g}",
                        (i + (k - 0.5) * 0.32, value),
                        xytext=(0, 5),
                        textcoords="offset points",
                        ha="center",
                        fontsize=7,
                    )
    axes[0, 0].legend()
    fig.suptitle("P07-02 | Original values: five deterministic scenario pairs")
    finish(
        fig,
        "P07-02-scenario-values",
        2,
        "原版本五情景原值；C为STOCK取消后的剩余接收，原720h截尾保留。共同窗含已声明派生尾部，不能当实际休息；全部原失败另见attempts表。",
        ["summary.json", "pairs.json", "attempts.json"],
    )

    # Group 3a: display-only representative selection, full data remain exported.
    fig, axes = plt.subplots(3, 1, figsize=(12, 9), layout="constrained")
    for ax, unit in zip(axes, ("N-CPU-EDD", "F-CPU-EDD", "C-STOCK-CPU-EDD-r4")):
        r = read(data / "computed" / f"{unit}.json", limit=80_000_000)
        lanes = sorted(r["device_ids"])
        for i, lane in enumerate(lanes):
            pieces = union(
                [
                    [x["start_h"], x["end_h"]]
                    for x in r["resource_intervals"]
                    if x["kind"] == "OWNERSHIP" and x["resource_id"] in (lane, "ENTITY:" + lane)
                ]
            )
            intervals = [(a, b - a) for a, b in pieces]
            ax.broken_barh(intervals, (i - 0.35, 0.7), facecolors="#444444", edgecolors="none")
        ax.set(
            yticks=range(len(lanes)),
            yticklabels=lanes,
            xlabel="Actual simulated time (h)",
            title=unit,
            xlim=(0, r["summary"]["actual_lifecycle_end_h"]),
        )
        ax.tick_params(axis="y", labelsize=7)
        ax.grid(axis="x", alpha=0.15)
    finish(
        fig,
        "P07-03a-resource-gantt",
        3,
        "预先指定N/F/C三个EDD代表的全部10项设备/工装所有权区间；同设备直接锁和ENTITY锁取并集。空行表示该运行无对应持有区间，完整资源表与全行双域导出保留。横条不是预测计划。",
        [
            "resources.csv",
            "summary.json",
            "computed/N-CPU-EDD.json",
            "computed/F-CPU-EDD.json",
            "computed/C-STOCK-CPU-EDD-r4.json",
        ],
    )
    normal = read(data / "computed/N-CPU-EDD.json", limit=80_000_000)
    high = read(data / "computed/H-CPU-EDD.json", limit=80_000_000)
    fig, axes = plt.subplots(5, 3, figsize=(11, 11), layout="constrained", sharex=True, sharey=True)
    ids = sorted(r["person_id"] for r in normal["people"])
    for ax, pid in zip(axes.flat, ids):
        for r, label, style, color in ((normal, "N", "--", "#777"), (high, "H", "-", "#222")):
            iv = [x for x in r["human_intervals"] if x["person_id"] == pid]
            t, f = fatigue_polyline(iv)
            ax.plot(t, f, style, color=color, lw=0.7, label=label)
        ax.set(title=pid, ylim=(0, 1), xlabel="Actual time (h)", ylabel="F")
        ax.grid(alpha=0.15)
    axes[0, 0].legend()
    fig.suptitle("P07-03b | All 15 people: actual lifecycle fatigue, N versus H (EDD)")
    finish(
        fig,
        "P07-03b-all-person-fatigue",
        3,
        "固定15人的实际生命周期疲劳，按实际区间函数绘制，恢复至0处显式插入折点；每条图线积分与同窗E核对，无平滑或抽样。N虚线、H实线，720h派生评价另在数据表报告。",
        ["people.csv", "activity.csv", "computed/N-CPU-EDD.json", "computed/H-CPU-EDD.json"],
    )
    dynamic = read(data / "dynamic_people.json", limit=32_000_000)
    fig, axes = plt.subplots(2, 1, figsize=(12, 7), layout="constrained")
    for ax, case in zip(axes, dynamic):
        pp = sorted(case["people"], key=lambda x: x["person_id"])
        x = np.arange(len(pp))
        ax.bar(x - 0.18, [p["presence_h"] for p in pp], 0.36, color="#222", label="Actual presence")
        ax.bar(
            x + 0.18,
            [p["availability_h"] for p in pp],
            0.36,
            color="#bbb",
            edgecolor="#222",
            hatch="///",
            label="Eligible availability",
        )
        ax.set(
            xticks=x,
            xticklabels=[p["person_id"] for p in pp],
            ylabel="Person-hours",
            title=f"{case['case']} | actual window [0,{case['common_window_h'][1]:.6f}] h",
            ylim=(0, None),
        )
        ax.legend(fontsize=8)
        ax.grid(axis="y", alpha=0.15)
    finish(
        fig,
        "P07-03c-dynamic-denominators",
        3,
        "两个原局部动态案例各16人的真实在岗与可用人时；离岗者仍保留，新人到岗前不补零。两个案例窗口/方法不同，图不作成对方法效应比较。",
        ["dynamic_people.csv", "dynamic_people.json"],
    )

    # Group 4: actual milestones, hypothetical adoption changes kept separate.
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), layout="constrained")
    f = read(data / "computed/F-CPU-EDD.json", limit=80_000_000)
    marks = [
        m
        for m in f["milestones"]
        if m["kind"] in ("FAILURE", "REPAIR", "RESUME_STARTED", "RESUME_COMPLETED")
    ]
    ax = axes[0, 0]
    for i, m in enumerate(marks):
        ax.scatter(m["time_h"], i, color="#222", marker="o")
        ax.annotate(
            m["kind"], (m["time_h"], i), xytext=(4, 4), textcoords="offset points", fontsize=7
        )
    ax.set(xlabel="Actual time (h)", yticks=[], title="F: actual failure / repair / resume")
    u = read(data / "computed/U-CPU-EDD-r3.json", limit=80_000_000)
    ax = axes[0, 1]
    for i, p in enumerate(u["products"]):
        for key, marker in [
            ("first_registration_h", "o"),
            ("first_actual_production_h", "s"),
            ("received_h", "^"),
        ]:
            if p.get(key) is not None:
                ax.scatter(
                    p[key],
                    i,
                    marker=marker,
                    facecolors="white" if marker == "o" else "#333",
                    edgecolors="#222",
                )
    ax.set(
        yticks=range(len(u["products"])),
        yticklabels=[p["product_id"] for p in u["products"]],
        xlabel="Actual time (h)",
        title="U EDD: registration o / first production s / receipt ^",
    )
    e20 = read(data / "e20_order_details.json")
    ax = axes[1, 0]
    applied = [r for r in e20["timeline"] if r["phase"] == "APPLIED"]
    for i, r in enumerate(applied):
        ax.scatter(r["sim_h"], i, color="#222")
        ax.annotate(
            r["kind"],
            (r["sim_h"], i),
            xytext=(-5 if r["sim_h"] > 40 else 5, 3),
            ha="right" if r["sim_h"] > 40 else "left",
            textcoords="offset points",
            fontsize=7,
        )
    ax.set(
        xlim=(0, 60),
        yticks=[],
        xlabel="Actual time (h), displayed window [0,60]",
        title="E20 r14: same-run applied changes; STOP at 387.732h",
    )
    ax = axes[1, 1]
    for i, h in enumerate(e20["plan_changes"]):
        ax.scatter(h["at_h"], i, color="#222", marker="x" if h["status"] != "ADOPTED" else "o")
        ax.annotate(
            f"call {i + 1}: {h['status']}",
            (h["at_h"], i),
            xytext=(5, 2),
            textcoords="offset points",
            fontsize=7,
        )
    ax.set(
        xlim=(0, 60),
        yticks=[],
        xlabel="Adoption boundary (h)",
        title="E20: adopted plans o / rejected attempt x",
    )
    finish(
        fig,
        "P07-04-response-timelines",
        4,
        "故障实际里程碑、急单实际结果及r14前60h变化/采用安排。r14最终387.732h STOPPED，仅1接收3未接收；计划采用不表示实际完成；8h追平单值未评价。",
        ["milestones.csv", "products.csv", "e20_order_details.json", "e20_orders.csv"],
    )
    c = read(data / "computed/C-STOCK-CPU-EDD-r4.json", limit=80_000_000)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.5), layout="constrained")
    marks = [m for m in c["milestones"] if "CANCEL" in m["kind"]]
    for i, m in enumerate(marks):
        axes[0].scatter(m["time_h"], i, color="#222")
        label = (
            "Last recorded tail\ncompletion"
            if m["kind"] == "LAST_RECORDED_CANCELLED_PRODUCT_COMPLETION"
            else m["kind"]
        )
        axes[0].annotate(
            label,
            (m["time_h"], i),
            xytext=(-5, 3) if "TAIL" in m["kind"] or "COMPLETION" in m["kind"] else (5, 3),
            ha="right" if "TAIL" in m["kind"] or "COMPLETION" in m["kind"] else "left",
            textcoords="offset points",
            fontsize=8,
        )
    axes[0].set(
        title="C-STOCK: cancellation and recorded tail",
        xlabel="Actual time (h)",
        yticks=[],
        ylim=(-0.2, 1.45),
    )
    for i, p in enumerate(c["products"]):
        if p["received_h"] is not None:
            axes[1].scatter(p["received_h"], i, color="#222", marker="^")
        else:
            axes[1].text(12, i, "CANCELLED; never reported as received", fontsize=8)
    axes[1].axvline(720, color="#555", ls="--")
    axes[1].set(
        xlim=(0, 760),
        ylim=(-0.2, 1.4),
        yticks=range(len(c["products"])),
        yticklabels=[p["product_id"] for p in c["products"]],
        xlabel="Actual time (h)",
        title="Remaining receipt ^\nOriginal WINDOW_CENSORED at720h",
    )
    finish(
        fig,
        "P07-04b-stock-cancellation",
        4,
        "STOCK取消的实际尾段记录与未取消产品接收分开；原720h WINDOW_CENSORED终态保留。图不代表WIP/J3 HOLD取消后剩余完成，原两次失败另列。",
        ["computed/C-STOCK-CPU-EDD-r4.json", "attempts.json"],
    )

    # Group 5: stages/output/exposure and recorded computation, no nested sum.
    mechanism = read(data / "mechanisms.json")
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.5), layout="constrained")
    for ax, key, label in zip(
        axes,
        ("last_received_h", "branch_labour_h", "common_window_sum_E"),
        ("Last actual receipt (h)", "Branch labour (person h)", "Common-window sum E (F h)"),
    ):
        ax.bar(
            range(4),
            [r[key] for r in mechanism],
            color=["#333", "#999", "#333", "#999"],
            edgecolor="#222",
            hatch="//",
        )
        ax.set(
            xticks=range(4),
            xticklabels=[r["mechanism"] for r in mechanism],
            ylabel=label,
            ylim=(0, None),
        )
        ax.tick_params(axis="x", rotation=25)
    finish(
        fig,
        "P07-05a-four-mechanisms",
        5,
        "H/HR×正常/较高初始疲劳的四机制；阶段劳动、全产品接收与共同窗曝光分开。HR两格引用N/H的EDD原运行，不增加独立样本。",
        ["mechanisms.json", "stages.csv"],
    )
    cidx = {r["unit"]: r for r in costs}
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.8), layout="constrained")
    for ax, key, label in zip(
        axes,
        ("original_runtime_elapsed_s", "search_seconds", "cached_plan_dispatches"),
        (
            "Original whole-run elapsed (s)",
            "Recorded search diagnostic (s)",
            "Actual cached-plan STARTED count",
        ),
    ):
        for k, method in enumerate(("EDD", "ADAPTIVE")):
            vals = [cidx[idx[s, method]["unit"]].get(key) for s in SCENARIOS]
            ax.bar(
                np.arange(5) + (k - 0.5) * 0.32,
                [v if v is not None else np.nan for v in vals],
                0.32,
                color=COLORS[k],
                edgecolor="#222",
                hatch="" if k == 0 else "///",
                label=method,
            )
        ax.set(xticks=range(5), xticklabels=SCENARIOS, ylabel=label, ylim=(0, None))
        ax.grid(axis="y", alpha=0.15)
    axes[0].legend()
    fig.suptitle("P07-05b | Recorded computation; CPU time / peak memory not recorded")
    finish(
        fig,
        "P07-05b-computation",
        5,
        "原机器/原顺序的总墙钟、搜索诊断和实际缓存计划派发；各计时字段可能嵌套，不合计成分项总成本；CPU时间和峰内存未测，不补0。候选检查不等于实际采用。",
        ["costs.json", "summary.json"],
    )
    write(
        out / "manifest.json",
        dict(
            groups=5,
            native_mermaid=pin(out / "P07-01-feedback.md"),
            figures=index,
            data_validation=pin(data / "validation.json"),
            new_production_runs=0,
            new_kit_runs=0,
        ),
    )
    print(json.dumps(dict(status="FIGURES_GENERATED", groups=5, static_figures=len(index))))


if __name__ == "__main__":
    main()
