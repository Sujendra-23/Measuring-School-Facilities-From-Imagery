"""
Optional part of the brief: "pick one measure and show how it changes
across two or more dates, for as many schools as feasible."

We pick rooftop solar -- a manual screenshot check against the main pipeline
(src/) had flagged three candidate schools (Bel Air, Bertha, Wells Middle)
where current Google imagery looked like it might show panels our single
NAIP snapshot didn't, so tracking solar over time is motivated by a real
lead, not an arbitrary choice. That lead only partly held up once actually
tested here: Bertha shows no solar at either date (the original screenshot
read was likely wrong), and Bel Air's miss turns out to be a real detection
failure, not a timing gap -- see README.md / memo.pdf for the confirmed
result, which also credits Spring Lake Heights, not named in the original
three.

This does NOT reuse NAIP: NAIP's live ImageServer only serves the current
mosaic, not a queryable history (confirmed directly -- see
historical_imagery.py's docstring). Instead both time points come from
Esri's Wayback Imagery archive, a free, keyless, dated satellite basemap
archive going back to 2014, so both readings come from the same provider --
an apples-to-apples comparison, not NAIP-then vs. Wayback-now.

Caveat worth naming: Wayback's image quality isn't guaranteed to improve
monotonically with release date -- for at least one school here, the ~2016
snapshot was visibly sharper than the ~2026 one. That's a property of the
archive (different underlying captures per release, not our doing), not a
bug in this script, and the model's own confidence should reflect it rather
than us assuming a newer date always means a clearer image.

Run with (from the repo root):  python optional/solar_over_time.py
"""

import base64
import io
import json
import os
import sys
import time

import pandas as pd
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
import config  # noqa: E402
from vision_extract import _backoff_seconds, _strip_code_fences  # noqa: E402
import historical_imagery as hi  # noqa: E402

OLD_TARGET_DATE = "2017-01-01"  # ~9 years back from the newest release available
IMAGE_PIXELS_EQUIVALENT = 768  # 3x3 grid of 256px Wayback tiles

SOLAR_PROMPT = """You are looking at a top-down aerial image of a U.S. public school campus,
approximately {meters_per_pixel:.2f} meters per pixel, about {frame_m:.0f}m across.
This image is from a satellite basemap snapshot dated {date}.

Look only for rooftop solar panels on campus buildings: a regular grid of
dark, uniform rectangular panels, distinct from skylights, roof vents, HVAC
units, or a plain dark roof membrane (which can look superficially similar
at this resolution -- a real array is unusually regular and grid-like).

Respond with ONLY this JSON object, no markdown fences, no commentary:
{{
  "solar_present": true/false,
  "solar_confidence": number 0-1,
  "notes": "one sentence: what you saw, and anything that made this hard to read (image blur, low resolution for this particular snapshot, shadows, etc). Empty string if nothing notable."
}}

A confidence of 0.9 should mean you'd expect to be right about 9 times out
of 10. Image quality varies a lot between snapshot dates in this archive --
a blurrier or lower-resolution snapshot should pull confidence down, same as
it would for any other image quality problem.
"""


def _ask_about_solar(image, meters_per_pixel, date, attempts=3):
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode("utf-8")

    prompt = SOLAR_PROMPT.format(
        meters_per_pixel=meters_per_pixel, frame_m=meters_per_pixel * IMAGE_PIXELS_EQUIVALENT, date=date
    )
    body = {
        "model": config.OPENAI_MODEL,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ],
        }],
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
    schools = pd.read_csv(config.DATA_CSV, dtype={"school_id": str})
    # Reuse the location already resolved by the main pipeline instead of
    # re-running Overpass -- that work is already done and cached.
    measurements = pd.read_csv(config.MEASUREMENTS_CSV, dtype={"school_id": str}).set_index("school_id")

    releases = hi.load_releases()
    old_release = hi.closest_release(releases, OLD_TARGET_DATE)
    new_release = releases[-1]
    print(f"Comparing {old_release['date']} vs {new_release['date']} (of {len(releases)} available releases)",
          file=sys.stderr)

    out_dir = os.path.join(os.path.dirname(__file__), "images")
    os.makedirs(out_dir, exist_ok=True)

    rows = []
    for _, school in schools.iterrows():
        school_id, name = school["school_id"], school["school_name"]
        if school_id not in measurements.index:
            print(f"[{school_id}] skipping -- not in {config.MEASUREMENTS_CSV}", file=sys.stderr)
            continue
        lat = measurements.loc[school_id, "location_lat"]
        lon = measurements.loc[school_id, "location_lon"]
        print(f"[{school_id}] {name} ...", file=sys.stderr)

        row = {"school_id": school_id, "school_name": name,
               "old_release": old_release["date"], "new_release": new_release["date"]}
        try:
            for label, release in [("old", old_release), ("new", new_release)]:
                image, mpp = hi.fetch_crop(release["url_template"], lat, lon)
                image.save(os.path.join(out_dir, f"{school_id}_{label}.png"))
                result = _ask_about_solar(image, mpp, release["date"])
                row[f"{label}_solar_present"] = result.get("solar_present")
                row[f"{label}_solar_confidence"] = result.get("solar_confidence")
                row[f"{label}_notes"] = result.get("notes", "")
                time.sleep(config.OPENAI_DELAY_SECONDS)
        except Exception as exc:
            print(f"  FAILED: {exc}", file=sys.stderr)
            row["error"] = str(exc)

        rows.append(row)

    out = pd.DataFrame(rows)
    out_path = os.path.join(os.path.dirname(__file__), "solar_over_time.csv")
    out.to_csv(out_path, index=False)

    if "old_solar_present" in out.columns and "new_solar_present" in out.columns:
        changed = out[out["old_solar_present"] != out["new_solar_present"]]
        print(f"\n{len(changed)}/{len(out)} schools show a change in detected solar presence "
              f"between {old_release['date']} and {new_release['date']}:")
        if len(changed):
            print(changed[["school_name", "old_solar_present", "new_solar_present"]].to_string(index=False))
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
