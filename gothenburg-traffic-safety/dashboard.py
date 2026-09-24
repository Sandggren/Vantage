"""
Gothenburg Traffic Safety — Dashboard page.

Shown as "Dashboard" in the sidebar (see app.py). Renders an interactive
map of Gothenburg (traffic flows + accidents) with a details panel beside
it for whichever accident is clicked.
Next steps (see the other pages in `app_pages/`) will add:
  - a near-miss reporting form
  - route risk-checking via the OpenRouteService API
  - near-miss reports feeding into the accident hotspot layer
  - a Vasttrafik bus/tram layer
"""

import folium
from branca.element import MacroElement
from folium.plugins import HeatMap
from jinja2 import Template
import streamlit as st
from streamlit_folium import st_folium

import config
import risk
import traffic_flow
from config import DEFAULT_ZOOM, GOTHENBURG_CENTER
from geo_utils import haversine_m

st.set_page_config(
    page_title="Vantage · Gothenburg Traffic Safety",
    page_icon=config.LOGO_ICON_PATH,
    layout="wide",
)

logo_col, title_col = st.columns([1, 8], vertical_alignment="center")
with logo_col:
    st.image(config.LOGO_PATH, width=110)
with title_col:
    st.title("Gothenburg Traffic Safety")
    st.caption(
        "A crowdsourced near-miss reporting and mapping tool for mixed traffic "
        "in Gothenburg — cars, buses, trams, cyclists, and pedestrians."
    )

# --- Base map ---------------------------------------------------------
m = folium.Map(
    location=GOTHENBURG_CENTER,
    zoom_start=DEFAULT_ZOOM,
    tiles="OpenStreetMap",
    prefer_canvas=True,  # much faster with hundreds of road segments
    control_scale=True,
)

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
# Warm colors for real accident hotspots: pale yellow → orange → deep
# orange. No purple (that marks demo data) and short of the dark reds used
# for road traffic, so a hotspot can't be mistaken for either.
HEAT_GRADIENT = {0.2: "#ffe98a", 0.45: "#ffc233", 0.7: "#ff8c1a", 1.0: "#e8590c"}
HEAT_RADIUS_PX = 24
# Severity points (minor 1, severe 3, fatal 5) at one spot that reach the
# hottest color -- i.e. 3 minor accidents or 1 severe one.
HEAT_HOTTEST_AT = 3
# Clicking the map shows accidents within HOTSPOT_RADIUS_M of the accident
# nearest the click, if that one is within CLICK_SEARCH_M.
HOTSPOT_RADIUS_M = 250
CLICK_SEARCH_M = 500
try:
    incidents_df = risk.load_incidents()
except (FileNotFoundError, ValueError):
    incidents_df = None

if incidents_df is not None:
    # Draw demo (purple) incidents first so real police reports sit on top and
    # stay clickable where the two overlap (e.g. around Brunnsparken).
    incidents_df = incidents_df.sort_values(
        "source", key=lambda s: s != "SYNTHETIC_SAMPLE", kind="stable"
    ).reset_index(drop=True)
    # --- Accident hotspots (heat map) ---
    # Each accident adds heat weighted by severity (minor 1, severe 3,
    # fatal 5 -- config.SEVERITY_WEIGHTS), so a spot gets warmer the more
    # (and the worse) accidents there are. Real police reports and the
    # fabricated demo incidents get separate layers (same warm colors) so
    # fake data only shows up as a hotspot when that layer is switched on;
    # only the real one is on by default. Demo incidents are told apart by
    # their purple dots under ⚠️ Accident points.
    is_synthetic = incidents_df["source"] == "SYNTHETIC_SAMPLE"
    for name, subset, show, gradient in [
        ("🔥 Accident hotspots (police reports)", incidents_df[~is_synthetic], True, HEAT_GRADIENT),
        ("🔥 More accident hotspots", incidents_df[is_synthetic], False, HEAT_GRADIENT),
    ]:
        points = [
            [r["lat"], r["lon"], config.SEVERITY_WEIGHTS.get(str(r["severity"]).lower(), 1) / HEAT_HOTTEST_AT]
            for _, r in subset.iterrows()
        ]
        if not points:
            continue
        heat_layer = folium.FeatureGroup(name=name, show=show)
        HeatMap(
            points,
            radius=HEAT_RADIUS_PX,
            blur=18,
            min_opacity=0.5,
            max_zoom=DEFAULT_ZOOM,  # full intensity from the starting zoom inwards
            gradient=gradient,
        ).add_to(heat_layer)
        heat_layer.add_to(m)

    # Individual accidents as dots -- off by default (the hotspots give the
    # overview). Details come from clicking the map anywhere near them, see
    # clicked_incidents().
    incident_layer = folium.FeatureGroup(name="⚠️ Accident points", show=False)
    # Own pane above the heat map (and road lines), so the purple demo dots
    # keep their color instead of being tinted by the hotspots underneath.
    # pointer_events=True: folium panes ignore the mouse by default, which
    # made the dots unclickable and without hover text.
    folium.map.CustomPane("accident-dots", z_index=450, pointer_events=True).add_to(m)
    for _, row in incidents_df.iterrows():
        desc = risk.incident_marker_style(row)
        dot = folium.CircleMarker(
            (row["lat"], row["lon"]),
            radius=6,
            tooltip=desc["tooltip"],
            **desc["style"],
        )
        dot.options["pane"] = "accident-dots"  # folium drops a pane= argument
        dot.add_to(incident_layer)
    incident_layer.add_to(m)

folium.LayerControl(collapsed=True, position="topright").add_to(m)
heat_legend = (
    '<div style="margin-top:6px"><b>Accident hotspots</b></div>'
    '<div style="height:8px;width:120px;border-radius:4px;background:linear-gradient(90deg,'
    + ",".join(HEAT_GRADIENT.values())
    + ')"></div><div style="display:flex;justify-content:space-between;width:120px">'
    "<span>fewer</span><span>more</span></div>"
    '<div style="margin-top:4px"><span style="display:inline-block;width:12px;height:12px;'
    'border-radius:50%;background:' + risk.SYNTHETIC_COLOR + ';vertical-align:middle;'
    'margin:0 6px 0 1px"></span>Purple = demo data</div>'
)
m.get_root().html.add_child(folium.Element(traffic_flow.legend_html(extra_html=heat_legend)))
# Hover texts can't be layered above the legend (Leaflet keeps them inside
# the map), so fade the legend while one is showing to keep it readable.
# Attached to the map itself: streamlit-folium only renders the map's own
# scripts, not ones added to the surrounding page.
class FadeLegendOnHover(MacroElement):
    _template = Template("""
        {% macro script(this, kwargs) %}
        {{ this._parent.get_name() }}.on("tooltipopen", function () {
            var legend = document.getElementById("map-legend");
            if (legend) legend.style.opacity = "0.12";
        });
        {{ this._parent.get_name() }}.on("tooltipclose", function () {
            var legend = document.getElementById("map-legend");
            if (legend) legend.style.opacity = "1";
        });
        {% endmacro %}
    """)


FadeLegendOnHover().add_to(m)
# The heat map has its own canvas: keep it above the road lines so hotspots
# on busy roads stay visible, and let clicks pass through it to the map.
m.get_root().header.add_child(
    folium.Element("<style>.leaflet-heatmap-layer { pointer-events: none; z-index: 2; }</style>")
)



def latest_click(map_state):
    """(lat, lon) of the user's most recent click on the map, or None.

    streamlit-folium reports a click on empty map as `last_clicked` but a
    click on a drawn object (a road line, bike circle, accident dot) only as
    `last_object_clicked` -- and hotspots mostly sit on roads. Whichever of
    the two changed since the previous run is the new click.
    """
    map_state = map_state or {}
    previous = st.session_state.get("dashboard_prev_clicks", {})
    for key in ("last_clicked", "last_object_clicked"):
        value = map_state.get(key)
        if value and value != previous.get(key):
            st.session_state.dashboard_click = (value["lat"], value["lng"])
    st.session_state.dashboard_prev_clicks = {
        k: map_state.get(k) for k in ("last_clicked", "last_object_clicked")
    }
    return st.session_state.get("dashboard_click")


def clicked_incidents(click_pt, incidents):
    """Accidents at the hotspot nearest to where the user last clicked the
    map, or an empty frame.

    Works on a plain map click (not just clicks on the dots, which are
    hidden by default): find the accident nearest the click, and if it's
    within CLICK_SEARCH_M, return every accident within HOTSPOT_RADIUS_M of
    it -- roughly one hotspot blob at the default zoom. Sorted nearest to
    the click first, so the dot that was clicked is at the top.
    """
    if incidents is None:
        return None
    if not click_pt:
        return incidents.iloc[0:0]

    distances = incidents.apply(lambda r: haversine_m(click_pt, (r["lat"], r["lon"])), axis=1)
    if distances.min() > CLICK_SEARCH_M:
        return incidents.iloc[0:0]
    nearest = incidents.loc[distances.idxmin()]
    anchor = (nearest["lat"], nearest["lon"])
    in_hotspot = incidents[
        incidents.apply(lambda r: haversine_m(anchor, (r["lat"], r["lon"])) <= HOTSPOT_RADIUS_M, axis=1)
    ]
    # Nearest to the click first, so a clicked dot is always at the top.
    return in_hotspot.assign(
        _dist=distances.reindex(in_hotspot.index)
    ).sort_values("_dist", kind="stable").drop(columns="_dist")


def show_incident_details(row):
    is_synthetic = row.get("source") == "SYNTHETIC_SAMPLE"
    with st.container(border=True):
        # Demo (fabricated) incidents: purple dot in the heading, matching
        # their purple map marker. They have no time or police report.
        marker = "🟣 " if is_synthetic else ""
        st.markdown(f"**{marker}{risk.accident_type_label(row.get('road_users'))}**")
        if is_synthetic:
            near = row.get("near")
            if isinstance(near, str) and near.strip():
                st.markdown(f"**Where:** {near if near == 'Citywide' else 'near ' + near}")
            st.markdown(f"**Severity:** {str(row.get('severity', '')).title()}")
            return

        if isinstance(row.get("street"), str):
            st.markdown(f"**Where:** {row['street']}")
        happened = risk.incident_happened_at(row)
        if happened:
            st.markdown(f"**When it happened:** {risk.format_when(happened)}")
        if isinstance(row.get("datetime"), str):
            st.caption(f"Reported by the police: {row['datetime'].rsplit(' ', 1)[0]}")
        st.markdown(
            f"**Severity:** {str(row.get('severity', '')).title()} "
            "<span style='opacity:.6'>(estimated from the report text)</span>",
            unsafe_allow_html=True,
        )
        if isinstance(row.get("summary"), str) and row["summary"].strip():
            st.markdown("**Police report:**")
            st.markdown(f"> {row['summary']}")
        if isinstance(row.get("url"), str) and row["url"].startswith("http"):
            st.link_button("Read the full report on polisen.se ↗", row["url"])


map_col, info_col = st.columns([3, 2], gap="medium")

with map_col:
    # Only the click position is sent back, so panning/zooming doesn't
    # rerun the page -- clicking does, to fill in the details panel.
    map_state = st_folium(
        m,
        width=None,
        height=560,
        use_container_width=True,
        returned_objects=["last_clicked", "last_object_clicked"],
        key="dashboard_map",
    )

with info_col:
    st.subheader("Accident details")
    selected = clicked_incidents(latest_click(map_state), incidents_df)
    if incidents_df is None:
        st.info("No accident data loaded.")
    elif selected is None or selected.empty:
        st.info(
            "Click a hotspot on the map to see the accidents there. To see "
            "each accident as a dot, turn on **⚠️ Accident points** in the "
            "map menu (top right).",
            icon="👆",
        )
    else:
        if len(selected) > 1:
            n_sim = int((selected["source"] == "SYNTHETIC_SAMPLE").sum())
            breakdown = f" ({len(selected) - n_sim} from police reports, {n_sim} 🟣)" if n_sim else ""
            st.caption(f"{len(selected)} accidents in this hotspot{breakdown}, nearest to your click first:")
        with st.container(height=420 if len(selected) > 1 else "content", border=False):
            for _, row in selected.iterrows():
                show_incident_details(row)

    if incidents_df is not None:
        real = incidents_df[incidents_df["source"] != "SYNTHETIC_SAMPLE"].copy()
        real["happened"] = [risk.incident_happened_at(r) for _, r in real.iterrows()]
        latest = real.dropna(subset=["happened"]).sort_values("happened", ascending=False).head(5)
        if not latest.empty:
            st.subheader("Latest police reports")
            for _, row in latest.iterrows():
                label = risk.accident_type_label(row.get("road_users"))
                where = f" — {row['street']}" if isinstance(row.get("street"), str) else ""
                link = f" · [report ↗]({row['url']})" if isinstance(row.get("url"), str) and row["url"] else ""
                st.markdown(f"**{risk.format_when(row['happened'])}** · {label}{where}{link}")

if incidents_df is None:
    st.info(
        "No incident data found yet. Run `python data/fetch_police_incidents.py` "
        "to pull recent Göteborg traffic-accident reports and plot them here.",
        icon="ℹ️",
    )
