"""Route risk-scoring against a point incident dataset.

Loads a CSV of past incidents (lat, lon, severity, road_users) and scores a
route by how many incidents fall within RISK_BUFFER_METERS of its geometry,
weighted by severity. This ships pointed at a synthetic demo dataset
(config.INCIDENT_DATA_IS_SYNTHETIC) — swap config.INCIDENT_DATA_PATH to a
real export (e.g. STRADA) with the same columns to score against real data.
"""

import math
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import pandas as pd

import config
import traffic_flow
from geo_utils import point_to_polyline_distance_m, polyline_length_m

REQUIRED_COLUMNS = {"lat", "lon", "severity", "road_users"}

ROAD_USER_LABELS = {
    "Car": "Car",
    "Bus": "Bus",
    "Tram": "Tram",
    "Cyclist": "Bike",
    "Pedestrian": "Pedestrian",
}


def accident_type_label(road_users):
    """Human-readable accident type from a '|'-separated road_users value,
    e.g. "Car & Bike accident". Used for map marker tooltips."""
    if pd.isna(road_users) or not str(road_users).strip():
        return "Traffic accident (type unspecified)"
    labels = [ROAD_USER_LABELS.get(u.strip(), u.strip()) for u in str(road_users).split("|") if u.strip()]
    return " & ".join(labels) + " accident"


SWEDISH_MONTHS = {
    name: i + 1
    for i, name in enumerate(
        ["januari", "februari", "mars", "april", "maj", "juni", "juli",
         "augusti", "september", "oktober", "november", "december"]
    )
}
_TITLE_TIME = re.compile(r"^\s*(\d{1,2}) ([a-zåäö]+) (\d{1,2})[.:](\d{2})", re.IGNORECASE)


def incident_happened_at(row):
    """When a police-reported accident happened, as a datetime, or None.

    The police event title starts with the time of the accident ("4
    september 06.53, Trafikolycka, Göteborg") but has no year, so the year
    comes from the report's publish time (`datetime`) -- stepping back a
    year for accidents on e.g. 31 December reported on 1 January.
    """
    title, published = row.get("title"), row.get("datetime")
    if not isinstance(title, str) or not isinstance(published, str):
        return None
    m = _TITLE_TIME.match(title)
    month = SWEDISH_MONTHS.get(m.group(2).lower()) if m else None
    try:
        # "2026-09-04 9:30:34 +02:00" -- date and time, dropping the offset.
        # Hours aren't zero-padded, so split rather than slice.
        published_at = datetime.strptime(" ".join(published.split()[:2]), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    if not month:
        return None
    happened = datetime(published_at.year, month, int(m.group(1)), int(m.group(3)), int(m.group(4)))
    if happened > published_at:
        happened = happened.replace(year=happened.year - 1)
    return happened


def format_when(dt):
    """e.g. "4 Sep 2026, 06:53"."""
    return f"{dt.day} {dt:%b %Y, %H:%M}"


SEVERITY_COLORS = {"fatal": "black", "severe": "orange", "minor": "#f2c744"}
SYNTHETIC_COLOR = "#9467bd"  # distinct purple, never used for a real severity


def incident_marker_style(row):
    """Folium CircleMarker kwargs + tooltip/popup text for one incident row.

    Fabricated demo rows (source == "SYNTHETIC_SAMPLE") are marked visually
    -- distinct purple color, dashed outline, lower opacity -- on every page
    that renders them, so they can be told apart from real police reports.
    Their text carries no label; purple is the marker.
    """
    is_synthetic = row.get("source") == "SYNTHETIC_SAMPLE"
    location_note = row.get("near") if is_synthetic else row.get("street")

    base_label = accident_type_label(row.get("road_users"))
    if isinstance(location_note, str) and location_note.strip():
        base_label += f" — {location_note}"

    if is_synthetic:
        tooltip = base_label
        popup = f"{str(row.get('severity', '')).title()} · {base_label}"
    else:
        tooltip = base_label
        happened = incident_happened_at(row)
        if happened:
            tooltip += f" · {format_when(happened)}"
        popup = f"{str(row.get('severity', '')).title()} · {base_label}"
        if isinstance(row.get("summary"), str):
            popup += f" — {row['summary'][:200]}"

    style = {
        "color": SYNTHETIC_COLOR if is_synthetic else SEVERITY_COLORS.get(str(row.get("severity", "")).lower(), "gray"),
        "weight": 2,
        "fill": True,
        "fill_opacity": 0.5 if is_synthetic else 0.8,
    }
    if is_synthetic:
        style["dash_array"] = "4"

    return {"tooltip": tooltip, "popup": popup, "style": style, "is_synthetic": is_synthetic}


def _load_csv(path):
    df = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        raise ValueError(f"Incident data at {path} is missing columns: {missing}")
    return df


@lru_cache(maxsize=4)
def load_incidents(path=None):
    """Load the incident dataset used for risk scoring and map display.

    With no argument, loads the real dataset (config.INCIDENT_DATA_PATH)
    and, if config.INCLUDE_SYNTHETIC_INCIDENTS is True, merges in the
    fabricated demo dataset at config.SYNTHETIC_INCIDENT_DATA_PATH -- those
    rows carry source="SYNTHETIC_SAMPLE" and an id prefixed "SYN-" so
    they're always distinguishable from real reports downstream (map
    marker styling keys off this same `source` column).

    Pass an explicit `path` to load a single file as-is, bypassing the
    merge (e.g. for tests or one-off inspection).
    """
    if path is not None:
        return _load_csv(path)

    frames = [_load_csv(config.INCIDENT_DATA_PATH)]
    if config.INCLUDE_SYNTHETIC_INCIDENTS:
        synthetic_path = Path(config.SYNTHETIC_INCIDENT_DATA_PATH)
        if synthetic_path.resolve() != Path(config.INCIDENT_DATA_PATH).resolve() and synthetic_path.exists():
            frames.append(_load_csv(synthetic_path))

    combined = pd.concat(frames, ignore_index=True, sort=False)
    missing = REQUIRED_COLUMNS - set(combined.columns)
    if missing:
        raise ValueError(f"Combined incident data is missing columns: {missing}")
    return combined


def score_route(coordinates, incidents=None, buffer_m=None, traffic_flows=None):
    """Score one route's risk.

    `coordinates` is a list of (lat, lon) points describing the route
    geometry, in order. Returns a dict with an overall score, a per-km
    rate (so longer routes aren't unfairly penalized just for length),
    a breakdown by road-user type, and the matched incident rows for
    map display.

    Risk per km = nearby incidents (severity-weighted) per km, plus, when
    `traffic_flows` (traffic_flow.load_vehicle_flows()) is given, points for
    how busy the roads the route uses are -- see
    config.TRAFFIC_RISK_POINTS_PER_10K. The two parts are also returned
    separately (incident_score_per_km / traffic_score_per_km).
    """
    incidents = incidents if incidents is not None else load_incidents()
    buffer_m = buffer_m or config.RISK_BUFFER_METERS

    nearby_rows = []
    for _, row in incidents.iterrows():
        dist = point_to_polyline_distance_m((row["lat"], row["lon"]), coordinates)
        if dist <= buffer_m:
            nearby_rows.append(row)

    length_km = max(polyline_length_m(coordinates) / 1000, 0.01)

    weighted_score = sum(
        config.SEVERITY_WEIGHTS.get(str(row["severity"]).lower(), 1)
        for row in nearby_rows
    )

    breakdown = {}
    for row in nearby_rows:
        road_users = row["road_users"]
        if pd.isna(road_users):
            continue
        for user in str(road_users).split("|"):
            user = user.strip()
            if not user:
                continue
            breakdown[user] = breakdown.get(user, 0) + config.SEVERITY_WEIGHTS.get(
                str(row["severity"]).lower(), 1
            )

    incident_score_per_km = weighted_score / length_km

    traffic = None
    traffic_score_per_km = 0.0
    if traffic_flows is not None:
        traffic = traffic_flow.route_traffic_exposure(coordinates, traffic_flows)
        # Length-weighted average vehicles/day over the whole route (streets
        # without traffic data count as 0), converted to points per km.
        traffic["avg_vehicles_per_day"] = round(traffic["vehicle_km_per_day"] / length_km)
        traffic_score_per_km = (
            traffic["avg_vehicles_per_day"] / 10_000 * config.TRAFFIC_RISK_POINTS_PER_10K
        )

    score_per_km = incident_score_per_km + traffic_score_per_km
    # Saturating 0-100% scale: no incidents and no traffic -> 0%, and risk approaches
    # (never quite reaches) 100% as the weighted incident density per km
    # grows well past config.RISK_PCT_SCALE. Bounded/monotonic, so it stays
    # readable as "0% = no known risk, 100% = extremely risky" regardless of
    # how sparse or dense the underlying incident dataset is.
    risk_percent = round(100 * (1 - math.exp(-score_per_km / config.RISK_PCT_SCALE)), 1)

    return {
        "incident_count": len(nearby_rows),
        "weighted_score": weighted_score,
        "score_per_km": round(score_per_km, 2),
        "incident_score_per_km": round(incident_score_per_km, 2),
        "traffic_score_per_km": round(traffic_score_per_km, 2),
        "traffic": traffic,
        "risk_percent": risk_percent,
        "length_km": round(length_km, 2),
        "breakdown_by_road_user": breakdown,
        "incidents": nearby_rows,
    }


def risk_level_label(risk_percent):
    """Short human label + emoji for a risk_percent value, for display."""
    if risk_percent < 20:
        return "🟢 Low risk"
    if risk_percent < 50:
        return "🟡 Moderate risk"
    if risk_percent < 80:
        return "🟠 High risk"
    return "🔴 Severe risk"
