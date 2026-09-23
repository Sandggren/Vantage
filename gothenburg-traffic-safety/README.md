# Gothenburg Traffic Safety

A crowdsourced near-miss reporting and mapping tool for mixed traffic in
Gothenburg (cars, buses, trams, cyclists, pedestrians), built with Python and
Streamlit.

## Current state

The base map (with incident markers) and the Route Check page (fast vs.
lower-risk route comparison, with a 0–100% risk score) are working. Route
Check needs an OpenRouteService API key (see Setup below). Risk scoring
blends two sources — real Gothenburg traffic-accident reports from the
Swedish Police open events API (`data/fetch_police_incidents.py`) plus
~140 fabricated demo incidents added so route comparisons have enough
density to show a real trade-off. Route risk also counts how busy the roads a
route uses are, from Trafikverket's traffic volumes (state roads only —
see `config.TRAFFIC_RISK_POINTS_PER_10K`). The fake ones are always visually
(purple, dashed) and textually ("🧪 SIMULATED") distinct from real reports
— see `data/README.md`. The other pages are still placeholders. This
project does not use a database — storage is file-based (CSV/JSON under
`data/`).

## Setup

1. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # on Windows: .venv\Scripts\activate
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Copy the environment template and add your API keys (not required yet for
   the base map, but needed once routing is wired in):

   ```bash
   cp .env.example .env
   ```

   - OpenRouteService key: https://openrouteservice.org/dev/#/signup
   - Trafiklab key (for Vasttrafik/GTFS): https://www.trafiklab.se

4. Run the app:

   ```bash
   streamlit run app.py
   ```

   It should open in your browser at `http://localhost:8501` and show an
   interactive map centered on Gothenburg.

## Project structure

```
gothenburg-traffic-safety/
├── app.py                       # Entry point — sidebar navigation
├── assets/                      # Vantage logo (full, wide for the sidebar, shield icon) + original image
├── dashboard.py                 # Dashboard — map (traffic flow + accidents) with accident details panel
├── config.py                    # Shared constants (map center, bounds, categories, routing/risk config)
├── routing.py                   # ORS geocoding + fast/safe route selection
├── risk.py                      # Incident-based route risk scoring
├── near_miss.py                 # Saves/loads near-miss reports (local CSV)
├── traffic_flow.py              # Vehicle (Trafikverket) + bicycle traffic-flow map layers
├── geo_utils.py                 # Haversine / point-to-route distance helpers
├── app_pages/                   # page files, wired up in app.py (not named pages/ on purpose)
│   ├── 1_Report_Near_Miss.py    # near-miss report form, saved to data/near_miss_reports.csv
│   └── 2_Route_Check.py         # fast vs. lower-risk route comparison
├── data/
│   ├── README.md                     # incident data schema, real vs. synthetic, how to swap datasets
│   ├── fetch_police_incidents.py     # pulls + geocodes real police incident data
│   ├── sample_police_events_raw.json # cached raw API response, for --offline dev
│   ├── police_incidents_gothenburg.csv  # real data (19ish rows, rolling feed)
│   ├── sample_synthetic_incidents.csv   # fabricated demo data (~140 rows), merged in by default
│   └── near_miss_reports.csv        # user-submitted near-miss reports (created on first report, local only)
├── requirements.txt
├── .env.example
└── .gitignore
```

## Roadmap

- [x] Base map of Gothenburg, with incident markers (real + synthetic, visually distinct)
- [x] Route risk-check via the OpenRouteService API, with a 0-100% risk score
- [x] Real risk data — Swedish Police open events API (`data/fetch_police_incidents.py`)
- [x] Synthetic demo data merged in for denser route comparisons (`config.INCLUDE_SYNTHETIC_INCIDENTS`)
- [x] "Safer" route actively routes around known incidents (ORS `avoid_polygons`), not just picked from generic alternatives
- [ ] Near-miss reporting form → local CSV/JSON (no database)
- [x] Accident hotspot heat map on the dashboard (police reports; near-miss reports to be added)
- [ ] Vasttrafik bus/tram layer (GTFS, filtered to Gothenburg)
- [ ] Schedule the police-incident fetch to run periodically and accumulate
      history instead of overwriting each run
- [ ] Turn off synthetic data (`config.INCLUDE_SYNTHETIC_INCIDENTS = False`)
      once real coverage is dense enough to stand on its own
