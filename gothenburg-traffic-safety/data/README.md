# data/

## Incident data (used for route risk scoring + map markers)

`risk.load_incidents()` is the single entry point every page uses, and it
merges **two** sources by default:

1. **`police_incidents_gothenburg.csv`** — real data, built by
   `fetch_police_incidents.py` from the Swedish Police open events API
   (`config.INCIDENT_DATA_PATH`). Two caveats inherited from the source
   (see that script's docstring for detail):
   - **Rolling feed, not a historical archive.** The API only exposes the
     ~500 most recent events nationwide. Re-running the script reflects
     whatever is currently live; it does not accumulate history on its own.
   - **Heuristic extraction.** Street name and involved road-user type are
     parsed from free-text Swedish report summaries via regex/keyword
     matching, not a structured field. Bare highway mentions (e.g. "på
     E45") geocode to a generic point on that road, not the specific spot
     named in the text.
2. **`sample_synthetic_incidents.csv`** — **fabricated demo data**
   (`config.SYNTHETIC_INCIDENT_DATA_PATH`), added because the real feed
   above is currently thin (a few dozen citywide) and makes most route
   comparisons look identically risk-free. It's ~140 made-up incidents
   spread across the city (some clustered at plausible hotspot names, some
   scattered with a center-weighted random distribution) so Route Check has
   enough density to show a genuine fast-vs-safer trade-off.

Regenerate the real half with:

```bash
python data/fetch_police_incidents.py            # live fetch + geocode
python data/fetch_police_incidents.py --offline   # reuse the cached raw sample, no network
python data/fetch_police_incidents.py --no-geocode  # preview extraction only (separate file, not the main CSV)
```

`sample_police_events_raw.json` is the cached raw API response (written
automatically on each live run) so `--offline` runs don't need network
access.

### Fake data is always distinguishable from real data

Every synthetic row has `source=SYNTHETIC_SAMPLE` and an `id` prefixed
`SYN-`, so it's identifiable in the raw CSV, not just in the UI. Anywhere
incidents are rendered (`risk.incident_marker_style()`, used by both
`dashboard.py` and `app_pages/2_Route_Check.py`), synthetic markers get:

- a distinct purple color (real markers are colored by severity: black /
  orange / yellow)
- a dashed outline and lower fill opacity
- a "🧪 SIMULATED" prefix on the hover tooltip and click popup

Set `config.INCLUDE_SYNTHETIC_INCIDENTS = False` to drop the fabricated
data entirely and score/display only real reports (once the real feed has
enough coverage to stand on its own).

### Schema

Both files share these columns, which `risk.py` depends on:

| column        | meaning                                                  |
|---------------|-----------------------------------------------------------|
| `lat`, `lon`  | incident location (WGS84)                                 |
| `severity`    | one of `fatal`, `severe`, `minor`                          |
| `road_users`  | `\|`-separated road users, e.g. `Car\|Cyclist` (may be blank) |
| `source`      | `POLICE_API` or `SYNTHETIC_SAMPLE`                         |

`police_incidents_gothenburg.csv` additionally has `datetime` (when the
police published the report), `title` (the police's event name, which
starts with when the accident happened, e.g. "4 september 06.53,
Trafikolycka, Göteborg"), `street`, `summary` and `url` (the full report
on polisen.se); the synthetic file has `near` (a landmark name) instead of
`street`/`summary`. `risk.incident_marker_style()` picks whichever applies.

To add a third dataset (e.g. a real STRADA export, if access is ever
granted), give it the same required columns and either point
`config.INCIDENT_DATA_PATH` at it directly, or extend
`risk.load_incidents()`'s merge list — `risk.py`/`routing.py` don't need
any other changes as long as the columns match.

## Near-miss reports

`near_miss_reports.csv` holds reports submitted on the Report Near Miss
page (written by `near_miss.save_report()`, created on the first report).
Columns: `id`, `timestamp` (when reported), `type` (Near miss / Hazard /
Collision), `road_users` (`|`-separated, same names as the incident data,
e.g. `Cyclist|Car`), `severity` (Low / Moderate / High), `description`,
`location_text` (as typed, blank for GPS), `lat`, `lon`, `location_source`
(`map` for a click on the map, `gps`, or `address` for a typed location).

It's local to each computer and listed in `.gitignore`, so reports aren't
uploaded with the code.

## No database

This project stores everything as flat files under `data/` — CSV/JSON —
by explicit decision. Don't add SQLite or any other database.
