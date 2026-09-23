"""Report a Near-Miss — click the map (or use GPS / type an address) to set
where it happened, then fill in the form beside the map.

Reports are saved locally to a CSV file (see near_miss.py), not a database.
Every report gets map coordinates: from the map click, the browser's GPS,
or by looking up the typed address (OpenRouteService).
"""

import folium
import streamlit as st
from streamlit_folium import st_folium
from streamlit_js_eval import get_geolocation

import config
import near_miss
import routing

st.set_page_config(
    page_title="Vantage · Report a Near-Miss",
    page_icon=config.LOGO_ICON_PATH,
    layout="wide",
)

st.title("⚠️ Report a Near Miss")
st.caption(
    "Help us identify traffic safety issues that may not appear in official reports. "
    "Click the map where it happened, then fill in the form."
)

# Form label -> stored value. Stored values match the road-user names used
# in the incident data (config.ROAD_USER_TYPES), so reports can later feed
# into the same maps and risk scoring.
ROAD_USER_OPTIONS = {
    "Cyclist": "Cyclist",
    "Pedestrian": "Pedestrian",
    "Driver": "Car",
    "Bus": "Bus",
    "Tram": "Tram",
    "Other": "Other",
}

# ---------------------------------------------------------
# SESSION STATE
# ---------------------------------------------------------

if "report_location" not in st.session_state:
    # {"lat", "lon", "source": "map" | "gps", "label": address or None}
    st.session_state.report_location = None

if "getting_location" not in st.session_state:
    st.session_state.getting_location = False

if "form_version" not in st.session_state:
    st.session_state.form_version = 0

if "success_message" not in st.session_state:
    st.session_state.success_message = None

if "report_map_prev_clicks" not in st.session_state:
    st.session_state.report_map_prev_clicks = {}


def set_location(lat, lon, source):
    """Store the chosen point plus its nearest address (best effort)."""
    try:
        label = routing.reverse_geocode(lat, lon)
    except routing.RoutingError:
        label = None
    st.session_state.report_location = {"lat": lat, "lon": lon, "source": source, "label": label}


# ---------------------------------------------------------
# SUCCESS MESSAGE
# ---------------------------------------------------------

if st.session_state.success_message:

    st.success(st.session_state.success_message)

    # Only show the message once
    st.session_state.success_message = None


reports = near_miss.load_reports()

map_col, form_col = st.columns([3, 2], gap="medium")

# ---------------------------------------------------------
# MAP — click to choose the location
# ---------------------------------------------------------

with map_col:

    m = folium.Map(
        location=config.GOTHENBURG_CENTER,
        zoom_start=13,
        tiles="OpenStreetMap",
        control_scale=True,
    )

    # Earlier reports as small dots, for context.
    for _, r in reports.dropna(subset=["lat", "lon"]).iterrows():
        ts = r["timestamp"]
        when = f"{ts.day} {ts:%b %Y}" if hasattr(ts, "strftime") else ""
        folium.CircleMarker(
            (r["lat"], r["lon"]),
            radius=5,
            color="#e76f51",
            weight=2,
            fill=True,
            fill_opacity=0.6,
            tooltip=f"Earlier report: {r['type']} · {when}",
        ).add_to(m)

    # The chosen location is drawn as a separate layer, so moving the
    # marker doesn't redraw the whole map (and reset its zoom/position).
    chosen = folium.FeatureGroup(name="Chosen location")
    loc = st.session_state.report_location
    if loc:
        folium.Marker(
            (loc["lat"], loc["lon"]),
            tooltip="Report location",
            icon=folium.Icon(color="red", icon="exclamation-sign"),
        ).add_to(chosen)

    map_state = st_folium(
        m,
        feature_group_to_add=chosen,
        # Jump to a GPS fix; map clicks leave the view where it is.
        center=(loc["lat"], loc["lon"]) if loc and loc["source"] == "gps" else None,
        width=None,
        height=600,
        use_container_width=True,
        returned_objects=["last_clicked", "last_object_clicked"],
        key="report_map",
    )

    # A click on empty map comes back as last_clicked, a click on a drawn
    # marker as last_object_clicked; whichever changed is the new click.
    map_state = map_state or {}
    previous = st.session_state.report_map_prev_clicks
    new_click = None
    for key in ("last_clicked", "last_object_clicked"):
        value = map_state.get(key)
        if value and value != previous.get(key):
            new_click = value
    st.session_state.report_map_prev_clicks = {
        k: map_state.get(k) for k in ("last_clicked", "last_object_clicked")
    }
    if new_click:
        set_location(new_click["lat"], new_click["lng"], "map")
        st.rerun()

# ---------------------------------------------------------
# FORM — location + what happened
# ---------------------------------------------------------

with form_col:

    st.subheader("1. Where did it happen?")

    loc = st.session_state.report_location

    if loc:

        place = loc["label"] or f"{loc['lat']:.5f}, {loc['lon']:.5f}"
        how = "clicked on the map" if loc["source"] == "map" else "your current location"
        st.success(f"📍 **{place}** ({how})")

    else:

        st.info("👈 Click the map where it happened.")

    gps_col, clear_col = st.columns(2)

    with gps_col:

        if st.button("📍 My location", width="stretch", help="Use your current GPS location"):

            st.session_state.getting_location = True

    with clear_col:

        if loc and st.button("Clear location", width="stretch"):

            st.session_state.report_location = None
            st.rerun()

    if st.session_state.getting_location:

        location = get_geolocation()

        if location:

            coords = location["coords"]

            set_location(coords["latitude"], coords["longitude"], "gps")

            st.session_state.getting_location = False

            st.rerun()

        else:

            st.info("Waiting for browser location permission…")

    manual_location = st.text_input(
        "✏️ …or type a location",
        placeholder="e.g. Vasagatan & Kungsportsavenyen",
        key=f"location_{st.session_state.form_version}",
        help="Only used if no point is chosen on the map.",
    )

    with st.form(f"near_miss_form_{st.session_state.form_version}"):

        st.subheader("2. What happened?")

        incident_type = st.radio(
            "Type of report",
            [
                "Near miss",
                "Hazard",
                "Collision"
            ],
            horizontal=True
        )

        road_users = st.multiselect(
            "Who was involved?",
            list(ROAD_USER_OPTIONS)
        )

        severity = st.select_slider(
            "How serious was it?",
            options=[
                "Low",
                "Moderate",
                "High"
            ],
            value="Moderate"
        )

        description = st.text_area(
            "What happened?",
            placeholder=(
                "Briefly describe what happened, for example: "
                "A car turned right while a cyclist was crossing."
            ),
            max_chars=500
        )

        submitted = st.form_submit_button(
            "🚨 Submit report",
            type="primary",
            width="stretch",
        )

    # ---------------------------------------------------------
    # SUBMISSION
    # ---------------------------------------------------------

    if submitted:

        location = st.session_state.report_location

        # Validation

        if not location and not manual_location.strip():

            st.error("Please click the map, use your current location, or type a location.")

        elif not road_users:

            st.error("Please select at least one road user.")

        elif not description.strip():

            st.error("Please describe what happened.")

        else:

            # Resolve the location to coordinates. A point from the map or
            # GPS wins; otherwise look up the typed address in Gothenburg.

            location_ok = True

            if location:

                lat, lon, source = location["lat"], location["lon"], location["source"]
                where = location["label"] or "the chosen location"
                location_text = manual_location.strip() or (location["label"] or "")

            else:

                try:
                    match = routing.geocode(manual_location, size=1)[0]
                    lat, lon, source = match["lat"], match["lon"], "address"
                    where = match["label"]
                    location_text = manual_location
                except routing.RoutingError as exc:
                    location_ok = False
                    st.error(
                        f"Couldn't find “{manual_location}” on the map: {exc} "
                        "Try a street name or landmark in Gothenburg, or click "
                        "the map instead."
                    )

            if location_ok:

                # Save to the local reports file

                near_miss.save_report(
                    report_type=incident_type,
                    road_users=[ROAD_USER_OPTIONS[u] for u in road_users],
                    severity=severity,
                    description=description,
                    location_text=location_text,
                    lat=lat,
                    lon=lon,
                    location_source=source,
                )

                # Clear location

                st.session_state.report_location = None

                # Tell next run to show success message

                st.session_state.success_message = (
                    f"✅ Report received — saved at {where}. "
                    "Thank you for helping improve traffic safety!"
                )

                # Create a completely new form

                st.session_state.form_version += 1

                # Reload page

                st.rerun()


# ---------------------------------------------------------
# SAVED REPORTS
# ---------------------------------------------------------

st.divider()

st.subheader(f"Saved reports ({len(reports)})")

if reports.empty:

    st.caption("No reports yet — they'll show up here and on the map once submitted.")

else:

    st.caption(
        "Stored on this computer in `data/near_miss_reports.csv` "
        "(not shared with other computers)."
    )

    st.dataframe(
        reports[["timestamp", "type", "road_users", "severity", "description", "location_text", "lat", "lon"]],
        column_config={
            "timestamp": st.column_config.DatetimeColumn("When reported", format="D MMM YYYY, HH:mm"),
            "type": "Type",
            "road_users": "Who was involved",
            "severity": "Severity",
            "description": "What happened",
            "location_text": "Location",
            "lat": st.column_config.NumberColumn("Lat", format="%.5f"),
            "lon": st.column_config.NumberColumn("Lon", format="%.5f"),
        },
        hide_index=True,
        width="stretch",
    )
