"""
Validation approach #1: an independent second vision model.

output/measurements.csv comes from OpenAI's gpt-5.4 (see src/vision_extract.py).
Here we send a subset of the same images, with the same prompt, to gpt-4o --
the former primary model -- and see how often they agree. That doubles as a
before/after comparison of the gpt-4o -> gpt-5.4 switch, on top of its
validation role.

A genuinely different provider would be the stronger design here -- two
vendors' models are less likely to share the same blind spots. That's not
what ended up here: the project settled on keeping everything on OpenAI.
Two models from the same provider can still disagree usefully, but they're
more likely to share correlated blind spots (similar training data, similar
failure modes) than two different vendors would -- so treat agreement here
as a weaker signal than a true cross-vendor check, not an equivalent one.
That trade-off is named here rather than left
for the reader to guess at.

Run with (from the repo root):  python validation/second_opinion.py
"""

import base64
import json
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config  # noqa: E402
from vision_extract import _backoff_seconds, _build_prompt, _strip_code_fences  # noqa: E402

# Schools picked by hand to spread across location-resolution outcomes and
# school level, not just the easy cases. See memo for why this matters.
SUBSET_SCHOOL_IDS = [
    "060483000471",  # Beverly Hills High -- OSM grounds match, urban, high
    "010282001124",  # Wedowee Middle -- no OSM match, rural, middle
    "360008802312",  # PS 78 Anne Hutchinson -- dense urban, primary
    "180283000341",  # Zionsville Community High -- large suburban campus
    "270543000204",  # Bertha Secondary -- very small rural school
    "421917006915",  # Pittsburgh Brashear HS -- OSM had it, name-match missed it (see memo)
    "481455000943",  # Coleman HS -- small rural Texas town
    "160000100084",  # Priest River Lamanna HS -- rural mountain west
]

COMPARE_FIELDS = [
    "solar_present", "portables_count", "fence_status",
    "track_present", "sports_fields_count", "hard_courts_count", "pool_present",
]


def _call_second_opinion(image_path, meters_per_pixel, boundary_confirmed, boundary_note, attempts=3):
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")

    prompt = _build_prompt(meters_per_pixel, boundary_confirmed, boundary_note)
    body = {
        "model": config.SECOND_OPINION_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
            ],
        }],
        # Matches the primary pipeline's call (vision_extract.py): without this,
        # gpt-4o's default temperature adds its own randomness on top of any
        # real disagreement with gpt-5.4, which isn't what "second opinion"
        # should mean -- found while explaining an odd swing in this file's
        # own results, not a hypothetical.
        "temperature": 0,
    }
    headers = {"Authorization": f"Bearer {config.OPENAI_API_KEY}"}

    last_error = None
    for attempt in range(attempts):
        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions", json=body, headers=headers, timeout=60
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"]
            return json.loads(_strip_code_fences(text))
        except (requests.RequestException, KeyError, IndexError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(_backoff_seconds(exc, attempt))
    raise last_error


def main():
    measurements = pd.read_csv(config.MEASUREMENTS_CSV, dtype={"school_id": str}).set_index("school_id")

    comparison_rows = []
    for school_id in SUBSET_SCHOOL_IDS:
        if school_id not in measurements.index:
            print(f"skipping {school_id}: not in measurements.csv", file=sys.stderr)
            continue
        primary_row = measurements.loc[school_id]
        image_path = os.path.join(config.IMAGE_CACHE_DIR, f"{school_id}.png")
        boundary_confirmed = primary_row["location_source"] == "osm_school_grounds"
        # measurements.csv doesn't persist the matched OSM feature's name, so
        # this can't be byte-identical to the primary run's boundary_note --
        # but it should still say the same THING (matched a traced polygon,
        # or didn't), not a bare technical label, since the whole point of
        # this file is the same prompt going to a second model.
        boundary_note = (
            "matched an OSM school-grounds polygon" if boundary_confirmed
            else "no confirmed OSM match; using a default-size crop around the CCD coordinate"
        )

        print(f"[{school_id}] asking {config.SECOND_OPINION_MODEL} for a second opinion ...", file=sys.stderr)
        try:
            second_result = _call_second_opinion(
                image_path,
                primary_row["meters_per_pixel"],
                boundary_confirmed,
                boundary_note,
            )
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            continue

        for field in COMPARE_FIELDS:
            primary_value = primary_row.get(field)
            second_value = second_result.get(field)
            comparison_rows.append({
                "school_id": school_id,
                "field": field,
                f"{config.OPENAI_MODEL}_value": primary_value,
                f"{config.SECOND_OPINION_MODEL}_value": second_value,
                "agree": primary_value == second_value,
            })
        time.sleep(1)

    if not comparison_rows:
        print("No comparisons produced -- see errors above.", file=sys.stderr)
        return

    comparisons = pd.DataFrame(comparison_rows)
    out_path = os.path.join(os.path.dirname(__file__), "second_opinion_results.csv")
    comparisons.to_csv(out_path, index=False)

    schools_covered = comparisons["school_id"].nunique()
    print(f"\nPer-field agreement between {config.OPENAI_MODEL} (primary) and "
          f"{config.SECOND_OPINION_MODEL} (second opinion), "
          f"{schools_covered}/{len(SUBSET_SCHOOL_IDS)} schools covered:")
    summary = comparisons.groupby("field")["agree"].mean().sort_values()
    print(summary.to_string())
    print(f"\nOverall agreement: {comparisons['agree'].mean():.2f}")
    print(f"Wrote row-level comparisons to {out_path}")


if __name__ == "__main__":
    main()
