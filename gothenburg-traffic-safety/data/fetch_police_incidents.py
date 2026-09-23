"""Fetch Gothenburg traffic-accident events from the Swedish Police open API.

Pulls recent Trafikolycka events for Goteborg from https://polisen.se/api/events,
extracts a street name and the involved road-user type(s) from the free-text
`summary` field, geocodes the extracted street via Nominatim, and writes the
clean (successfully extracted + geocoded) subset to
data/police_incidents_gothenburg.csv in the schema risk.py expects
(lat, lon, severity, road_users).

The API's own `location.gps` field is a fixed county-level centroid, not a
per-incident coordinate -- it's ignored here in favor of geocoding the
extracted street name.

This is a rolling feed of the ~500 most recent events nationwide, not a
historical archive: re-running this script reflects whatever is currently
live, it does not accumulate history on its own.

Usage:
    python data/fetch_police_incidents.py                # live fetch + geocode
    python data/fetch_police_incidents.py --offline       # reuse cached raw sample
    python data/fetch_police_incidents.py --no-geocode    # skip Nominatim (preview only)
"""

import argparse
import csv
import json
import re
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config

DATA_DIR = Path(__file__).resolve().parent
RAW_SAMPLE_PATH = DATA_DIR / "sample_police_events_raw.json"
OUTPUT_PATH = DATA_DIR / "police_incidents_gothenburg.csv"
NO_GEOCODE_PREVIEW_PATH = DATA_DIR / "police_incidents_gothenburg_preview_no_geocode.csv"

POLICE_API_URL = "https://polisen.se/api/events"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "gothenburg-traffic-safety/0.1 (local development script)"

STREET_SUFFIXES = (
    "gatan", "vagen", "leden", "platsen", "torget", "granden", "grand",
    "allen", "bron", "motet", "stigen", "backen", "kajen", "esplanaden",
    "plan", "parken",
)
# Swedish text isn't normalized here -- match both the plain-ASCII and
# accented forms of each suffix (e.g. "vägen" as well as "vagen").
_ACCENTED = {"a": "[aå]", "o": "o", "e": "[eé]", "vagen": "v[aä]gen"}
STREET_PATTERN = re.compile(
    r"(?:p[aå]|vid|l[aä]ngs|i)\s+((?:[A-ZÅÄÖ][\wÅÄÖåäö\-]*\s?){1,3}(?:"
    + "gatan|v[aä]gen|leden|platsen|torget|gr[aä]nden|gr[aä]nd|all[eé]n|bron|"
      "motet|stigen|backen|kajen|esplanaden|plan|parken"
    + r"))\b"
)
HIGHWAY_PATTERN = re.compile(r"\bE\d{1,2}(?:an|:an)?\b")

ROAD_USER_KEYWORDS = {
    "Car": ["personbil", "bilist", "bil "],
    "Bus": ["buss"],
    "Tram": ["spårvagn", "sparvagn"],
    "Cyclist": ["cyklist", "cykel"],
    "Pedestrian": ["fotgängare", "fotgangare", "gående", "gaende", "gångtrafikant", "gangtrafikant"],
}

SEVERITY_KEYWORDS = {
    "fatal": ["avled", "avliden", "omkom", "dödsolycka", "dodsolycka"],
    "severe": ["svårt skadad", "svart skadad", "allvarligt skadad"],
}


def extract_street(summary):
    m = STREET_PATTERN.search(summary)
    if m:
        return m.group(1).strip()
    m = HIGHWAY_PATTERN.search(summary)
    if m:
        return m.group(0)
    return None


def extract_road_users(summary):
    text = summary.lower()
    found = [user for user, kws in ROAD_USER_KEYWORDS.items() if any(kw in text for kw in kws)]
    return "|".join(found)


def extract_severity(summary):
    text = summary.lower()
    for severity, kws in SEVERITY_KEYWORDS.items():
        if any(kw in text for kw in kws):
            return severity
    return "minor"


def fetch_events(location="Göteborg", event_type="Trafikolycka"):
    resp = requests.get(
        POLICE_API_URL,
        params={"locationname": location, "type": event_type},
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def geocode_street(street, cache):
    if street in cache:
        return cache[street]
    bounds = config.GOTHENBURG_BOUNDS
    resp = requests.get(
        NOMINATIM_URL,
        params={
            "q": f"{street}, Göteborg, Sweden",
            "format": "json",
            "limit": 1,
            "bounded": 1,
            "viewbox": (
                f"{bounds['min_lon']},{bounds['max_lat']},"
                f"{bounds['max_lon']},{bounds['min_lat']}"
            ),
        },
        headers={"User-Agent": USER_AGENT},
        timeout=10,
    )
    resp.raise_for_status()
    results = resp.json()
    coords = (float(results[0]["lat"]), float(results[0]["lon"])) if results else None
    cache[street] = coords
    time.sleep(1.1)  # Nominatim usage policy: max 1 request/second
    return coords


FIELDNAMES = ["id", "datetime", "street", "lat", "lon", "severity", "road_users", "summary", "source"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--offline", action="store_true",
        help="Reuse the cached raw sample instead of hitting the live police API",
    )
    parser.add_argument(
        "--no-geocode", action="store_true",
        help="Skip Nominatim geocoding; writes a preview CSV (no lat/lon) instead of the main output",
    )
    args = parser.parse_args()

    if args.offline:
        if not RAW_SAMPLE_PATH.exists():
            raise SystemExit(f"No cached sample at {RAW_SAMPLE_PATH} -- run once without --offline first.")
        events = json.loads(RAW_SAMPLE_PATH.read_text(encoding="utf-8"))
        print(f"Loaded {len(events)} cached events from {RAW_SAMPLE_PATH}")
    else:
        events = fetch_events()
        RAW_SAMPLE_PATH.write_text(json.dumps(events, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Fetched {len(events)} live events, cached raw response to {RAW_SAMPLE_PATH}")

    geocode_cache = {}
    rows = []
    skipped_no_street = 0
    skipped_no_geocode = 0

    for event in events:
        summary = event.get("summary", "") or ""
        street = extract_street(summary)
        if not street:
            skipped_no_street += 1
            continue

        lat, lon = None, None
        if not args.no_geocode:
            coords = geocode_street(street, geocode_cache)
            if not coords:
                skipped_no_geocode += 1
                continue
            lat, lon = coords

        rows.append({
            "id": event["id"],
            "datetime": event.get("datetime", ""),
            "street": street,
            "lat": lat,
            "lon": lon,
            "severity": extract_severity(summary),
            "road_users": extract_road_users(summary),
            "summary": summary,
            "source": "POLICE_API",
        })

    out_path = NO_GEOCODE_PREVIEW_PATH if args.no_geocode else OUTPUT_PATH
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote {len(rows)} incidents to {out_path}")
    print(f"Skipped {skipped_no_street} events with no extractable street name")
    if not args.no_geocode:
        print(f"Skipped {skipped_no_geocode} events where geocoding found no match")
    if args.no_geocode:
        print("NOTE: --no-geocode output has no lat/lon and is NOT usable by risk.py -- preview only.")


if __name__ == "__main__":
    main()
