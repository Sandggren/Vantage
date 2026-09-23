"""Route Check — compare a fast route vs. a lower-risk route.

Geocodes a start point (browser geolocation or a typed address) and a
destination address, then asks OpenRouteService for route alternatives and
scores each against the incident dataset in risk.py. Shows the fastest
route and the lowest-risk route side by side, both annotated with their
risk score, so a trade-off between speed and safety is visible before you
travel.
"""

import folium
import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

import config
import risk
import routing

st.set_page_config(page_title="Route Risk Check", page_icon="🧭", layout="wide")

st.title("🧭 Route Risk Check")
st.caption(
    "Compare a fast route against a lower-risk route between two points, "
    "each scored against reported incidents near the road."
)

if not config.OPENROUTESERVICE_API_KEY:
    st.warning(
        "No OpenRouteService API key configured. Add `OPENROUTESERVICE_API_KEY` "
        "to a `.env` file in the project root (see `.env.example`), then reload "
        "this page. Get a free key at https://openrouteservice.org/dev/#/signup.",
        icon="🔑",
    )
    st.stop()

if config.INCIDENT_DATA_IS_SYNTHETIC:
    st.warning(
        "Risk scores below are computed against a **synthetic demo dataset** "
        "(`data/sample_synthetic_incidents.csv`), not real accident records. "
        "Treat the risk comparison as illustrative until a real dataset "
        "(e.g. a STRADA export) is wired in — see `data/README.md`.",
        icon="⚠️",
    )
else:
    _incidents = risk.load_incidents()
    _n_real = int((_incidents["source"] != "SYNTHETIC_SAMPLE").sum())
    _n_synthetic = int((_incidents["source"] == "SYNTHETIC_SAMPLE").sum())
    st.caption(
        f"Risk scores are computed from {_n_real} real Göteborg "
        "traffic-accident reports pulled from the Swedish Police open "
        "events API (`data/fetch_police_incidents.py`) — street and "
        "road-user type are extracted from free-text report summaries "
        "(heuristic, not guaranteed accurate) and geocoded via Nominatim; "
        "it's a rolling feed, not a full historical archive — "
        + (
            f"**plus {_n_synthetic} fabricated demo incidents** "
            "(🧪 marked, purple dashed markers on the map) added so route "
            "comparisons have more to work with. See `data/README.md`."
            if config.INCLUDE_SYNTHETIC_INCIDENTS and _n_synthetic
            else "so treat counts as indicative rather than exhaustive."
        )
    )

for key in ["start_point", "start_candidates", "dest_candidates", "dest_point", "awaiting_geo"]:
    st.session_state.setdefault(key, None)

# --- Start point --------------------------------------------------------

st.subheader("1. Start")
col_geo, col_manual = st.columns(2)

with col_geo:
    if st.button("📍 Use my current location"):
        st.session_state.awaiting_geo = True

    if st.session_state.awaiting_geo:
        location = get_geolocation()
        if location:
            coords = location["coords"]
            st.session_state.start_point = {
                "label": "My current location",
                "lat": coords["latitude"],
                "lon": coords["longitude"],
            }
            st.session_state.awaiting_geo = False
            st.rerun()
        else:
            st.info("Waiting for browser location permission…")

with col_manual:
    start_query = st.text_input("…or type a start address", key="start_query")
    if st.button("Find start address") and start_query:
        try:
            st.session_state.start_candidates = routing.geocode(start_query)
        except routing.RoutingError as exc:
            st.error(str(exc))

if st.session_state.get("start_candidates"):
    labels = [c["label"] for c in st.session_state.start_candidates]
    choice = st.selectbox("Match", labels, key="start_choice")
    if st.button("Set as start"):
        st.session_state.start_point = next(
            c for c in st.session_state.start_candidates if c["label"] == choice
        )
        st.session_state.start_candidates = None
        st.rerun()

if st.session_state.start_point:
    st.success(f"Start: {st.session_state.start_point['label']}")

# --- Destination ---------------------------------------------------------

st.subheader("2. Destination")
dest_query = st.text_input("Destination address", key="dest_query")
if st.button("Find destination") and dest_query:
    try:
        st.session_state.dest_candidates = routing.geocode(dest_query)
    except routing.RoutingError as exc:
        st.error(str(exc))

if st.session_state.dest_candidates:
    labels = [c["label"] for c in st.session_state.dest_candidates]
    choice = st.selectbox("Match", labels, key="dest_choice")
    if st.button("Set as destination"):
        st.session_state.dest_point = next(
            c for c in st.session_state.dest_candidates if c["label"] == choice
        )
        st.session_state.dest_candidates = None
        st.rerun()

if st.session_state.dest_point:
    st.success(f"Destination: {st.session_state.dest_point['label']}")

# --- Mode + route ----------------------------------------------------------

st.subheader("3. Compare routes")
profile_key = st.radio("Mode", list(config.ROUTE_PROFILES), horizontal=True)

ready = st.session_state.start_point and st.session_state.dest_point
if st.button("Find routes", type="primary", disabled=not ready):
    start = st.session_state.start_point
    dest = st.session_state.dest_point
    try:
        with st.spinner("Requesting routes and scoring risk…"):
            fast, safe, _all = routing.get_fast_and_safe_routes(
                profile_key,
                (start["lat"], start["lon"]),
                (dest["lat"], dest["lon"]),
            )
        st.session_state.fast_route = fast
        st.session_state.safe_route = safe
    except routing.RoutingError as exc:
        st.error(str(exc))

if not ready:
    st.caption("Set a start point and a destination above to compare routes.")

# --- Results ---------------------------------------------------------------

fast = st.session_state.get("fast_route")
safe = st.session_state.get("safe_route")

if fast and safe:
    same_route = fast is safe or fast["coordinates"] == safe["coordinates"]

    fast_min = round(fast["duration_s"] / 60)
    safe_min = round(safe["duration_s"] / 60)

    col_fast, col_safe = st.columns(2)
    with col_fast:
        st.markdown("#### 🚗 Fastest route")
        st.metric("Duration", f"{fast_min} min")
        st.metric("Distance", f"{fast['distance_m'] / 1000:.1f} km")
        st.metric("Risk level", f"{fast['risk']['risk_percent']:.0f}%")
        st.caption(
            f"{risk.risk_level_label(fast['risk']['risk_percent'])} · "
            f"{fast['risk']['incident_count']} nearby incident(s) in dataset"
        )
        if fast["risk"]["breakdown_by_road_user"]:
            st.bar_chart(fast["risk"]["breakdown_by_road_user"])

    with col_safe:
        st.markdown("#### 🛡️ Lower-risk route")
        if same_route:
            st.info("No distinct lower-risk alternative was found — showing the same route.")
        st.metric(
            "Duration", f"{safe_min} min",
            delta=f"{safe_min - fast_min:+d} min", delta_color="inverse",
        )
        st.metric("Distance", f"{safe['distance_m'] / 1000:.1f} km")
        risk_delta = safe["risk"]["risk_percent"] - fast["risk"]["risk_percent"]
        st.metric(
            "Risk level", f"{safe['risk']['risk_percent']:.0f}%",
            delta=f"{risk_delta:+.0f} pts", delta_color="inverse",
        )
        st.caption(
            f"{risk.risk_level_label(safe['risk']['risk_percent'])} · "
            f"{safe['risk']['incident_count']} nearby incident(s) in dataset"
        )
        if safe["risk"]["breakdown_by_road_user"]:
            st.bar_chart(safe["risk"]["breakdown_by_road_user"])

    # --- Map ---
    all_coords = fast["coordinates"] + safe["coordinates"]
    lats = [c[0] for c in all_coords]
    lons = [c[1] for c in all_coords]
    m = folium.Map(location=[sum(lats) / len(lats), sum(lons) / len(lons)], zoom_start=13)
    m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])

    folium.Marker(
        (st.session_state.start_point["lat"], st.session_state.start_point["lon"]),
        tooltip="Start",
        icon=folium.Icon(color="blue", icon="play"),
    ).add_to(m)
    folium.Marker(
        (st.session_state.dest_point["lat"], st.session_state.dest_point["lon"]),
        tooltip="Destination",
        icon=folium.Icon(color="red", icon="flag"),
    ).add_to(m)

    folium.PolyLine(
        fast["coordinates"], color="#1f77b4", weight=5, opacity=0.85, tooltip="Fastest route"
    ).add_to(m)
    if not same_route:
        folium.PolyLine(
            safe["coordinates"], color="#2ca02c", weight=5, opacity=0.85, tooltip="Lower-risk route"
        ).add_to(m)

    seen_ids = set()
    for route in (fast, safe):
        for row in route["risk"]["incidents"]:
            if row["id"] in seen_ids:
                continue
            seen_ids.add(row["id"])
            desc = risk.incident_marker_style(row)
            folium.CircleMarker(
                (row["lat"], row["lon"]),
                radius=5,
                tooltip=desc["tooltip"],
                popup=desc["popup"],
                **desc["style"],
            ).add_to(m)

    st_folium(m, width=None, height=550, use_container_width=True)
