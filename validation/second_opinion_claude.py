"""
Validation approach #3: a cross-vendor second opinion from Claude.

validation/second_opinion.py compares gpt-5.4 against gpt-4o, which is the same
vendor and so a weaker independence check (shared training data, correlated blind
spots). This sends the SAME cached images with the SAME prompt (src/vision_extract.py's
PROMPT_TEMPLATE) to Claude through the Anthropic API, requests the SAME JSON schema,
and writes one row per school to validation/second_opinion_claude.csv. It then
reports per-field agreement with the OpenAI results in output/measurements.csv.

Two honest limits. Agreement between two models is not accuracy: both can be wrong
the same way, which is what evaluate_labels.py (your hand labels) is for. And this
makes one call per school, whereas the primary pipeline resamples hard_courts_count
three times and takes the median, so hard-court disagreement is partly that
difference, not only a difference of models.

Needs ANTHROPIC_API_KEY (environment or .env); refuses to run without it. About 25
image calls. Run from the repo root:

    python validation/second_opinion_claude.py --dry-run     # list what would be sent, no calls
    python validation/second_opinion_claude.py --limit 3     # try a few first
    python validation/second_opinion_claude.py               # all schools
    python validation/second_opinion_claude.py --report-only # re-print agreement from the CSV
"""

import argparse
import base64
import json
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config  # noqa: E402
from vision_extract import _build_prompt, _strip_code_fences  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
OUT_PATH = os.path.join(os.path.dirname(__file__), "second_opinion_claude.csv")

COMPARE_FIELDS = [
    "solar_present", "portables_count", "fence_status",
    "track_present", "sports_fields_count", "hard_courts_count", "pool_present",
]
COUNT_FIELDS = ["portables_count", "sports_fields_count", "hard_courts_count"]
# Everything in the schema the prompt asks for, in the order the CSV is written.
SCHEMA_FIELDS = [
    "solar_present", "solar_area_m2", "solar_confidence",
    "portables_count", "portables_confidence",
    "fence_status", "fence_type", "fence_confidence",
    "track_present", "track_confidence",
    "sports_fields_count", "sports_fields_confidence",
    "hard_courts_count", "hard_courts_confidence",
    "pool_present", "pool_confidence", "notes",
]
CSV_COLUMNS = ["school_id", "school_name", "model", "input_tokens", "output_tokens"] + SCHEMA_FIELDS


def _boundary(row):
    """Same wording as validation/second_opinion.py, so the prompt matches the primary run's."""
    confirmed = row["location_source"] == "osm_school_grounds"
    note = (
        "matched an OSM school-grounds polygon" if confirmed
        else "no confirmed OSM match; using a default-size crop around the CCD coordinate"
    )
    return confirmed, note


def call_claude(image_path, meters_per_pixel, boundary_confirmed, boundary_note, attempts=3):
    """Returns (parsed_json_dict, usage_dict). Raises the last error if every attempt fails."""
    with open(image_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")
    body = {
        "model": config.CLAUDE_MODEL,
        "max_tokens": 2048,
        "temperature": 0,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
                {"type": "text", "text": _build_prompt(meters_per_pixel, boundary_confirmed, boundary_note)},
            ],
        }],
    }
    # Header auth only: requests echoes the URL in exception messages, and a key
    # must never end up in a log or results file.
    headers = {
        "x-api-key": config.ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(API_URL, json=body, headers=headers, timeout=90)
            response.raise_for_status()
            payload = response.json()
            text = "".join(block.get("text", "") for block in payload["content"] if block.get("type") == "text")
            return json.loads(_strip_code_fences(text)), payload.get("usage", {})
        except (requests.RequestException, KeyError, TypeError, json.JSONDecodeError) as exc:
            last_error = exc
            retry_after = getattr(getattr(exc, "response", None), "headers", {}).get("retry-after")
            time.sleep(float(retry_after) + 1 if retry_after else 2 * (attempt + 1))
    raise last_error


def _same(a, b):
    """Compare a measurements.csv cell with the model's JSON value despite type differences."""
    if pd.isna(a) and (b is None or pd.isna(b)):
        return True
    if isinstance(a, str) and a.strip().lower() in ("true", "false"):
        a = a.strip().lower() == "true"
    if isinstance(b, str) and b.strip().lower() in ("true", "false"):
        b = b.strip().lower() == "true"
    try:
        return a == b or float(a) == float(b)
    except (TypeError, ValueError):
        return str(a).strip().lower() == str(b).strip().lower()


def agreement(primary, second):
    """
    primary: measurements.csv as a DataFrame (OpenAI); second: second_opinion_claude.csv.
    Returns (per_field_table, row_level_table).
    """
    primary = primary.set_index("school_id")
    rows = []
    for _, other in second.iterrows():
        school_id = other["school_id"]
        if school_id not in primary.index:
            continue
        for field in COMPARE_FIELDS:
            first, theirs = primary.loc[school_id, field], other[field]
            rows.append({
                "school_id": school_id,
                "field": field,
                "openai_value": first,
                "claude_value": theirs,
                "agree": bool(_same(first, theirs)),
                "abs_diff": abs(float(first) - float(theirs)) if field in COUNT_FIELDS else None,
            })
    detail = pd.DataFrame(rows, columns=["school_id", "field", "openai_value", "claude_value",
                                         "agree", "abs_diff"])
    if detail.empty:
        return pd.DataFrame(columns=["field", "n", "agreement", "mean_abs_diff"]), detail
    summary = detail.groupby("field").agg(n=("agree", "size"), agreement=("agree", "mean"),
                                          mean_abs_diff=("abs_diff", "mean")).reset_index()
    summary = summary.set_index("field").loc[[f for f in COMPARE_FIELDS if f in set(summary["field"])]]
    return summary.reset_index(), detail


def print_report(primary, second):
    summary, detail = agreement(primary, second)
    if detail.empty:
        print("No overlapping schools between the two files.")
        return
    print(f"\nAgreement between {primary['vision_model'].iloc[0]} (primary, output/measurements.csv) and "
          f"{second['model'].iloc[0]} (second opinion), {second['school_id'].nunique()} schools:")
    print(summary.to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="-"))
    print(f"\nOverall agreement: {detail['agree'].mean():.2f} over {len(detail)} field comparisons")
    print("This is agreement between two models, not accuracy; see validation/evaluate_labels.py "
          "for scoring against hand labels.")


def main():
    parser = argparse.ArgumentParser(description="Cross-vendor second opinion: Claude vision.")
    parser.add_argument("--dry-run", action="store_true", help="list the images, make no API calls")
    parser.add_argument("--limit", type=int, help="only the first N schools")
    parser.add_argument("--report-only", action="store_true", help="skip the API; report from the existing CSV")
    args = parser.parse_args()

    primary = pd.read_csv(config.MEASUREMENTS_CSV, dtype={"school_id": str})
    if args.report_only:
        print_report(primary, pd.read_csv(OUT_PATH, dtype={"school_id": str}))
        return 0

    if args.limit:
        primary_subset = primary.head(args.limit)
    else:
        primary_subset = primary
    images = {row["school_id"]: os.path.join(config.IMAGE_CACHE_DIR, f"{row['school_id']}.png")
              for _, row in primary_subset.iterrows()}
    missing = [path for path in images.values() if not os.path.exists(path)]
    if missing:
        print(f"{len(missing)} cached image(s) missing (run src/pipeline.py first), e.g. {missing[0]}",
              file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"Would send {len(images)} images to {config.CLAUDE_MODEL} (no calls made):")
        for school_id, path in images.items():
            print(f"  {school_id}  {path}")
        return 0

    if not config.ANTHROPIC_API_KEY:
        print("ANTHROPIC_API_KEY is not set (environment or .env). Nothing was sent.", file=sys.stderr)
        return 2

    results, total_in, total_out = [], 0, 0
    for _, row in primary_subset.iterrows():
        school_id = row["school_id"]
        confirmed, note = _boundary(row)
        print(f"[{school_id}] asking {config.CLAUDE_MODEL} ...", file=sys.stderr)
        try:
            parsed, usage = call_claude(images[school_id], row["meters_per_pixel"], confirmed, note)
        except Exception as exc:  # report and continue; one bad image shouldn't lose the rest
            print(f"  FAILED: {type(exc).__name__}", file=sys.stderr)
            continue
        total_in += usage.get("input_tokens", 0)
        total_out += usage.get("output_tokens", 0)
        results.append({
            "school_id": school_id, "school_name": row["school_name"], "model": config.CLAUDE_MODEL,
            "input_tokens": usage.get("input_tokens"), "output_tokens": usage.get("output_tokens"),
            **{field: parsed.get(field) for field in SCHEMA_FIELDS},
        })
        time.sleep(1)

    if not results:
        print("No results produced; see errors above.", file=sys.stderr)
        return 1
    second = pd.DataFrame(results, columns=CSV_COLUMNS)
    second.to_csv(OUT_PATH, index=False)
    print(f"\nWrote {len(second)} rows to {OUT_PATH}")
    print(f"Tokens used: {total_in} input, {total_out} output "
          f"(multiply by your model's per-token price for the cost).")
    print_report(primary, second)
    return 0


if __name__ == "__main__":
    sys.exit(main())
