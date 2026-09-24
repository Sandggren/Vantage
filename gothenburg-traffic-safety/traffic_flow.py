"""Vehicle and bicycle traffic-flow layers for the map.

Vehicle flow comes from Trafikverket's public "Vägtrafikflöden" ArcGIS
service (annual average daily traffic, AADT, per road segment). That
service splits the road network across several layers by traffic level
(<1000 vs >=1000 vehicles/day) and by how the number was obtained
(measured vs. estimated, "Mätmetod 4"). We query all four and merge them,
otherwise most of the network is missing from the map.

Note: Trafikverket only covers state roads (E6, E20, E45, road 40, 155
etc.) — not municipal city streets, which Göteborgs Stad owns.
"""

import requests
import streamlit as st

import config
from geo_utils import bearing_deg, line_angle_diff_deg, point_to_segment_distance_m, sample_polyline

TRAFIKVERKET_FLOW_URL = (
    "https://vektor.trafikverket.se/gis/rest/services/"
    "VTF_MC/Vagtrafikfloden_Mc_gradient/MapServer"
)

# layer id -> data type. These four layers are disjoint and together cover
# the full network; the other layers in the service are text labels or
# small-scale overview copies of the same segments.
TRAFIKVERKET_FLOW_LAYERS = {
    5: "Measured",  # < 1000 vehicles/day
    6: "Estimated",  # < 1000 vehicles/day
    9: "Measured",  # >= 1000 vehicles/day
    10: "Estimated",  # >= 1000 vehicles/day
}

# (minimum vehicles/day, line color, line weight), highest first. Darker
# and thicker red = more traffic.
VEHICLE_FLOW_CLASSES = [
    (30_000, "#67000d", 7),
    (15_000, "#b3001b", 6),
    (5_000, "#e63946", 5),
    (1_000, "#f4845f", 4),
    (0, "#f9c74f", 3),
]

BIKE_COLOR = "#2a9d8f"

# Bicycle counts per weekday at a few Göteborgs Stad counting stations.
# NOTE: these numbers were typed in by hand and have not been checked
# against Göteborgs Stad's published counts — they're shown on the map as
# unverified until replaced with data from the city's open data API
# (data.goteborg.se, "Cykelflöden").
BIKE_COUNT_STATIONS = [
    {"name": "Ullevigatan", "lat": 57.7065, "lon": 11.9860, "flow": 3200, "year": 2022},
    {"name": "Redbergsvägen", "lat": 57.7160, "lon": 12.0040, "flow": 2800, "year": 2022},
    {"name": "Nya Allén", "lat": 57.7035, "lon": 11.9660, "flow": 2400, "year": 2022},
    {"name": "Delsjövägen", "lat": 57.6950, "lon": 12.0140, "flow": 2400, "year": 2022},
]
BIKE_DATA_VERIFIED = False


def _bbox_param():
    b = config.GOTHENBURG_BOUNDS
    return f"{b['min_lon']},{b['min_lat']},{b['max_lon']},{b['max_lat']}"


@st.cache_data(ttl=24 * 3600, show_spinner="Loading vehicle traffic flows from Trafikverket…")
def load_vehicle_flows():
    """GeoJSON FeatureCollection of road segments within Gothenburg, each
    with AADT_TOT (vehicles/day), VAEG_NUM (road number), AAR (year) and
    DATA_TYPE ("Measured"/"Estimated")."""
    features = []
    for layer_id, data_type in TRAFIKVERKET_FLOW_LAYERS.items():
        response = requests.get(
            f"{TRAFIKVERKET_FLOW_URL}/{layer_id}/query",
            params={
                "where": "AADT_TOT > 0",
                "outFields": "AADT_TOT,VAEG_NUM,AAR",
                "geometry": _bbox_param(),
                "geometryType": "esriGeometryEnvelope",
                "inSR": "4326",
                "outSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "returnGeometry": "true",
                # Light simplification (~10 m) to keep the map responsive.
                "maxAllowableOffset": "0.0001",
                "f": "geojson",
            },
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            raise RuntimeError(f"Trafikverket layer {layer_id}: {data['error']}")

        for feature in data.get("features", []):
            props = feature["properties"]
            props["DATA_TYPE"] = data_type
            # String, so the tooltip doesn't format it as "2 025".
            props["AAR"] = str(props.get("AAR") or "–")
            props["VAEG_NUM"] = f"Road {props['VAEG_NUM']}" if props.get("VAEG_NUM") else "Unnumbered road"
            features.append(feature)

    # Draw busiest roads last so they sit on top where segments overlap.
    features.sort(key=lambda f: f["properties"].get("AADT_TOT") or 0)
    return {"type": "FeatureCollection", "features": features}


def vehicle_flow_class(vehicles_per_day):
    """(color, weight) for a traffic volume."""
    try:
        vehicles_per_day = float(vehicles_per_day)
    except (TypeError, ValueError):
        vehicles_per_day = 0
    for threshold, color, weight in VEHICLE_FLOW_CLASSES:
        if vehicles_per_day >= threshold:
            return color, weight
    return VEHICLE_FLOW_CLASSES[-1][1:]


def vehicle_flow_style(feature):
    color, weight = vehicle_flow_class(feature["properties"].get("AADT_TOT"))
    return {"color": color, "weight": weight, "opacity": 0.85}


def bike_marker_radius(flow):
    """Bigger circle = more bicycles."""
    return max(6, min(14, flow / 300))


def legend_html(extra_html=""):
    """Small fixed-position legend for the vehicle flow colors; `extra_html`
    is appended for other layers' legend entries."""
    rows = []
    for i, (threshold, color, weight) in enumerate(VEHICLE_FLOW_CLASSES):
        if i == 0:
            label = f"{threshold:,}+"
        else:
            upper = VEHICLE_FLOW_CLASSES[i - 1][0]
            label = f"{threshold:,}–{upper - 1:,}"
        rows.append(
            f'<div><span style="display:inline-block;width:26px;height:{weight}px;'
            f'background:{color};vertical-align:middle;margin-right:6px"></span>{label}</div>'
        )
    rows.append(
        f'<div style="margin-top:4px"><span style="display:inline-block;width:12px;height:12px;'
        f'border-radius:50%;background:{BIKE_COLOR};vertical-align:middle;margin:0 8px 0 7px"></span>'
        "Bicycle count</div>"
    )
    return (
        '<div id="map-legend" style="position:fixed;bottom:50px;left:10px;z-index:9999;background:white;'
        "transition:opacity .15s;"
        "padding:8px 10px;border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);"
        'font:12px sans-serif;line-height:1.6">'
        "<b>Vehicles / day</b>" + "".join(rows) + extra_html + "</div>"
    )


def _flow_segments(flows):
    """Flatten the GeoJSON into straight road pieces with a bounding box, so
    routes can be matched against them quickly."""
    pad = config.TRAFFIC_MATCH_METERS / 111_000 * 2  # generous: lon degrees are shorter
    pieces = []
    for idx, feature in enumerate(flows["features"]):
        geom = feature["geometry"]
        lines = [geom["coordinates"]] if geom["type"] == "LineString" else geom["coordinates"]
        for line in lines:
            for (lon1, lat1), (lon2, lat2) in zip(line, line[1:]):
                pieces.append(
                    {
                        "feature": idx,
                        "a": (lat1, lon1),
                        "b": (lat2, lon2),
                        "bearing": bearing_deg((lat1, lon1), (lat2, lon2)),
                        "min_lat": min(lat1, lat2) - pad,
                        "max_lat": max(lat1, lat2) + pad,
                        "min_lon": min(lon1, lon2) - pad,
                        "max_lon": max(lon1, lon2) + pad,
                    }
                )
    return pieces


def route_traffic_exposure(coordinates, flows):
    """How much of a route runs along roads in the Trafikverket traffic data,
    and how busy those roads are.

    The route is sampled every TRAFFIC_SAMPLE_STEP_M meters; a sample counts
    as "on" a road when it lies within TRAFFIC_MATCH_METERS of it AND runs in
    roughly the same direction (so crossing a highway on a bridge, or a
    street running under one, doesn't count as driving on it). Streets not
    covered by Trafikverket (most municipal city streets) simply don't
    match and add no traffic, and roads matched for less than
    TRAFFIC_MIN_MATCH_M are ignored as junction crossings.

    Bike paths and footpaths running right next to a road can't be told
    apart from the road itself at this precision, so for bike/walk routes
    the result means "along" busy roads rather than "on" them.

    Returns a dict with:
      vehicle_km_per_day  sum over matched stretches of km * vehicles/day
      matched_km          km of the route on roads with traffic data
      busy_km             km on roads with >= BUSY_ROAD_VEHICLES_PER_DAY
      busiest             {"vehicles_per_day", "road"} of the busiest road used, or None
      feature_indices     indices into flows["features"] the route uses (for drawing)
    """
    step_m = config.TRAFFIC_SAMPLE_STEP_M
    max_dist = config.TRAFFIC_MATCH_METERS
    max_angle = config.TRAFFIC_MATCH_MAX_ANGLE_DEG
    pieces = _flow_segments(flows)
    features = flows["features"]

    meters_on = {}  # feature index -> meters of route matched to it
    for point, bearing in sample_polyline(coordinates, step_m):
        lat, lon = point
        best = None
        for piece in pieces:
            if not (piece["min_lat"] <= lat <= piece["max_lat"] and piece["min_lon"] <= lon <= piece["max_lon"]):
                continue
            if line_angle_diff_deg(bearing, piece["bearing"]) > max_angle:
                continue
            dist = point_to_segment_distance_m(point, piece["a"], piece["b"])
            if dist <= max_dist and (best is None or dist < best[0]):
                best = (dist, piece["feature"])
        if best is None:
            continue

        meters_on[best[1]] = meters_on.get(best[1], 0) + step_m

    # Drop roads the route only brushes (typically crossing at a junction).
    used = {i: m for i, m in meters_on.items() if m >= config.TRAFFIC_MIN_MATCH_M}

    matched_m = busy_m = vehicle_m_per_day = 0.0
    for idx, meters in used.items():
        vehicles = float(features[idx]["properties"].get("AADT_TOT") or 0)
        matched_m += meters
        vehicle_m_per_day += meters * vehicles
        if vehicles >= config.BUSY_ROAD_VEHICLES_PER_DAY:
            busy_m += meters

    busiest = None
    if used:
        top = max(used, key=lambda i: features[i]["properties"].get("AADT_TOT") or 0)
        busiest = {
            "vehicles_per_day": int(features[top]["properties"].get("AADT_TOT") or 0),
            "road": features[top]["properties"].get("VAEG_NUM"),
        }

    return {
        "vehicle_km_per_day": vehicle_m_per_day / 1000,
        "matched_km": round(matched_m / 1000, 2),
        "busy_km": round(busy_m / 1000, 2),
        "busiest": busiest,
        "feature_indices": sorted(used),
    }
