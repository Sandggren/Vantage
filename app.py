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
)

folium.Marker(
    location=GOTHENBURG_CENTER,
    tooltip="Gothenburg city center",
    icon=folium.Icon(color="blue", icon="info-sign"),
).add_to(m)

# --- Traffic incidents (real police reports + synthetic demo data) ----
try:
    incidents_df = risk.load_incidents()
except (FileNotFoundError, ValueError):
    incidents_df = None

if incidents_df is not None:
    for _, row in incidents_df.iterrows():
        desc = risk.incident_marker_style(row)
        folium.CircleMarker(
            (row["lat"], row["lon"]),
            radius=5,
            tooltip=desc["tooltip"],
            popup=desc["popup"],
            **desc["style"],
        ).add_to(m)

st_folium(m, width=None, height=600, use_container_width=True)

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
