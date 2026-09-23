"""Local storage for user-submitted near-miss reports.

Reports are appended to a CSV file (config.NEAR_MISS_REPORTS_PATH) — no
database. Each computer running the app keeps its own file; it isn't shared
between computers unless the file itself is copied.
"""

import csv
import threading
import uuid
from datetime import datetime
from pathlib import Path

import pandas as pd

import config

FIELDNAMES = [
    "id",
    "timestamp",
    "type",
    "road_users",
    "severity",
    "description",
    "location_text",
    "lat",
    "lon",
    "location_source",
]

# Streamlit serves every browser session from the same process, so guard
# the file against two reports being written at the same moment.
_write_lock = threading.Lock()


def save_report(report_type, road_users, severity, description, location_text, lat, lon, location_source):
    """Append one report and return it as a dict.

    `road_users` is a list (stored "|"-separated, like the incident data);
    `location_source` is "gps" or "address".
    """
    row = {
        "id": uuid.uuid4().hex[:8],
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "type": report_type,
        "road_users": "|".join(road_users),
        "severity": severity,
        "description": description.strip(),
        "location_text": location_text.strip(),
        "lat": lat,
        "lon": lon,
        "location_source": location_source,
    }
    path = Path(config.NEAR_MISS_REPORTS_PATH)
    with _write_lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            if is_new:
                writer.writeheader()
            writer.writerow(row)
    return row


def load_reports():
    """All saved reports, newest first (empty DataFrame if none yet)."""
    path = Path(config.NEAR_MISS_REPORTS_PATH)
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame(columns=FIELDNAMES)
    df = pd.read_csv(path, dtype={"id": str})
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    return df.sort_values("timestamp", ascending=False).reset_index(drop=True)
