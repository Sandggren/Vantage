"""Geocoding and route alternatives via the OpenRouteService (ORS) API."""

import requests

import config
import risk
import traffic_flow
from geo_utils import haversine_m, square_ring_lonlat

AVOID_FEATURES_BY_PROFILE = {
    "driving-car": ["highways", "tollways"],
    "cycling-regular": ["steps"],
    "foot-walking": ["steps"],
}


class RoutingError(Exception):
    """Raised for user-facing routing/geocoding failures (bad key, no route, etc)."""


def _require_api_key():
    if not config.OPENROUTESERVICE_API_KEY:
        raise RoutingError(
            "No OpenRouteService API key configured. Add "
            "OPENROUTESERVICE_API_KEY to your .env file (see .env.example)."
        )


def key_summary():
    """Safe-to-show fingerprint of the key in use, for comparing between
    computers without revealing the key itself."""
    key = config.OPENROUTESERVICE_API_KEY
    source = f".env at {config.ENV_PATH}" if config.ENV_FILE_FOUND else "environment (no .env file found)"
    if key == "your_key_here":
        return f"Key in use is still the placeholder `your_key_here` (from {source})."
    return f"Key in use: {len(key)} characters, starts `{key[:4]}`, ends `{key[-4:]}` (from {source})."


def _raise_for_ors_error(resp):
    if resp.status_code == 401:
        raise RoutingError(f"OpenRouteService rejected the API key (401). {key_summary()}")
    if resp.status_code == 403:
        # ORS uses 403 both for a used-up daily quota and for a key that
        # isn't allowed to use this endpoint -- include its reason.
        raise RoutingError(
            "OpenRouteService refused the request (403): "
            f"{resp.text[:200] or 'no reason given'}. This usually means the key "
            "is wrong or its daily quota is used up — check it at "
            f"https://openrouteservice.org/dev/#/home. {key_summary()}"
        )
    if resp.status_code == 429:
        raise RoutingError("OpenRouteService rate limit hit — wait a moment and try again.")
    if not resp.ok:
        raise RoutingError(f"OpenRouteService request failed ({resp.status_code}): {resp.text[:200]}")


def geocode(query, size=5):
    """Look up an address, biased to the Gothenburg bounding box.

    Returns a list of {"label", "lat", "lon"} candidates, best match first.
    """
    _require_api_key()
    bounds = config.GOTHENBURG_BOUNDS
    params = {
        "api_key": config.OPENROUTESERVICE_API_KEY,
        "text": query,
        "size": size,
        "boundary.rect.min_lon": bounds["min_lon"],
        "boundary.rect.min_lat": bounds["min_lat"],
        "boundary.rect.max_lon": bounds["max_lon"],
        "boundary.rect.max_lat": bounds["max_lat"],
    }
    resp = requests.get(f"{config.ORS_BASE_URL}/geocode/search", params=params, timeout=10)
    _raise_for_ors_error(resp)

    candidates = []
    for feature in resp.json().get("features", []):
        lon, lat = feature["geometry"]["coordinates"]
        candidates.append(
            {
                "label": feature["properties"].get("label", query),
                "lat": lat,
                "lon": lon,
            }
        )
    if not candidates:
        raise RoutingError(f"No match found for “{query}” in the Gothenburg area.")
    return candidates


def avoid_polygons_from_incidents(incidents, start, end, half_width_m=None):
    """Build a GeoJSON MultiPolygon of small "avoid zones" around each known
    incident, for requesting a route that actively routes around them.

    Incidents too close to the start/end point are excluded so a trip that
    begins or ends near a reported incident doesn't become infeasible to
    route at all.
    """
    half_width_m = half_width_m or config.AVOID_POLYGON_HALF_WIDTH_M
    exclusion_m = half_width_m * 1.5

    polygons = []
    for _, row in incidents.iterrows():
        point = (row["lat"], row["lon"])
        if haversine_m(point, start) < exclusion_m or haversine_m(point, end) < exclusion_m:
            continue
        polygons.append([square_ring_lonlat(row["lat"], row["lon"], half_width_m)])

    if not polygons:
        return None
    return {"type": "MultiPolygon", "coordinates": polygons}


def _request_directions(
    profile, start, end, alternative_routes=False, avoid_features=None, avoid_polygons=None
):
    body = {"coordinates": [[start[1], start[0]], [end[1], end[0]]]}
    if alternative_routes:
        body["alternative_routes"] = {
            "target_count": 3,
            "weight_factor": 1.6,
            "share_factor": 0.6,
        }
    options = {}
    if avoid_features:
        options["avoid_features"] = avoid_features
    if avoid_polygons:
        options["avoid_polygons"] = avoid_polygons
    if options:
        body["options"] = options

    headers = {
        "Authorization": config.OPENROUTESERVICE_API_KEY,
        "Content-Type": "application/json",
    }
    resp = requests.post(
        f"{config.ORS_BASE_URL}/v2/directions/{profile}/geojson",
        json=body,
        headers=headers,
        timeout=15,
    )
    _raise_for_ors_error(resp)

    routes = []
    for feature in resp.json().get("features", []):
        coords = [(lat, lon) for lon, lat in feature["geometry"]["coordinates"]]
        summary = feature["properties"]["summary"]
        routes.append(
            {
                "coordinates": coords,
                "distance_m": summary["distance"],
                "duration_s": summary["duration"],
            }
        )
    return routes


def _dedupe_routes(routes):
    seen = set()
    unique = []
    for route in routes:
        key = tuple((round(lat, 5), round(lon, 5)) for lat, lon in route["coordinates"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(route)
    return unique


def get_fast_and_safe_routes(profile_key, start, end, incidents=None):
    """Return (fastest_route, safest_route, all_scored_routes) for a trip.

    Each route dict has coordinates/distance_m/duration_s plus a "risk"
    entry from risk.score_route(), which includes how busy the roads on the
    route are (Trafikverket traffic volumes) when that data is reachable. Combines three sources of candidate
    routes so the "safe" pick is a genuine, actively-routed-around-risk
    alternative rather than just whichever generic ORS alternative happens
    to score lowest:
      1. ORS's own alternative routes for the fastest option.
      2. If ORS only returns one, a route avoiding highways/steps.
      3. A route that actively avoids small zones around every known
         incident (options.avoid_polygons), so it structurally routes
         around risk rather than coincidentally differing.
    """
    _require_api_key()
    profile = config.ROUTE_PROFILES[profile_key]
    incidents = incidents if incidents is not None else risk.load_incidents()

    routes = _request_directions(profile, start, end, alternative_routes=True)

    if len(routes) < 2:
        avoid = AVOID_FEATURES_BY_PROFILE.get(profile)
        if avoid:
            routes += _request_directions(profile, start, end, avoid_features=avoid)

    avoid_polygons = avoid_polygons_from_incidents(incidents, start, end)
    if avoid_polygons:
        try:
            routes += _request_directions(profile, start, end, avoid_polygons=avoid_polygons)
        except RoutingError:
            pass  # avoid-zone routing infeasible (e.g. polygon/area limits) -- fall back to alternatives only

    routes = _dedupe_routes(routes)
    if not routes:
        raise RoutingError("OpenRouteService returned no route between those points.")

    try:
        traffic_flows = traffic_flow.load_vehicle_flows()
    except Exception:
        traffic_flows = None  # Trafikverket unreachable -- score on incidents only

    scored = [
        {
            **route,
            "risk": risk.score_route(route["coordinates"], incidents, traffic_flows=traffic_flows),
        }
        for route in routes
    ]

    fastest = min(scored, key=lambda r: r["duration_s"])

    # "Safest" must actually beat the fastest route's risk -- never present
    # a distinct alternative that's both slower AND riskier just because it
    # happens to be the second-best of the candidate pool.
    strictly_safer = [
        r for r in scored
        if r is not fastest and r["risk"]["score_per_km"] < fastest["risk"]["score_per_km"]
    ]
    safest = min(strictly_safer, key=lambda r: r["risk"]["score_per_km"]) if strictly_safer else fastest

    return fastest, safest, scored
