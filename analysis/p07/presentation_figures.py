"""Four figures whose titles state the question answered by the saved data."""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from adapters import require
from load import pin, read, write
from matplotlib.lines import Line2D

HUMAN = "#616975"
COLLAB = "#1d4ed8"
INK = "#17212e"
URGENT = "#a61b1b"


def build_figures(data, output):
    require(read(data / "validation.json")["status"] == "PASS", "PRESENTATION_VALIDATION_REQUIRED")
    tables = read(data / "tables.json")
    output.mkdir(parents=True, exist_ok=True)
    index = []
    style = {
        "font.family": "DejaVu Sans",
        "font.size": 12,
        "axes.titlesize": 14,
        "axes.labelsize": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "svg.hashsalt": "p07-question-led-r1",
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }

    def save(fig, identifier, question, finding, scope):
        files = []
        for extension in ("png", "svg", "pdf"):
            target = output / (identifier + "." + extension)
            metadata = (
                {"Date": None}
                if extension == "svg"
                else ({"CreationDate": None, "ModDate": None} if extension == "pdf" else {})
            )
            fig.savefig(target, dpi=300, bbox_inches=None, metadata=metadata)
            files.append(pin(target))
        plt.close(fig)
        side = dict(
            id=identifier,
            question=question,
            finding=finding,
            scope=scope,
            files=files,
            source_data=[pin(data / "tables.json"), pin(data / "validation.json")],
            script=pin(Path(__file__)),
            transformations="Explicit table derivations; no smoothing; no new execution or sampling inference",
            publisher_target="GENERAL_PROJECT_DOCUMENTATION; NO_JOURNAL_CERTIFICATION",
        )
        write(output / (identifier + ".json"), side)
        index.append(side)

    with plt.rc_context(style):
        rows = tables["mechanism_contrasts"]
        fig, axes = plt.subplots(3, 1, figsize=(8.2, 10.2))
        fig.subplots_adjust(left=0.19, right=0.94, top=0.82, bottom=0.17, hspace=0.8)
        labels = ["Normal F0=0.2", "Higher F0=0.6"]
        fields = [
            (
                "human_branch_person_h",
                "hr_branch_person_h",
                "Branch labour (person h)",
                "branch_person_h_change_percent",
                (0, 15),
            ),
            (
                "human_all_person_E",
                "hr_all_person_E",
                "All-person exposure in [0,720h] (F h)",
                "all_person_E_change_percent",
                (0, 355),
            ),
            (
                "human_receipt_h",
                "hr_receipt_h",
                "Last actual receipt (h); displayed axis 500-565h",
                "receipt_change_h",
                (500, 565),
            ),
        ]
        for ax, (a, b, label, delta_key, limits) in zip(axes, fields):
            ax.set(yticks=[1, 0], yticklabels=labels, xlabel=label, xlim=limits, ylim=(-0.6, 1.6))
            ax.grid(axis="x", alpha=0.18)
            for y, row in zip((1, 0), rows):
                av, bv = row[a], row[b]
                if av == bv:
                    ax.scatter([av], [y], marker="D", s=75, color=INK, zorder=3)
                    ax.annotate(
                        f"Both {av:.2f} | no receipt change",
                        (av, y),
                        xytext=(0, 14),
                        textcoords="offset points",
                        ha="center",
                        fontsize=11,
                    )
                else:
                    ax.plot([av, bv], [y, y], color="#aab2bd", lw=2, zorder=1)
                    ax.scatter(
                        [av],
                        [y],
                        marker="o",
                        s=70,
                        facecolors="white",
                        edgecolors=HUMAN,
                        lw=1.8,
                        zorder=3,
                    )
                    ax.scatter([bv], [y], marker="s", s=65, color=COLLAB, zorder=3)
                    ax.annotate(
                        f"H {av:.3f}" if a.endswith("person_h") else f"H {av:.2f}",
                        (av, y),
                        xytext=(0, 13),
                        textcoords="offset points",
                        ha="center",
                        fontsize=11,
                        color=HUMAN,
                    )
                    ax.annotate(
                        f"HR {bv:.3f}" if b.endswith("person_h") else f"HR {bv:.2f}",
                        (bv, y),
                        xytext=(0, -21),
                        textcoords="offset points",
                        ha="center",
                        fontsize=11,
                        color=COLLAB,
                    )
                    delta = row[delta_key]
                    text = (
                        f"{delta:+.2f} h" if delta_key == "receipt_change_h" else f"{delta:+.2f}%"
                    )
                    ax.text(
                        0.02,
                        0.94 if y == 1 else 0.40,
                        text,
                        transform=ax.transAxes,
                        ha="left",
                        va="top",
                        fontsize=12,
                        weight="bold",
                    )
        fig.suptitle(
            "Branch labour falls in both conditions;\nearlier receipt appears only in the higher-fatigue case",
            fontsize=16,
            y=0.975,
        )
        fig.legend(
            handles=[
                Line2D(
                    [],
                    [],
                    color=HUMAN,
                    marker="o",
                    markerfacecolor="white",
                    ls="",
                    label="H: human mode",
                ),
                Line2D(
                    [], [], color=COLLAB, marker="s", ls="", label="HR: sequential human-robot mode"
                ),
            ],
            loc="upper center",
            bbox_to_anchor=(0.5, 0.91),
            ncol=1,
            frameon=False,
            fontsize=11,
        )
        fig.text(
            0.08,
            0.035,
            "Four existing deterministic mechanism cells. HR reuses N/H EDD runs.\nThis is a mode comparison, not an ADAPTIVE-versus-EDD advantage.\nExposure uses the declared 720h evaluation; receipt uses actual events.",
            fontsize=10,
            color=HUMAN,
        )
        save(
            fig,
            "P07-R4-01-mechanism-contrast",
            "Do branch savings reach the whole production outcome?",
            "Branch person-hours fall about 68%; normal receipt is unchanged and higher-fatigue receipt is 22.071h earlier.",
            "H/HR mechanism comparison; four reused existing cells; no independent replication added",
        )

        rr = tables["e20_response"]
        fig, ax = plt.subplots(figsize=(10, 6.5))
        fig.subplots_adjust(left=0.17, right=0.97, top=0.75, bottom=0.28)
        end = rr[0]["observation_end_h"]
        for y, row in zip((3, 2, 1, 0), rr):
            start, first = row["registration_h"], row["first_nonservice_started_h"]
            ax.plot([start, first], [y, y], color=COLLAB, lw=4, solid_capstyle="butt")
            ax.scatter([start], [y], s=50, marker="o", facecolor="white", edgecolor=INK, zorder=4)
            ax.scatter([first], [y], s=65, marker="D", color=COLLAB, zorder=4)
            right = row["received_h"] if row["received_h"] is not None else end
            ax.plot([first, right], [y, y], color="#8c96a4", ls=(0, (2, 3)), lw=1.5)
            if row["received_h"] is not None:
                ax.scatter([right], [y], marker="^", s=85, color="#16755a", zorder=4)
                ax.annotate(
                    f"Received {right:.3f}h",
                    (right, y),
                    xytext=(-6, 14),
                    textcoords="offset points",
                    ha="right",
                    fontsize=11,
                )
            else:
                ax.scatter([end], [y], marker=">", s=80, facecolor="white", edgecolor=INK, zorder=4)
                ax.annotate(
                    "Not received",
                    (end, y),
                    xytext=(7, 0),
                    textcoords="offset points",
                    va="center",
                    fontsize=10,
                )
            gap = row["wait_to_first_nonservice_started_h"]
            if y == 3:
                ax.annotate(
                    "First non-service STARTED: 0.034h",
                    (first, y),
                    xytext=(20, -26),
                    textcoords="offset points",
                    fontsize=10,
                )
            else:
                ax.annotate(
                    f"Wait {gap:.3f}h",
                    ((start + first) / 2, y),
                    xytext=(0, 12),
                    textcoords="offset points",
                    ha="center",
                    fontsize=11,
                    color=COLLAB,
                )
            if row["due_h"] <= end:
                due = row["due_h"]
                ax.vlines(due, y - 0.28, y + 0.28, color=URGENT, ls="--", lw=1.6)
                ax.annotate(
                    f"Due {due:.3f}h",
                    (due, y),
                    xytext=(0, -30),
                    textcoords="offset points",
                    ha="center",
                    fontsize=10,
                    color=URGENT,
                )
                ax.text(
                    190,
                    y + 0.17,
                    f"Tardiness >= {row['receipt_tardiness_or_lower_bound_h']:.3f}h\nat observation end",
                    fontsize=11,
                    color=URGENT,
                )
        ax.axvline(end, color=INK, ls="--", lw=1)
        ax.text(end, 3.58, f"STOP {end:.3f}h", ha="right", fontsize=11)
        ax.set(
            xlim=(-5, 455),
            ylim=(-0.65, 3.75),
            yticks=[3, 2, 1, 0],
            yticklabels=["Base / P1", "Normal / P2", "Normal / P3", "Urgent / P4"],
            xlabel="Simulation time (h)",
        )
        ax.grid(axis="x", alpha=0.15)
        fig.suptitle("An adopted plan is not a received product", fontsize=18, y=0.97)
        fig.text(
            0.17,
            0.855,
            "Same E20 r14 run: plan adoption shares registration's simulation timestamp.\nFirst actual starts are later; 1 product received and 3 pending at STOP.",
            fontsize=12,
        )
        fig.text(
            0.17,
            0.08,
            "Solid blue: registration to first non-service STARTED.\nDotted grey: interval between observed events, not continuous processing.\nOther order due dates lie after this observation window; no wall-time latency inferred.",
            fontsize=10,
            color=HUMAN,
        )
        save(
            fig,
            "P07-R4-02-order-event-chain",
            "Where is the delay between registration, planning, first action and receipt?",
            "Urgent first start follows registration by 24.378h; urgent receipt remains censored with a 290.732h tardiness lower bound.",
            "One original real-Kit r14 prefix; non-service STARTED may include transport; three right-censored products",
        )

        normal = [r for r in tables["activity_decomposition"] if r["unit"] == "N-CPU-EDD"]
        fig, axes = plt.subplots(2, 1, figsize=(8.4, 9.8))
        fig.subplots_adjust(left=0.18, right=0.95, top=0.82, bottom=0.17, hspace=0.46)
        for ax, key, absolute, label, unit in [
            (
                axes[0],
                "eligible_share_percent",
                "calendar_eligible_person_h",
                "Share of calendar-eligible person-hours (%)",
                "person h",
            ),
            (
                axes[1],
                "exposure_share_percent",
                "actual_exposure_F_h",
                "Share of actual lifecycle exposure (%)",
                "F h",
            ),
        ]:
            selected = sorted([r for r in normal if r[absolute] > 0], key=lambda r: -r[key])
            for i, row in enumerate(selected):
                value = row[key]
                ax.barh(
                    i, value, height=0.65, color=COLLAB if row["phase"] == "WAIT" else "#8793a2"
                )
                text = f"{row[absolute]:,.2f} {unit} | {value:.2f}%"
                ax.text(
                    value / 2 if value > 35 else value + 1.5,
                    i,
                    text,
                    va="center",
                    ha="center" if value > 35 else "left",
                    color="white" if value > 35 else INK,
                    fontsize=11,
                )
            ax.set(
                xlim=(0, 100),
                yticks=range(len(selected)),
                yticklabels=[r["phase"] for r in selected],
                xlabel=label,
            )
            ax.invert_yaxis()
            ax.grid(axis="x", alpha=0.15)
            ax.set_axisbelow(True)
        fig.suptitle("Waiting dominates eligible time and model exposure", fontsize=17, y=0.97)
        fig.text(
            0.18,
            0.865,
            "Normal EDD, actual observation 0-531.859h.\nTwo denominators: 2,697.885 eligible person h and 241.157 F h.",
            fontsize=12,
        )
        fig.text(
            0.08,
            0.035,
            "The model accumulates WAIT fatigue at +0.02 F/h; REST and OFF_SHIFT recover at 0.2 F/h.\nCalendar-ineligible REST/OFF_SHIFT are omitted only from the upper capacity panel.\nModel activity attribution is not a physiological measurement or bottleneck proof.",
            fontsize=10,
            color=HUMAN,
        )
        save(
            fig,
            "P07-R4-03-time-and-exposure",
            "Which activities account for calendar capacity and accumulated exposure?",
            "WAIT occupies 91.06% of eligible person-hours and accounts for 68.98% of actual model exposure.",
            "Normal EDD only; actual lifecycle; calendar capacity and activity are distinct; all activity exposure retained",
        )

        windows = tables["fatigue_windows"]
        fig, (trace_ax, ax) = plt.subplots(
            2, 1, figsize=(8.2, 8.0), gridspec_kw={"height_ratios": [1.5, 1]}
        )
        fig.subplots_adjust(left=0.21, right=0.94, top=0.87, bottom=0.21, hspace=0.65)
        curve = tables["fatigue_first_day"]
        trace_ax.plot(
            [r["time_h"] for r in curve],
            [r["normal_mean_F"] for r in curve],
            color=HUMAN,
            ls="--",
            lw=1.7,
            label="Normal initial F=0.2",
        )
        trace_ax.plot(
            [r["time_h"] for r in curve],
            [r["higher_mean_F"] for r in curve],
            color=COLLAB,
            lw=1.7,
            label="Higher initial F=0.6",
        )
        trace_ax.set(
            xlim=(0, 24),
            ylim=(0, 0.8),
            xlabel="First-day actual simulation time (h)",
            ylabel="Mean F across all 15 people",
        )
        trace_ax.legend(fontsize=10, frameon=False)
        trace_ax.grid(alpha=0.15)
        for y, row in zip((1, 0), windows):
            value = row["delta_E"]
            ax.barh(y, value, height=0.5, color=COLLAB if row["window"] == "first" else "#8793a2")
            ax.text(
                value / 2 if value > 20 else value + 1,
                y,
                f"{value:.3f} F h | {row['delta_share_percent']:.2f}%",
                va="center",
                ha="center" if value > 20 else "left",
                color="white" if value > 20 else INK,
                fontsize=12,
            )
        ax.set(
            xlim=(0, 70),
            yticks=[1, 0],
            yticklabels=["First 24h", "24-531.859h"],
            xlabel="Added exposure: higher minus normal initial fatigue (F h)",
        )
        ax.grid(axis="x", alpha=0.15)
        ax.set_axisbelow(True)
        fig.suptitle("99.02% of the added exposure occurs in the first day", fontsize=16, y=0.96)
        fig.text(
            0.08,
            0.035,
            "Mean curves retain all interval and recovery-zero breakpoints; no smoothing or sample CI.\nN/H EDD differ in initial F only. Bars compare contributions of unequal time windows, not rates.\nFull actual-lifecycle difference: 63.806 F h; no extrapolated 720h tail used.",
            fontsize=10,
            color=HUMAN,
        )
        save(
            fig,
            "P07-R4-04-initial-fatigue-window",
            "When does the initial-fatigue difference contribute to the accumulated exposure difference?",
            "First-day difference is 63.178 F h, later difference 0.628 F h: 99.02% of 63.806 F h falls in the first day.",
            "N/H EDD actual lifecycle; exact clipped interval integration; unequal windows; fixed model conditions",
        )
    write(
        output / "manifest.json",
        dict(
            format="P07-QUESTION-LED-FIGURES-1",
            figures=index,
            data_manifest=pin(data / "manifest.json"),
            historical_appendix="figures/p07/r3; not active comparative gallery",
            new_production_runs=0,
            new_kit_runs=0,
        ),
    )
    return index
