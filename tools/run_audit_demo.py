#!/usr/bin/env python3
"""Run a non-interactive demo audit using the same logic as the Streamlit app.

This script expects pipeline outputs under Downloads by default and writes a CSV demo audit.
"""
import json
from pathlib import Path
import csv
import sys

# Import the compute function from the streamlit app package location (repo src/)
from src.streamlit_app import load_jsonl, compute_polygon_station_metrics

OUT_DIR = Path("/Users/test/Downloads")
AUG = OUT_DIR / "analysis_outputs_v2" / "augmented.jsonl"
ANAL = OUT_DIR / "analysis_outputs_v2" / "analysis.jsonl"
DEMO_POLY = OUT_DIR / "demo_districts.geojson"
DEMO_STATIONS = OUT_DIR / "demo_stations.geojson"

if not AUG.exists() or not ANAL.exists():
    print("Pipeline outputs not found in /Users/test/Downloads/analysis_outputs_v2. Run the pipeline first or adjust paths.")
    raise SystemExit(1)

augmented = load_jsonl(str(AUG))
analysis = load_jsonl(str(ANAL))

# Build incidents_index by merging analysis with augmented
incidents_index = []
for a in analysis:
    idx = a.get("source_index")
    aug = augmented[idx] if idx is not None and idx < len(augmented) else {}
    merged = {**a, "augmented": aug}
    merged["incident_id"] = aug.get("incident_id") or aug.get("incident_number") or merged.get("source_index")
    incidents_index.append(merged)

# Load demo polygons and stations
polygons = json.load(open(DEMO_POLY, "r", encoding="utf-8"))
polygons_features = polygons.get("features") if polygons.get("type") == "FeatureCollection" else [polygons]

stations = json.load(open(DEMO_STATIONS, "r", encoding="utf-8"))
station_features = stations.get("features") if stations.get("type") == "FeatureCollection" else [stations]
station_points = []
for f in station_features:
    props = f.get("properties", {})
    sid = props.get("station_id") or props.get("id") or props.get("name")
    geom = f.get("geometry")
    if geom and geom.get("type") == "Point":
        coords = geom.get("coordinates")
        station_points.append((sid, (coords[0], coords[1])))

results = compute_polygon_station_metrics(polygons_features, station_points, incidents_index)

# Write CSV
out_csv = OUT_DIR / "demo_audit.csv"
with open(out_csv, "w", newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=["state","district","n_incidents","mean_completeness","messiness","stations_inside","nearest_station_distance_m"])
    writer.writeheader()
    for r in results:
        writer.writerow({
            "state": r.get("state"),
            "district": r.get("district"),
            "n_incidents": r.get("n_incidents"),
            "mean_completeness": r.get("mean_completeness"),
            "messiness": r.get("messiness"),
            "stations_inside": ";".join(r.get("stations_inside") or []),
            "nearest_station_distance_m": r.get("nearest_station_distance_m") or 0,
        })

print(f"Wrote demo audit to {out_csv}")
