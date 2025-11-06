#!/usr/bin/env python3
"""Simple pipeline runner for incident analysis.

Usage (example):
  python tools/run_pipeline.py --input /path/to/incidents.jsonl --output-dir /path/to/out

This script is intentionally dependency-light and defensive: it will try to import jsonschema/openapi validators if available but works without them.
"""

import argparse
import json
import os
from pathlib import Path
from typing import Any, Dict, List


def analyze_incident(payload: Dict[str, Any], weights: Dict[str, float] = None) -> Dict[str, Any]:
    """Return an augmented payload and an analysis object.

    Augmentation strategy:
    - Ensure `incident_id` exists, otherwise add a placeholder
    - Ensure `title` exists, otherwise add placeholder
    - Any top-level key with None or empty string is replaced by a '<MISSING: key>' placeholder
    """
    aug = dict(payload)
    analysis: Dict[str, Any] = {"missing_fields": [], "placeholders_added": {}}

    # Required-ish fields
    for k in ("incident_id", "title", "details"):
        if k not in aug or aug.get(k) in (None, ""):
            placeholder = f"<MISSING: {k}>"
            aug[k] = placeholder
            analysis["missing_fields"].append(k)
            analysis["placeholders_added"][k] = placeholder

    # Generic sweep for empty values
    for k, v in list(aug.items()):
        if v is None or (isinstance(v, str) and v.strip() == ""):
            placeholder = f"<MISSING: {k}>"
            aug[k] = placeholder
            if k not in analysis["missing_fields"]:
                analysis["missing_fields"].append(k)
            analysis["placeholders_added"][k] = placeholder

    # Example scoring stub (configurable via weights)
    if weights is None:
        penalty = 0.1
    else:
        penalty = float(weights.get("missing_field_penalty", 0.1))
    analysis["completeness_score"] = max(0.0, 1.0 - len(analysis["missing_fields"]) * penalty)

    return {"augmented": aug, "analysis": analysis}


def load_inputs(path: str) -> List[Dict[str, Any]]:
    p = Path(path)
    docs: List[Dict[str, Any]] = []
    if p.is_dir():
        for child in sorted(p.iterdir()):
            if child.suffix.lower() in (".json", ".jsonl"):
                docs.extend(load_inputs(str(child)))
        return docs

    if p.suffix.lower() == ".jsonl":
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                docs.append(json.loads(line))
        return docs

    # Assume single JSON file
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, list):
            docs.extend(data)
        elif isinstance(data, dict):
            docs.append(data)
        else:
            raise ValueError("Unsupported JSON root type: must be object or array")
    return docs


def validate_with_jsonschema(instance: Dict[str, Any], schema_path: str) -> List[str]:
    try:
        import jsonschema
    except Exception:
        return ["jsonschema package not installed; skipping JSON Schema validation"]

    with open(schema_path, "r", encoding="utf-8") as f:
        schema = json.load(f)

    validator = jsonschema.Draft7Validator(schema)
    errors = [f"{list(e.path)}: {e.message}" for e in validator.iter_errors(instance)]
    return errors


def validate_openapi_spec(openapi_path: str) -> List[str]:
    try:
        from openapi_spec_validator import validate_spec
        import yaml
    except Exception:
        return ["openapi-spec-validator or pyyaml not installed; skipping OpenAPI validation"]

    with open(openapi_path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f)

    try:
        validate_spec(spec)
        return []
    except Exception as e:
        return [str(e)]


def write_jsonl(objects: List[Dict[str, Any]], path: str) -> None:
    with open(path, "w", encoding="utf-8") as f:
        for obj in objects:
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")


def main():
    parser = argparse.ArgumentParser(description="Run incident analysis pipeline")
    parser.add_argument("--input", required=True, help="Input file or directory (json/jsonl)")
    parser.add_argument("--output-dir", required=True, help="Directory to write outputs")
    parser.add_argument("--schema", help="Optional JSON Schema file to validate augmented payloads")
    parser.add_argument("--openapi", help="Optional OpenAPI file to validate the spec")
    parser.add_argument("--weights", help="Optional JSON file with scoring weights (overrides INCIDENT_WEIGHTS_PATH env var)")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    inputs = load_inputs(args.input)
    augmented_list = []
    analysis_list = []

    # Load optional weights file if provided via --weights or env INCIDENT_WEIGHTS_PATH
    weights = None
    weights_path = args.weights or os.environ.get("INCIDENT_WEIGHTS_PATH")
    if weights_path and os.path.exists(weights_path):
        try:
            with open(weights_path, "r", encoding="utf-8") as wf:
                weights = json.load(wf)
        except Exception:
            weights = None

    for i, doc in enumerate(inputs):
        res = analyze_incident(doc, weights=weights)
        augmented = res["augmented"]
        analysis = res["analysis"]
        analysis["source_index"] = i

        # Optional schema validation
        if args.schema:
            errs = validate_with_jsonschema(augmented, args.schema)
            analysis["json_schema_errors"] = errs

        augmented_list.append(augmented)
        analysis_list.append(analysis)

    # Optional OpenAPI validation
    openapi_errors = []
    if args.openapi:
        openapi_errors = validate_openapi_spec(args.openapi)

    # Write outputs
    augmented_path = out_dir / "augmented.jsonl"
    analysis_path = out_dir / "analysis.jsonl"
    write_jsonl(augmented_list, str(augmented_path))
    write_jsonl(analysis_list, str(analysis_path))

    # Summary
    summary = {
        "num_input_docs": len(inputs),
        "augmented_path": str(augmented_path),
        "analysis_path": str(analysis_path),
        "openapi_errors": openapi_errors,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
