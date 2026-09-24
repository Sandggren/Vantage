"""Small geometry helpers for route risk-scoring (no extra geo dependencies)."""

import math

EARTH_RADIUS_M = 6_371_000


def haversine_m(a, b):
    """Great-circle distance in meters between (lat, lon) points a and b."""
    lat1, lon1 = math.radians(a[0]), math.radians(a[1])
    lat2, lon2 = math.radians(b[0]), math.radians(b[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(h))


def _to_local_xy(point, origin):
    """Flat-earth projection (meters) around `origin`, good enough at city scale."""
    lat0 = math.radians(origin[0])
    x = math.radians(point[1] - origin[1]) * math.cos(lat0) * EARTH_RADIUS_M
    y = math.radians(point[0] - origin[0]) * EARTH_RADIUS_M
    return x, y


def point_to_segment_distance_m(point, seg_a, seg_b):
    """Shortest distance in meters from `point` to the segment seg_a-seg_b."""
    px, py = _to_local_xy(point, seg_a)
    ax, ay = 0.0, 0.0
    bx, by = _to_local_xy(seg_b, seg_a)

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0:
        return haversine_m(point, seg_a)

    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    closest_x, closest_y = ax + t * dx, ay + t * dy
    return math.hypot(px - closest_x, py - closest_y)


def point_to_polyline_distance_m(point, polyline):
    """Shortest distance in meters from `point` to a polyline of (lat, lon) points."""
    if len(polyline) == 1:
        return haversine_m(point, polyline[0])
    return min(
        point_to_segment_distance_m(point, polyline[i], polyline[i + 1])
        for i in range(len(polyline) - 1)
    )


def polyline_length_m(polyline):
    return sum(
        haversine_m(polyline[i], polyline[i + 1]) for i in range(len(polyline) - 1)
    )


def square_ring_lonlat(lat, lon, half_width_m):
    """Closed square ring in GeoJSON (lon, lat) point order, centered at
    (lat, lon) with the given half-width in meters. Used to build small
    "avoid" zones around incident points for routing."""
    dlat = half_width_m / 111_320
    dlon = half_width_m / (111_320 * math.cos(math.radians(lat)))
    corners = [
        (lat - dlat, lon - dlon),
        (lat - dlat, lon + dlon),
        (lat + dlat, lon + dlon),
        (lat + dlat, lon - dlon),
        (lat - dlat, lon - dlon),
    ]
    return [(c_lon, c_lat) for c_lat, c_lon in corners]


def bearing_deg(a, b):
    """Compass direction (0-360°) of travel from (lat, lon) a to b, using the
    same flat-earth projection as the distance helpers."""
    x, y = _to_local_xy(b, a)
    return math.degrees(math.atan2(x, y)) % 360


def line_angle_diff_deg(bearing1, bearing2):
    """Smallest angle (0-90°) between two lines, ignoring direction of
    travel -- a route heading north on a road drawn south-to-north and one
    drawn north-to-south both count as 0°."""
    diff = abs(bearing1 - bearing2) % 180
    return min(diff, 180 - diff)


def sample_polyline(polyline, step_m):
    """Points every `step_m` meters along a polyline of (lat, lon) points.

    Yields (point, bearing_deg) pairs; each sample stands for the `step_m`
    stretch of polyline it starts."""
    carry = 0.0  # distance into the current segment where the next sample falls
    for a, b in zip(polyline, polyline[1:]):
        seg_len = haversine_m(a, b)
        if seg_len == 0:
            continue
        bearing = bearing_deg(a, b)
        pos = carry
        while pos < seg_len:
            t = pos / seg_len
            yield (a[0] + t * (b[0] - a[0]), a[1] + t * (b[1] - a[1])), bearing
            pos += step_m
        carry = pos - seg_len
