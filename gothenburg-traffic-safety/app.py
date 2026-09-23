"""
Gothenburg Traffic Safety — Home / Map page.

This is the entry point for the Streamlit app. Right now it just renders
an interactive map of Gothenburg so we have a working base to build on.
Next steps (see the other pages in `pages/`) will add:
  - a near-miss reporting form
  - route risk-checking via the OpenRouteService API
  - a hotspot/heatmap layer built from reported near-misses
  - a Vasttrafik bus/tram layer
"""

import folium
import streamlit as st
from streamlit_folium import st_folium

import risk
import traffic_flow
from config import DEFAULT_ZOOM, GOTHENBURG_CENTER

st.set_page_config(
    page_title="Gothenburg Traffic Safety",
    page_icon="🚦",
    layout="wide",
)

st.title("🚦 Gothenburg Traffic Safety")
st.caption(
    "A crowdsourced near-miss reporting and mapping tool for mixed traffic "
    "in Gothenburg — cars, buses, trams, cyclists, and pedestrians."
)

with st.sidebar:
    st.header("Project roadmap")
    st.markdown(
        "- [x] Base map of Gothenburg\n"
        "- [x] Vehicle & bicycle traffic flow\n"
        "- [ ] Report a near-miss\n"
        "- [ ] Route risk-check (OpenRouteService)\n"
        "- [ ] Hotspot heatmap\n"
        "- [ ] Bus/tram layer (Vasttrafik GTFS)\n"
        "- [ ] Planner dashboard"
    )
    st.divider()
    st.caption("Use the pages in the left-hand nav to jump between sections.")

# --- Base map ---------------------------------------------------------
m = folium.Map(
    location=GOTHENBURG_CENTER,
    zoom_start=DEFAULT_ZOOM,
    tiles="OpenStreetMap",
    prefer_canvas=True,  # much faster with hundreds of road segments
    control_scale=True,
)

folium.Marker(
    location=GOTHENBURG_CENTER,
    tooltip="Gothenburg city center",
    icon=folium.Icon(color="blue", icon="info-sign"),
).add_to(m)

# --- 🚗 Vehicle traffic flow (Trafikverket) ---------------------------
# Added before incidents so incident markers are drawn on top of the roads.
vehicle_layer = folium.FeatureGroup(name="🚗 Vehicle traffic flow", show=True)
try:
    vehicle_flows = traffic_flow.load_vehicle_flows()
except Exception as e:  # network / API errors shouldn't take the page down
    vehicle_flows = None
    st.warning(f"Vehicle traffic data could not be loaded from Trafikverket: {e}", icon="⚠️")

if vehicle_flows is not None:
    folium.GeoJson(
        vehicle_flows,
        style_function=traffic_flow.vehicle_flow_style,
        highlight_function=lambda _: {"weight": 9, "opacity": 1},
        tooltip=folium.GeoJsonTooltip(
            fields=["AADT_TOT", "VAEG_NUM", "AAR", "DATA_TYPE"],
            aliases=["Vehicles/day:", "Road:", "Year:", "Data:"],
            localize=True,
            sticky=True,
        ),
    ).add_to(vehicle_layer)
vehicle_layer.add_to(m)

# --- 🚲 Bicycle traffic flow -------------------------------------------
bike_layer = folium.FeatureGroup(name="🚲 Bicycle traffic flow", show=True)
unverified_note = "" if traffic_flow.BIKE_DATA_VERIFIED else " (unverified sample figure)"
for station in traffic_flow.BIKE_COUNT_STATIONS:
    folium.CircleMarker(
        (station["lat"], station["lon"]),
        radius=traffic_flow.bike_marker_radius(station["flow"]),
        color=traffic_flow.BIKE_COLOR,
        weight=2,
        fill=True,
        fill_color=traffic_flow.BIKE_COLOR,
        fill_opacity=0.75,
        tooltip=f"🚲 {station['name']} – {station['flow']:,} bicycles/weekday{unverified_note}",
        popup=folium.Popup(
            f"<b>🚲 {station['name']}</b><br>"
            f"{station['flow']:,} bicycles/weekday ({station['year']})<br>"
            f"<i>Göteborgs Stad counting station{unverified_note}</i>",
            max_width=300,
        ),
    ).add_to(bike_layer)
bike_layer.add_to(m)

# --- Traffic incidents (real police reports + synthetic demo data) ----
try:
    incidents_df = risk.load_incidents()
except (FileNotFoundError, ValueError):
    incidents_df = None

if incidents_df is not None:
    incident_layer = folium.FeatureGroup(name="⚠️ Traffic incidents", show=True)
    for _, row in incidents_df.iterrows():
        desc = risk.incident_marker_style(row)
        folium.CircleMarker(
            (row["lat"], row["lon"]),
            radius=5,
            tooltip=desc["tooltip"],
            popup=desc["popup"],
            **desc["style"],
        ).add_to(incident_layer)
    incident_layer.add_to(m)

folium.LayerControl(collapsed=False, position="topright").add_to(m)
m.get_root().html.add_child(folium.Element(traffic_flow.legend_html()))

# returned_objects=[]: nothing reads map state back, so don't rerun the
# whole script every time the user pans or zooms.
st_folium(m, width=None, height=600, use_container_width=True, returned_objects=[])

st.caption(
    "🚗 **Vehicle traffic flow** — annual average vehicles/day on state roads "
    "(Trafikverket). Darker, thicker red = more traffic. Municipal city streets "
    "aren't included in Trafikverket's data. Traffic volume alone does not mean "
    "accident risk. 🚲 **Bicycle flow** — larger circle = more cyclists. "
    "Use the menu in the top-right corner to show or hide layers."
)

if incidents_df is not None:
    n_real = int((incidents_df["source"] != "SYNTHETIC_SAMPLE").sum())
    n_synthetic = int((incidents_df["source"] == "SYNTHETIC_SAMPLE").sum())
    st.caption(
        f"Showing {n_real} real Göteborg traffic-accident reports from the Swedish "
        "Police open events API (street/road-user extraction is heuristic, and "
        "it's a rolling feed, not a full historical archive — see "
        "`data/fetch_police_incidents.py`) plus "
        f"**{n_synthetic} fabricated demo incidents** (🧪 purple, dashed outline) "
        "added so route comparisons have more to work with — see `data/README.md`."
    )
else:
    st.info(
        "No incident data found yet. Run `python data/fetch_police_incidents.py` "
        "to pull recent Göteborg traffic-accident reports and plot them here.",
        icon="ℹ️",
    )

st.info(
    "Reporting and the hotspot heatmap layer will build on top of this next — "
    "see `.env.example` for what's needed for routing/transit.",
    icon="ℹ️",
)
