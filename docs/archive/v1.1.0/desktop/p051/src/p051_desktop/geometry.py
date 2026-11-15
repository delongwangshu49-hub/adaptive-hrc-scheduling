"""P051 horizontal dual-view layout, owner override 2026-10-24.

All reviewed client sizes keep 3D on the left and timeline on the right.
Equal panels, full-width native viewport and a readable Gantt name column.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Plan:
    client: tuple[int, int]
    profile: str
    plots: tuple[Rect, Rect]
    geometry_admissible: bool
    reason: str
    runtime_kit_verified: bool = False
    label_width: int = 160
    orientation: str = "horizontal"


def plan(
    width: int,
    height: int,
    *,
    form_open: bool = False,
    extra_aux_height: int = 0,
    split_ratio: float = 0.5,
    label_width: int | None = None,
) -> Plan:
    """Panel equality does not require a blank native label gutter."""
    if any(type(v) is not int or v < 0 for v in (width, height, extra_aux_height)):
        raise ValueError("dimensions must be nonnegative logical integer pixels")
    if type(form_open) is not bool:
        raise ValueError("form_open must be boolean")
    if width >= 1440:
        profile, pad, gap = "wide", 16, 8
        mast, identity, actions, aux, footer = 64, 32, 44, 200 if form_open else 72, 32
        title, toolbar, axis = 32, 64, 24
    else:
        profile, pad, gap = "compact", 12, 4 if form_open else 6
        mast, identity, actions, aux, footer = 40, 24, 44, 144 if form_open else 32, 20
        title, toolbar, axis = 24, 64, 24
    dual_top = pad + mast + identity + actions + 3 * gap
    nondual = 2 * pad + 5 * gap + mast + identity + actions + aux + footer
    dual_height = height - nondual - extra_aux_height
    inset = title + toolbar + axis
    label = label_width if label_width is not None else (260 if profile == "wide" else 210)
    if type(label) is not int or not 170 <= label <= 300 or not 0.1 <= split_ratio <= 0.9:
        raise ValueError("PANEL_BUDGET")
    available = width - 2 * pad - 8
    panel_width = int(available * split_ratio)
    second_width = available - panel_width
    second_x = pad + panel_width + 8
    plots = (
        Rect(pad, dual_top + title + toolbar, panel_width, dual_height - inset),
        Rect(
            second_x + label, dual_top + title + toolbar, second_width - label, dual_height - inset
        ),
    )
    supported = width >= 1280 and height >= 720
    fits = (
        supported
        and plots[0].width >= 500
        and plots[1].width >= 300
        and all(r.height >= 160 for r in plots)
    )
    reason = "READY_FOR_HOST_GUARD" if fits else "GEOMETRY_BLOCKED"
    if not supported:
        reason = "BELOW_REVIEWED_CLIENT"
    return Plan((width, height), profile, plots, fits, reason, label_width=label)


def accepts_host(layout: Plan, measured_minimum: tuple[int, int]) -> bool:
    """Pure pre-commit predicate; true does not establish runtime compatibility."""
    if (
        not isinstance(measured_minimum, tuple)
        or len(measured_minimum) != 2
        or any(type(v) is not int or v <= 0 for v in measured_minimum)
    ):
        raise ValueError("measure both positive native minima before committing")
    r = layout.plots[0]
    return (
        layout.geometry_admissible
        and r.width >= measured_minimum[0]
        and r.height >= measured_minimum[1]
    )
