#!/usr/bin/env python3
"""Scheduled exporter: create per-state ZIP reports on a schedule and write to an output folder.

Usage example:
  python tools/schedule_exporter.py --inputs-dir /path/to/outputs --polygons /path/to/districts.geojson --stations /path/to/stations.geojson --outdir /path/to/reports
"""
import argparse
import json
import time
from pathlib import Path
from datetime import datetime
import schedule

from shapely.geometry import shape, Point
import io


def load_jsonl(path: Path):
    docs = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                docs.append(json.loads(line))
    return docs


def run_export(inputs_dir: Path, polygons_path: Path, stations_path: Path, outdir: Path):
    augmented = load_jsonl(inputs_dir / 'augmented.jsonl')
    analysis = load_jsonl(inputs_dir / 'analysis.jsonl')
    # build incidents_index
    incidents_index = []
    for a in analysis:
        idx = a.get('source_index')
        aug = augmented[idx] if idx is not None and idx < len(augmented) else {}
        merged = {**a, 'augmented': aug}
        merged['incident_id'] = aug.get('incident_id') or aug.get('incident_number') or merged.get('source_index')
        incidents_index.append(merged)

    polygons = json.load(open(polygons_path, 'r', encoding='utf-8'))
    polygons_features = polygons.get('features') if polygons.get('type') == 'FeatureCollection' else [polygons]
    stations = json.load(open(stations_path, 'r', encoding='utf-8'))
    station_features = stations.get('features') if stations.get('type') == 'FeatureCollection' else [stations]
    station_points = []
    for f in station_features:
        props = f.get('properties', {})
        sid = props.get('station_id') or props.get('id') or props.get('name')
        geom = f.get('geometry')
        if geom and geom.get('type') == 'Point':
            coords = geom.get('coordinates')
            station_points.append((sid, (coords[0], coords[1])))

    # Import the generator function from the streamlit app module in repo src
    from src.streamlit_app import generate_per_state_zip_bytes, compute_polygon_station_metrics

    # Build df-like structure
    import pandas as pd
    results = compute_polygon_station_metrics(polygons_features, station_points, incidents_index)
    df = pd.DataFrame(results)

    zip_bytes = generate_per_state_zip_bytes(df, polygons_features, station_points, incidents_index)
    timestamp = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    outfile = outdir / f'per_state_reports_{timestamp}.zip'
    outdir.mkdir(parents=True, exist_ok=True)
    with open(outfile, 'wb') as f:
        f.write(zip_bytes)
    print(f'Wrote scheduled report to {outfile}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--inputs-dir', required=True, help='Directory with augmented.jsonl and analysis.jsonl')
    parser.add_argument('--polygons', required=True, help='District GeoJSON')
    parser.add_argument('--stations', required=True, help='Station GeoJSON')
    parser.add_argument('--outdir', required=True, help='Directory to write zip reports')
    parser.add_argument('--interval-minutes', type=int, default=60, help='Run interval in minutes')
    args = parser.parse_args()

    inputs_dir = Path(args.inputs_dir)
    polygons_path = Path(args.polygons)
    stations_path = Path(args.stations)
    outdir = Path(args.outdir)

    def job():
        try:
            run_export(inputs_dir, polygons_path, stations_path, outdir)
        except Exception as e:
            print('Export failed:', e)

    # run immediately, then schedule
    job()
    schedule.every(args.interval_minutes).minutes.do(job)
    print(f'Started scheduled exporter (every {args.interval_minutes} minutes). Writing to {outdir}')
    try:
        while True:
            schedule.run_pending()
            time.sleep(1)
    except KeyboardInterrupt:
        print('Exiting scheduled exporter')


if __name__ == '__main__':
    main()
