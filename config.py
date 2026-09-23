"""Shared constants and config for the Gothenburg Traffic Safety app."""

import os

from dotenv import load_dotenv

load_dotenv()

# Rough bounding box for Gothenburg municipality, used to center the map
# and to constrain geocoding / routing queries to the area we care about.
GOTHENBURG_CENTER = (57.7089, 11.9746)  # lat, lon
GOTHENBURG_BOUNDS = {
    "min_lat": 57.60,
    "max_lat": 57.80,
    "min_lon": 11.80,
    "max_lon": 12.10,
}
DEFAULT_ZOOM = 12

# Road user types we track interactions between.
ROAD_USER_TYPES = ["Car", "Bus", "Tram", "Cyclist", "Pedestrian"]

# Near-miss / conflict categories (extend as needed).
CONFLICT_TYPES = [
    "Close pass",
    "Blocked crosswalk / bike lane",
    "Red-light / stop-sign conflict",
    "Dooring",
    "Blind-spot / merge conflict",
    "Other",
]

# --- Route Check ------------------------------------------------------

OPENROUTESERVICE_API_KEY = os.getenv("OPENROUTESERVICE_API_KEY", "")
ORS_BASE_URL = "https://api.openrouteservice.org"

# ORS routing profile per road-user mode offered on the Route Check page.
ROUTE_PROFILES = {
    "Car": "driving-car",
    "Bicycle": "cycling-regular",
    "Pedestrian": "foot-walking",
}

# Incident data used to score route risk. Real data extracted from the
# Swedish Police open events API — see data/fetch_police_incidents.py for
# how it's pulled/geocoded and its limitations (rolling feed, heuristic
# street/road-user extraction).
INCIDENT_DATA_PATH = "data/police_incidents_gothenburg.csv"
INCIDENT_DATA_IS_SYNTHETIC = False

# The real feed above is currently thin (a few dozen citywide), which makes
# most routes look identically risk-free. To get more meaningful route
# comparisons, risk.load_incidents() also merges in fabricated demo data
# from this file -- every row is tagged source=SYNTHETIC_SAMPLE and its id
# is prefixed "SYN-" so it's always distinguishable from real reports (in
# code, in the CSV, and in the UI, where synthetic markers get a different
# color + dashed outline and an explicit "Simulated" label). Set this to
# False once real coverage is dense enough to stand on its own.
INCLUDE_SYNTHETIC_INCIDENTS = True
SYNTHETIC_INCIDENT_DATA_PATH = "data/sample_synthetic_incidents.csv"

# How far (meters) from the route centerline an incident still counts
# toward that route's risk score.
RISK_BUFFER_METERS = 60

# Severity weights used when aggregating incidents into a risk score.
SEVERITY_WEIGHTS = {
    "fatal": 5,
    "severe": 3,
    "minor": 1,
}

# Weighted incidents per km at which the 0-100% risk score saturates
# noticeably (score_per_km == RISK_PCT_SCALE -> ~63% risk). See
# risk.score_route for the saturating-curve formula.
RISK_PCT_SCALE = 2.0

# Half-width (meters) of the square "avoid zone" built around each known
# incident when requesting a route that actively routes around them.
AVOID_POLYGON_HALF_WIDTH_M = 35
