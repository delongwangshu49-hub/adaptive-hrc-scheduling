"""Display-only direction and gait math; no route, timing or collider changes."""

import math


def facing_yaw(direction):
    """Yaw for a model whose accepted front points along local positive Y."""
    x, y = direction[:2]
    if not all(math.isfinite(v) for v in (x, y)) or math.hypot(x, y) < 1e-12:
        raise ValueError("VISUAL_DIRECTION_INVALID")
    return math.degrees(math.atan2(-x, y))


def angle_delta(start, finish):
    return (finish - start + 180) % 360 - 180


def route_heading(points, fraction, blend_m=0.6):
    """Interpolate the facing near existing corners without changing the path."""
    if not math.isfinite(fraction) or not 0 <= fraction <= 1 or blend_m <= 0:
        raise ValueError("VISUAL_ROUTE_SAMPLE_INVALID")
    segments = []
    distance = 0.0
    for a, b in zip(points, points[1:]):
        length = math.dist(a, b)
        if math.hypot(b[0] - a[0], b[1] - a[1]) < 1e-12:
            distance += length
            continue
        segments.append((distance, distance + length, facing_yaw((b[0] - a[0], b[1] - a[1]))))
        distance += length
    if not segments:
        return None
    at = fraction * distance
    current = next((s[2] for s in segments if at <= s[1]), segments[-1][2])
    for first, second in zip(segments, segments[1:]):
        corner = first[1]
        width = min(blend_m, (first[1] - first[0]) / 2, (second[1] - second[0]) / 2)
        if width > 0 and corner - width <= at <= corner + width:
            u = (at - corner + width) / (2 * width)
            u = u * u * (3 - 2 * u)
            return first[2] + angle_delta(first[2], second[2]) * u
    return current


def bounded_scale(width, depth, yaw):
    """Fit a rotated visible body to the original axis-aligned XY envelope."""
    if min(width, depth) <= 0 or not all(math.isfinite(v) for v in (width, depth, yaw)):
        raise ValueError("VISUAL_ENVELOPE_INVALID")
    c, s = abs(math.cos(math.radians(yaw))), abs(math.sin(math.radians(yaw)))
    return min(1.0, width / (width * c + depth * s), depth / (width * s + depth * c))


def foot_offset(clock_s, side, moving):
    if not math.isfinite(clock_s) or side not in (0, 1):
        raise ValueError("VISUAL_CLOCK_INVALID")
    if not moving:
        return (0.0, 0.0, 0.0)
    phase = math.tau * clock_s / 0.8 + side * math.pi
    return (0.0, 0.025 * math.sin(phase), 0.015 * max(0.0, math.sin(phase)))
