"""Conservative support coverage from measured mesh triangles, in prefab coordinates.

A successful coverage check is geometric only. It does not establish load-bearing
capacity, free space above the surface, or a suitable semantic use.
"""
from math import isfinite


def _cross(a, b, c):
    return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])


def _signed_area(points):
    return sum(a[0]*b[1]-b[0]*a[1] for a, b in zip(points, points[1:]+points[:1]))/2


def _clip(subject, boundary):
    """Sutherland-Hodgman convex intersection; boundary is counterclockwise."""
    out = subject
    for a, b in zip(boundary, boundary[1:]+boundary[:1]):
        incoming, out = out, []
        if not incoming:
            break
        previous = incoming[-1]
        before = _cross(a, b, previous)
        for current in incoming:
            after = _cross(a, b, current)
            if (before >= 0) != (after >= 0):
                fraction = before/(before-after)
                out.append(tuple(previous[i]+fraction*(current[i]-previous[i]) for i in (0, 1)))
            if after >= 0:
                out.append(current)
            previous, before = current, after
    return out


def footprint_supported(triangles, rectangle, height_tolerance=.01):
    """Require the full axis-aligned XZ rectangle on one near-horizontal patch.

    Overlapping triangles are rejected conservatively: duplicated geometry must
    not compensate for a hole by inflating the measured area.
    """
    if len(rectangle) != 4 or not all(isfinite(x) for x in rectangle):
        raise ValueError('Finite XZ rectangle required')
    x0, z0, x1, z1 = rectangle
    if x1 <= x0 or z1 <= z0 or not isfinite(height_tolerance) or height_tolerance < 0:
        raise ValueError('Positive footprint and nonnegative tolerance required')
    boundary = [(x0,z0),(x1,z0),(x1,z1),(x0,z1)]
    patches, heights = [], []
    for triangle in triangles:
        if len(triangle) != 3 or any(len(v) != 3 or not all(isfinite(x) for x in v) for v in triangle):
            raise ValueError('Finite triangle vertices required')
        flat = [(v[0],v[2]) for v in triangle]
        if _signed_area(flat) < 0:
            flat.reverse()
        clipped = _clip(flat, boundary)
        if abs(_signed_area(clipped)) > 1e-10:
            patches.append(clipped)
            heights.extend(v[1] for v in triangle)
    if not heights or max(heights)-min(heights) > height_tolerance:
        return False
    for i, a in enumerate(patches):
        if any(abs(_signed_area(_clip(a,b))) > 1e-9 for b in patches[i+1:]):
            return False
    expected = (x1-x0)*(z1-z0)
    return abs(sum(abs(_signed_area(p)) for p in patches)-expected) <= max(1e-9, expected*1e-6)
