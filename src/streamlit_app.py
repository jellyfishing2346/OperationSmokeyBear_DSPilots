#!/usr/bin/env python3
"""Streamlit app: per-state district data-audit and ranking

Features:
- Load pipeline outputs (augmented.jsonl and analysis.jsonl)
- Accept district GeoJSON upload (or a path) containing polygons with properties (state, district_id/name)
- Accept station GeoJSON upload (or derive station points from incident unit_responses)
- For each polygon: compute whether any station point lies inside; if none, compute nearest station distance (meters)
- Aggregate incidents within polygons and compute a 'messiness' score (1 - mean completeness_score) weighted by incident count
- Produce per-state ranked reports and enable CSV download

This module is used by the Streamlit UI and by tools that generate per-state reports.
"""
from __future__ import annotations

import json
from functools import partial
from io import StringIO
from typing import Dict, List, Optional, Tuple

import pandas as pd
import streamlit as st
import io
import zipfile
import tempfile
import os
import math
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.platypus import Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.utils import ImageReader
import matplotlib.pyplot as plt
from typing import Any
from shapely.geometry import shape, Point
from shapely.ops import transform
from pyproj import Transformer


def load_jsonl(path: str) -> List[Dict]:
    objs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            objs.append(json.loads(line))
    return objs


def extract_incident_point(aug: Dict) -> Optional[Tuple[float, float]]:
    # Try common places: base.point.geometry.coordinates or details.narrative point
    base = aug.get("base") or aug.get("details") or {}
    point = None
    if isinstance(base, dict):
        p = base.get("point")
        if p and isinstance(p, dict):
            geom = p.get("geometry")
            if geom and geom.get("type") == "Point":
                coords = geom.get("coordinates")
                if coords and len(coords) >= 2:
                    point = (coords[0], coords[1])
    # fallback: top-level 'point'
    if point is None and aug.get("point"):
        g = aug.get("point")
        if isinstance(g, dict) and g.get("geometry") and g["geometry"].get("type") == "Point":
            coords = g["geometry"].get("coordinates")
            point = (coords[0], coords[1])
    return point


def build_station_points_from_incidents(augmented_docs: List[Dict]) -> List[Tuple[str, Tuple[float, float]]]:
    stations = {}
    for doc in augmented_docs:
        # unit_responses -> pick reported unit point if exists
        unit_responses = doc.get("unit_responses") or doc.get("dispatch", {}).get("unit_responses") or []
        for ur in unit_responses:
            uid = ur.get("unit_neris_id") or ur.get("reported_unit_id")
            pt = None
            point_struct = ur.get("point") or ur.get("reported_point")
            if point_struct and isinstance(point_struct, dict):
                geom = point_struct.get("geometry")
                if geom and geom.get("type") == "Point":
                    coords = geom.get("coordinates")
                    if coords and len(coords) >= 2:
                        pt = (coords[0], coords[1])
            if uid and pt:
                stations[uid] = pt
    # Return list of (id, (lon,lat))
    return list(stations.items())


def to_meters_transformer() -> Transformer:
    # WGS84 (EPSG:4326) to WebMercator (EPSG:3857)
    return Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)


def geom_to_meters(geom):
    t = to_meters_transformer()
    return transform(lambda x, y: t.transform(x, y), geom)


def point_to_meters(pt: Tuple[float, float]) -> Tuple[float, float]:
    t = to_meters_transformer()
    return t.transform(pt[0], pt[1])


def compute_polygon_station_metrics(polygons: List[Dict], station_points: List[Tuple[str, Tuple[float, float]]], incidents_index: List[Dict]):
    # polygons: list of GeoJSON feature dicts with 'geometry' and properties including 'state'/'district'
    results = []

    # convert station points to shapely Points
    station_pts = [(sid, Point(pt)) for sid, pt in station_points]

    # Precompute incident points into shapely Points
    incident_records = []
    for inc in incidents_index:
        score = inc.get("completeness_score", 1.0)
        incident_id = inc.get("incident_id") or inc.get("incident_number") or inc.get("source_index")
        aug = inc.get("augmented") or {}
        p = extract_incident_point(aug)
        if p:
            incident_records.append({"id": incident_id, "score": score, "point": Point(p), "aug": aug})

    for feat in polygons:
        props = feat.get("properties", {})
        geom = shape(feat.get("geometry"))
        state = props.get("state") or props.get("STATE") or props.get("state_name")
        district = props.get("district") or props.get("district_id") or props.get("name") or props.get("NAME")

        # stations inside?
        stations_inside = [sid for sid, pt in station_pts if pt.within(geom)]

        # incidents inside polygon
        incs_inside = [rec for rec in incident_records if rec["point"].within(geom)]
        n_incs = len(incs_inside)
        mean_score = float(sum([r["score"] for r in incs_inside]) / n_incs) if n_incs else 1.0
        messiness = 1.0 - mean_score

        nearest_station_dist_m = None
        if not stations_inside and station_pts:
            # compute distance from polygon to nearest station in meters
            geom_m = geom_to_meters(geom)
            dists = []
            for sid, pt in station_pts:
                p_m = Point(point_to_meters((pt.x, pt.y))) if hasattr(pt, 'x') else Point(point_to_meters(pt))
                try:
                    d = geom_m.distance(p_m)
                except Exception:
                    # fallback approximate
                    d = geom.distance(pt)
                dists.append(d)
            if dists:
                nearest_station_dist_m = min(dists)

        results.append({
            "state": state,
            "district": district,
            "n_incidents": n_incs,
            "mean_completeness": mean_score,
            "messiness": messiness,
            "stations_inside": stations_inside,
            "nearest_station_distance_m": nearest_station_dist_m,
            "properties": props,
        })

    return results


def main():
    st.title("NERIS Incident Data Audit — District Ranking by Messiness")

    st.markdown("Upload or select the pipeline outputs (augmented + analysis JSONL). Defaults are taken from Downloads when present.")

    default_dir = "/Users/test/Downloads/analysis_outputs_v2"
    out_dir = st.text_input("Pipeline outputs directory", value=default_dir)

    run_button = st.button("Load outputs and run audit")

    uploaded_district = st.file_uploader("Upload district GeoJSON (optional)", type=["geojson", "json"])
    uploaded_stations = st.file_uploader("Upload station GeoJSON (optional)", type=["geojson", "json"])

    if run_button:
        try:
            aug_path = f"{out_dir}/augmented.jsonl"
            analysis_path = f"{out_dir}/analysis.jsonl"
            augmented = load_jsonl(aug_path)
            analysis = load_jsonl(analysis_path)
        except Exception as e:
            st.error(f"Failed to load pipeline outputs from {out_dir}: {e}")
            return

        # Build incidents index by merging analysis + augmented
        incidents_index = []
        for a in analysis:
            idx = a.get("source_index")
            aug = augmented[idx] if idx is not None and idx < len(augmented) else {}
            merged = {**a, "augmented": aug}
            # try to extract incident id
            merged["incident_id"] = aug.get("incident_id") or aug.get("incident_number") or merged.get("source_index")
            incidents_index.append(merged)

        # Stations
        station_points = []
        if uploaded_stations:
            try:
                stations_geo = json.load(uploaded_stations)
                features = stations_geo.get("features") if stations_geo.get("type") == "FeatureCollection" else [stations_geo]
                for f in features:
                    props = f.get("properties", {})
                    sid = props.get("id") or props.get("station_id") or props.get("name")
                    geom = shape(f.get("geometry"))
                    if geom and geom.geom_type == "Point":
                        station_points.append((sid, (geom.x, geom.y)))
            except Exception as e:
                st.warning(f"Failed to parse uploaded stations GeoJSON: {e}")

        if not station_points:
            # derive stations from incidents
            station_points = build_station_points_from_incidents([i.get("augmented", {}) for i in incidents_index])

        # Districts
        polygons = []
        if uploaded_district:
            try:
                geo = json.load(uploaded_district)
                features = geo.get("features") if geo.get("type") == "FeatureCollection" else [geo]
                polygons = features
            except Exception as e:
                st.error(f"Failed to parse district GeoJSON: {e}")
                return
        else:
            st.info("No district GeoJSON provided — you can upload polygon boundaries to compute district-level rankings and station containment.")

        if polygons:
            results = compute_polygon_station_metrics(polygons, station_points, incidents_index)

            df = pd.DataFrame(results)
            df["nearest_station_distance_m"] = df["nearest_station_distance_m"].fillna(0)

            # Per-state selector
            states = sorted([s for s in df["state"].unique() if s])
            sel_state = st.selectbox("Select state", options=[None] + states)
            if sel_state:
                sub = df[df["state"] == sel_state].sort_values(["messiness", "n_incidents"], ascending=[False, False])
                st.write(f"Districts in {sel_state} ranked by messiness (higher = more messy)")
                st.dataframe(sub[["district", "n_incidents", "mean_completeness", "messiness", "stations_inside", "nearest_station_distance_m"]].reset_index(drop=True))

                csv_buf = StringIO()
                sub.to_csv(csv_buf, index=False)
                st.download_button("Download CSV", csv_buf.getvalue(), file_name=f"{sel_state}_district_messiness.csv", mime="text/csv")
                # Per-state full ZIP (CSV + PDF) for all states
                if st.button("Generate full per-state ZIP (CSV + PDF)"):
                    with st.spinner("Generating per-state CSVs and PDFs and zipping..."):
                        zip_bytes = generate_per_state_zip_bytes(df, polygons, station_points, incidents_index)
                        st.download_button("Download full per-state ZIP", zip_bytes, file_name="per_state_reports.zip", mime="application/zip")
                # Per-state full ZIP (CSV + PDF) for all states
                if st.button("Generate full per-state ZIP (CSV + PDF)"):
                    with st.spinner("Generating per-state CSVs and PDFs and zipping..."):
                        # create temp zip
                        tmpfd, tmpzip = tempfile.mkstemp(suffix=".zip")
                        os.close(tmpfd)
                        with zipfile.ZipFile(tmpzip, "w", zipfile.ZIP_DEFLATED) as zf:
                            for state_name in df["state"].dropna().unique():
                                sname = str(state_name)
                                ssub = df[df["state"] == sname].sort_values(["messiness", "n_incidents"], ascending=[False, False])
                                # write CSV
                                csv_bytes = ssub.to_csv(index=False).encode("utf-8")
                                zf.writestr(f"{sname}_district_messiness.csv", csv_bytes)
                                # generate PDF report (simple)
                                pdf_bytes = generate_state_pdf_bytes(sname, ssub, polygons, station_points, incidents_index)
                                zf.writestr(f"{sname}_district_report.pdf", pdf_bytes)
                        # read zip and offer download
                        with open(tmpzip, "rb") as f:
                            data = f.read()
                        st.download_button("Download full per-state ZIP", data, file_name="per_state_reports.zip", mime="application/zip")
                        try:
                            os.remove(tmpzip)
                        except Exception:
                            pass
        else:
            st.info("No polygons to analyze. Upload a district GeoJSON to enable polygon-level analysis.")


def generate_state_map_png_bytes(state_name: str, polygons_features: List[Dict], station_points: List[Tuple[str, Tuple[float, float]]], incidents_index: List[Dict]) -> bytes:
    """Render a small PNG map for a state's polygons, stations, and sample incidents.

    Uses matplotlib to draw polygons and points; returns PNG bytes.
    """
    # collect polygons for this state
    feats = [f for f in polygons_features if (f.get("properties", {}).get("state") or f.get("properties", {}).get("STATE") or f.get("properties", {}).get("state_name")) == state_name]
    # If none, try fuzzy match
    if not feats:
        feats = [f for f in polygons_features if str(f.get("properties", {}).get("state") or '').upper() == str(state_name).upper()]

    # Determine bounding box
    lons = []
    lats = []
    for f in feats:
        geom = f.get("geometry")
        coords = geom.get("coordinates", [])
        # handle polygons (assumes lon,lat)
        for part in coords:
            for coord in part:
                lons.append(coord[0]); lats.append(coord[1])
    # also include stations and sample incident points
    for sid, pt in station_points:
        lons.append(pt[0]); lats.append(pt[1])
    for inc in incidents_index:
        p = None
        aug = inc.get("augmented", {})
        if isinstance(aug, dict):
            ptmp = aug.get("base", {}).get("point") or aug.get("point")
            if ptmp and isinstance(ptmp, dict):
                geom = ptmp.get("geometry")
                if geom and geom.get("type") == "Point":
                    c = geom.get("coordinates")
                    if c and len(c) >= 2:
                        lons.append(c[0]); lats.append(c[1])

    if not lons or not lats:
        # fallback to a small area
        minx, maxx, miny, maxy = -77.1, -76.7, 38.8, 39.3
    else:
        minx, maxx = min(lons), max(lons)
        miny, maxy = min(lats), max(lats)
        # add margin
        dx = (maxx - minx) * 0.1 if maxx > minx else 0.01
        dy = (maxy - miny) * 0.1 if maxy > miny else 0.01
        minx -= dx; maxx += dx; miny -= dy; maxy += dy

    fig, ax = plt.subplots(figsize=(6, 4), dpi=150)
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.set_title(f"{state_name} — Districts & Stations", fontsize=10)
    # draw polygons
    for f in feats:
        geom = f.get("geometry")
        if not geom:
            continue
        coords = geom.get("coordinates", [])
        for part in coords:
            xs = [c[0] for c in part]
            ys = [c[1] for c in part]
            ax.plot(xs, ys, color="C0", linewidth=1)
            ax.fill(xs, ys, edgecolor="C0", alpha=0.1)
    # draw stations
    if station_points:
        xs = [pt[0] for _, pt in station_points]
        ys = [pt[1] for _, pt in station_points]
        ax.scatter(xs, ys, marker="^", color="red", s=30, label="Stations")
    # draw sample incident points (up to 50)
    inc_pts = []
    for inc in incidents_index:
        aug = inc.get("augmented", {})
        ptmp = aug.get("base", {}).get("point") or aug.get("point")
        if ptmp and isinstance(ptmp, dict):
            geom = ptmp.get("geometry")
            if geom and geom.get("type") == "Point":
                c = geom.get("coordinates")
                if c and len(c) >= 2:
                    inc_pts.append((c[0], c[1]))
    if inc_pts:
        inc_pts = inc_pts[:50]
        xs = [p[0] for p in inc_pts]
        ys = [p[1] for p in inc_pts]
        ax.scatter(xs, ys, marker="o", color="black", s=6, alpha=0.6, label="Incidents")

    ax.legend(fontsize=8)
    ax.set_xlabel("Lon"); ax.set_ylabel("Lat")
    buf = io.BytesIO()
    plt.tight_layout()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def generate_state_pdf_bytes(state_name: str, df_state: pd.DataFrame, polygons_features: List[Dict], station_points: List[Tuple[str, Tuple[float, float]]], incidents_index: List[Dict]) -> bytes:
    """Create a richer PDF for a state: header, small map, table of top districts, and sample incident examples.

    Returns PDF bytes.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    width, height = letter
    # --- Cover page: logo (optional) + summary metrics ---
    c.setFont("Helvetica-Bold", 20)
    c.drawCentredString(width / 2.0, height - 80, f"State report: {state_name}")
    # optional logo: look in Downloads or current dir
    logo_paths = ["/Users/test/Downloads/logo.png", "./logo.png", "./logo.jpg"]
    logo_drawn = False
    for lp in logo_paths:
        try:
            if os.path.exists(lp):
                img = ImageReader(lp)
                # fit logo into a 200x80 box
                img_w = 200
                img_h = 80
                c.drawImage(img, width - img_w - 40, height - img_h - 40, width=img_w, height=img_h, preserveAspectRatio=True, mask='auto')
                logo_drawn = True
                break
        except Exception:
            continue

    c.setFont("Helvetica", 11)
    c.drawString(40, height - 120, f"Generated by NERIS audit — districts ranked by messiness")

    # summary metrics (from df_state)
    try:
        total_districts = int(df_state.shape[0])
        total_incidents = int(df_state["n_incidents"].sum())
        weighted_num = float((df_state["mean_completeness"] * df_state["n_incidents"]).sum())
        weighted_den = float(df_state["n_incidents"].sum()) or 1.0
        overall_mean_completeness = weighted_num / weighted_den
        overall_mean_messiness = float((df_state["messiness"] * df_state["n_incidents"]).sum()) / weighted_den
    except Exception:
        total_districts = df_state.shape[0]
        total_incidents = int(df_state["n_incidents"].sum()) if "n_incidents" in df_state else 0
        overall_mean_completeness = float(df_state["mean_completeness"].mean()) if "mean_completeness" in df_state else 1.0
        overall_mean_messiness = float(df_state["messiness"].mean()) if "messiness" in df_state else 0.0

    c.drawString(40, height - 150, f"Total districts: {total_districts}")
    c.drawString(40, height - 170, f"Total incidents (in-district): {total_incidents}")
    c.drawString(40, height - 190, f"Weighted mean completeness: {overall_mean_completeness:.3f}")
    c.drawString(40, height - 210, f"Weighted mean messiness: {overall_mean_messiness:.3f}")

    # small note
    c.setFont("Helvetica-Oblique", 9)
    c.drawString(40, height - 240, "This report is generated from pipeline outputs and uses point-in-polygon tests to select example incidents per district.")
    c.showPage()

    # header (page after cover)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(40, height - 50, f"State report: {state_name}")
    c.setFont("Helvetica", 10)
    c.drawString(40, height - 70, f"Generated by NERIS audit — districts ranked by messiness")

    # map image
    try:
        map_png = generate_state_map_png_bytes(state_name, polygons_features, station_points, incidents_index)
        img = ImageReader(io.BytesIO(map_png))
        img_w = 380
        img_h = 200
        c.drawImage(img, 40, height - 80 - img_h, width=img_w, height=img_h)
    except Exception:
        # skip map on failure
        pass

    # Table of top districts (paginated rows so table can span pages)
    top = df_state.sort_values(["messiness", "n_incidents"], ascending=[False, False])
    c.setFont("Helvetica-Bold", 11)
    table_x = 40
    table_y = height - 320
    row_h = 14
    # header
    headers = ["District", "Incidents", "Mean completeness", "Messiness"]
    c.setFont("Helvetica-Bold", 10)
    c.drawString(table_x, table_y, headers[0])
    c.drawString(table_x + 160, table_y, headers[1])
    c.drawString(table_x + 240, table_y, headers[2])
    c.drawString(table_x + 380, table_y, headers[3])
    table_y -= row_h
    c.setFont("Helvetica", 9)
    for _, row in top.iterrows():
        if table_y < 100:
            c.showPage()
            # redraw header on new page
            table_y = height - 50
            c.setFont("Helvetica-Bold", 10)
            c.drawString(table_x, table_y, headers[0])
            c.drawString(table_x + 160, table_y, headers[1])
            c.drawString(table_x + 240, table_y, headers[2])
            c.drawString(table_x + 380, table_y, headers[3])
            table_y -= row_h
            c.setFont("Helvetica", 9)
        c.drawString(table_x, table_y, str(row.get("district")))
        c.drawString(table_x + 160, table_y, str(int(row.get("n_incidents", 0))))
        c.drawString(table_x + 240, table_y, f"{row.get('mean_completeness'):.3f}")
        c.drawString(table_x + 380, table_y, f"{row.get('messiness'):.3f}")
        table_y -= row_h

    # Add sample incidents per top district: include up to 3 example incident IDs and missing_fields counts (actual point-in-polygon selection)
    y = table_y - 20
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, y, "Sample incident examples and missing-field breakdowns")
    y -= 18
    c.setFont("Helvetica", 9)
    # Precompute polygons mapped by district name for quick lookup
    district_polygons = {}
    for feat in polygons_features:
        props = feat.get("properties", {})
        name = props.get("district") or props.get("district_id") or props.get("name") or props.get("NAME")
        state = props.get("state") or props.get("STATE") or props.get("state_name")
        if state != state_name:
            continue
        if name:
            district_polygons[str(name)] = shape(feat.get("geometry"))

    # Build incident points list
    incident_points = []
    for inc in incidents_index:
        aug = inc.get("augmented", {})
        pt = extract_incident_point(aug)
        if pt:
            incident_points.append((inc, Point(pt)))

    # For each district in top, find incidents inside its polygon
    for _, row in top.iterrows():
        if y < 100:
            c.showPage(); y = height - 50
        district_name = str(row.get("district"))
        poly = district_polygons.get(district_name)
        examples = []
        if poly:
            for inc_rec, pt in incident_points:
                if pt.within(poly):
                    examples.append(inc_rec)
                    if len(examples) >= 3:
                        break
        # Build missing-field breakdown for examples
        ex_lines = []
        for ex in examples:
            ex_id = ex.get("incident_id")
            missing = ex.get("missing_fields") or []
            ex_lines.append(f"{ex_id} (missing:{','.join(missing)})")
        if not ex_lines:
            ex_lines = ["(no example incidents found inside polygon)"]
        line = f"{district_name}: { '; '.join(ex_lines) }"
        c.drawString(40, y, line)
        y -= 14

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.read()


def generate_per_state_zip_bytes(df: pd.DataFrame, polygons_features: List[Dict], station_points: List[Tuple[str, Tuple[float, float]]], incidents_index: List[Dict]) -> bytes:
    """Generate a zip file (bytes) containing per-state CSV and PDF reports (with maps and examples)."""
    mem = io.BytesIO()
    with zipfile.ZipFile(mem, "w", zipfile.ZIP_DEFLATED) as zf:
        for state_name in sorted([s for s in df["state"].dropna().unique()]):
            sname = str(state_name)
            ssub = df[df["state"] == sname].sort_values(["messiness", "n_incidents"], ascending=[False, False])
            csv_bytes = ssub.to_csv(index=False).encode("utf-8")
            zf.writestr(f"{sname}_district_messiness.csv", csv_bytes)
            pdf_bytes = generate_state_pdf_bytes(sname, ssub, polygons_features, station_points, incidents_index)
            zf.writestr(f"{sname}_district_report.pdf", pdf_bytes)
    mem.seek(0)
    return mem.read()


if __name__ == "__main__":
    main()
