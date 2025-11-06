#!/usr/bin/env python3
"""Generate synthetic incident payloads (JSONL) with controllable inconsistencies.
"""
import argparse
import json
import random
from pathlib import Path

KEYWORDS = ["exposure", "exposures", "rescue", "rescues", "casualty", "casualties"]


def make_incident(i: int, inconsistency_rate: float = 0.3):
    # narrative counts
    exposures_count = random.randint(0, 5)
    rescues_count = random.randint(0, 3)
    # narrative text mentions counts
    narrative = f"Witnesses reported {exposures_count} exposures and {rescues_count} rescues at the scene."

    # base payload
    payload = {
        "incident_id": f"synthetic-{i}",
        "title": f"Synthetic Incident {i}",
        "details": {
            "summary": f"Auto-generated incident {i}",
            "narrative": narrative,
        },
        "dispatch": {
            "disposition": []
        },
        "casualty_rescues": [],
        "exposures": [],
    }

    # Fill casualty_rescues with some entries matching rescues_count
    for r in range(rescues_count):
        payload["casualty_rescues"].append({
            "id": f"cr-{i}-{r}",
            "outcome": "rescued",
            "person": {"age_range": "adult", "sex": "unknown"},
        })

    # Decide whether to introduce inconsistency: mention >0 exposures but leave exposures empty
    if exposures_count > 0 and random.random() < inconsistency_rate:
        # leave exposures empty to create inconsistency
        pass
    else:
        for e in range(exposures_count):
            payload["exposures"].append({
                "id": f"exp-{i}-{e}",
                "hazard": "chemical",
                "level": random.choice(["low", "medium", "high"]),
            })

    # Occasionally drop required-ish top-level fields to simulate missing data
    if random.random() < 0.05:
        payload.pop("title", None)
    if random.random() < 0.03:
        payload["details"]["narrative"] = ""

    return payload


def main():
    parser = argparse.ArgumentParser(description="Generate synthetic incident JSONL")
    parser.add_argument("--count", type=int, default=1000)
    parser.add_argument("--out", default="/Users/test/Downloads/synthetic_incidents.jsonl")
    parser.add_argument("--inconsistency-rate", type=float, default=0.3,
                        help="Fraction of incidents where narrative mentions exposures but exposures list is empty")
    args = parser.parse_args()

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)

    with outp.open("w", encoding="utf-8") as f:
        for i in range(args.count):
            obj = make_incident(i, args.inconsistency_rate)
            f.write(json.dumps(obj, ensure_ascii=False))
            f.write("\n")

    print(f"Wrote {args.count} synthetic incidents to {str(outp)}")


if __name__ == "__main__":
    main()
