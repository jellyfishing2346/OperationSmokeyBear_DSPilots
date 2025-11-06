# What is Operation Smokey Bear?
**Operation Smokey Bear** is a web-based platform that converts messy incident narratives voice or text into clean, structured incident logs aligned to your incident schema like NERIS. With two connected experiences—a **Responder Portal** for quick capture and a **Records/Dashboard** view for review and analysis. Smokey Bear reduces reporting friction for first responders while standardizing data for downstream analytics.
We built Smokey Bear to solve a very everyday problem in emergency services. Incident details are often captured in free text or rushed notes, which makes consistency and later analysis hard. Our proof-of-concept is a working platform: responders record or paste a summary, the system **transcribes** it, **extracts structured fields** such as type of incident, address, injuries, narrative, etc and validates the output, and stores it. 
On the dashboard side, users can review entries, export data, and track incident counts at a glance. Unlike a single “do-everything” prompt, our solution decomposes the workflow into specialized components with fallback logic that makes field extraction reliable and repeatable.
With Operation Smokey Bear, responders save time, records stay consistent, and incident data becomes analytics-ready.


# Why is Operation Smokey Bear Useful?
Incident reporting is messy:

- Responders are pressed for time and documentation piles up.
- Free-form text is inconsistent and hard to analyze.
- Critical details (location, disposition, displaced persons, rescue info) are easily missed.

**Smokey Bear bridges this gap.** By combining **transcription**, **schema-aware extraction**, **validation**, and a **simple review workflow** into one pipeline, it eliminates confusion for responders and yields structured data that downstream systems (dashboards, GIS, EMR/records) can actually use.


# Features

## 1) Responder Portal
- Record a short **audio** note or paste a **text** description after an incident.
- Click **Parse** to convert the note into structured fields (e.g.,type ,address , injuries, narrative).
- Review the extracted fields and **Save to CSV**.
- See instant counts in a lightweight dashboard.

## 2) Records / Dashboard
- View all saved incidents in a table.
- Quick bar chart for incident type distribution.
- Export the master CSV for BI tools or GIS pipelines.

## 3) Agentic AI Pipeline
- **Transcription** → Local Whisper converts audio to text.
- **Field Extraction** → A Gemini-powered extractor reads the transcript and returns **only** the requested keys as strings (strict JSON; no extra commentary).
- **Validation & Normalization** → Coerces values to strings, fills missing keys with "", drops extras—stabilizing the output for CSV/ETL.
- **ID & Timestamp** → Each record is tagged with a unique incident ID and capture time.
- **Fallback Logic** → If the model returns messy JSON (code fences, extra text), recovery rules cleanly parse the object and retry when needed.

# Technical Overview
**Frontend:** Streamlit
**Backend:** FastAPI (Python)
**Transcription:** OpenAI Whisper (local)
**AI Extractor:** Google Gemini (via google-generativeai)
**Storage (POC):** CSV (incidents_master.csv) with columns: incident_id, timestamp, type, address, injuries, narrative
**Auth/Security (POC):** Local only (CORS enabled for localhost); easy to extend to Supabase/Postgres with RLS.


# Key Backend Modules
- `transcribe.py`: Loads Whisper model (base by default) and returns plain text.
- `providers.py`: Gemini provider with strict JSON response mode and robust parsing fallbacks.
    - `server.py`: FastAPI app exposing:
        - `POST /categorize-transcript` (JSON body: { transcript, fields[] })
        - `POST /categorize-audio` (form-data: audio, fields as JSON array or CSV list)
- `prompt.py`: System and extraction prompts that enforce: **exact keys**, **strings only**, **no extra commentary**.
- `validators.py`: Normalizes the model output to { field: string }.
- `categorize.py`: Orchestration helpers and provider selection hook.


# Datasets
Incident Schema CSV (e.g., core_mod_incident-*.csv): drives which fields you request from the extractor and how you label the dashboard.

## AI Safety by Design
**When configured correctly.** In Smokey Bear, we designed the pipeline so you can keep audio **local**, control what if anything goes to a cloud model, and ship only **validated, sanitized** text into your CSV.
- **Local-first transcription (Whisper):** Audio is processed on the machine running the backend. No audio leaves your network unless you explicitly choose to.
- **Text-only extraction:** The field extractor (Gemini) receives **only the transcript text** and a **fixed list of field names**. You can also run fully offline by swapping Gemini for a local model.
- **Strict output contract:** The extractor is forced to return **exact keys, string values only**. We normalize outputs, drop unexpected keys, and fill missing ones with "".
- **CSV hardening:** Before writing to CSV, we sanitize values to prevent **CSV formula injection** (e.g., cells starting with =, +, , @).
- **Controlled retention:** You can configure whether to keep raw audio, keep just transcripts, or store neither.
- **Least-data principle:** Send only the fields you actually need nothing else is extracted or stored.

# Conclusion
Operation Smokey Bear transforms how first responders document incidents by converting voice recordings or text descriptions into structured, analytics-ready data. 
Instead of choosing between thorough documentation and quick response times, responders can simply speak what happened and let AI extract the key details into standardized fields. 
This proof-of-concept reduces reporting friction while ensuring consistent, searchable incident records that support better decision-making and resource allocation.

## Workspace & local run notes

If you cloned this repository into a developer workspace, a small set of convenience tools and examples are available under the `tools/` folder. To run locally:

1. Create a Python virtual environment and install dependencies:

```bash
cd OperationSmokeyBear_DSPilots
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Generate synthetic data and run the pipeline (examples):

```bash
python tools/generate_synthetic.py --count 1000 --out /Users/test/Downloads/synthetic_incidents.jsonl
python tools/run_pipeline.py --input /Users/test/Downloads/synthetic_incidents.jsonl --output-dir /Users/test/Downloads/analysis_outputs_v2
```

3. Run the Streamlit app (from repo root):

```bash
streamlit run src/streamlit_app.py
```

4. Demo audit and scheduled exporter are in `tools/` and expect pipeline outputs and demo GeoJSON files under `/Users/test/Downloads` by default.

If you'd like a `pyproject.toml`, CI workflow, or tests added, please enable the `restructure/workspace` branch where those artifacts are staged.
