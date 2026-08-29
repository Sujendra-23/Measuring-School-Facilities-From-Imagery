"""
End-to-end run: read the school list, resolve each campus location, pull a
satellite image, run it through the vision model, and write one row per
school to output/measurements.csv.

Run with (from the repo root):  python src/pipeline.py
"""

import sys
import time

import pandas as pd

import config
import geolocate
import imagery
import vision_extract

OUTPUT_COLUMNS = [
    "school_id", "school_name",
    "solar_present", "solar_area_m2", "solar_confidence",
    "portables_count", "portables_confidence",
    "fence_status", "fence_type", "fence_confidence",
    "track_present", "track_confidence",
    "sports_fields_count", "sports_fields_confidence",
    "hard_courts_count", "hard_courts_confidence",
    "pool_present", "pool_confidence",
    "imagery_date", "imagery_source", "meters_per_pixel",
    "location_lat", "location_lon", "location_source", "location_confidence",
    "vision_model", "notes",
]


def process_school(row):
    """Run one school through the full pipeline. Returns a dict matching OUTPUT_COLUMNS."""
    school_id = row["school_id"]
    school_name = row["school_name"]
    print(f"[{school_id}] {school_name} ({row['city']}, {row['state']}) ...", file=sys.stderr)

    location = geolocate.resolve_location(school_name, row["latitude"], row["longitude"])
    print(f"  location: {location.source}, confidence={location.confidence:.2f}", file=sys.stderr)

    try:
        image = imagery.fetch_image(school_id, location)
    except Exception as exc:  # network/service failures shouldn't kill the whole run
        print(f"  FAILED to fetch imagery: {exc}", file=sys.stderr)
        return _failed_row(row, location, f"imagery fetch failed: {exc}")

    boundary_confirmed = location.bbox is not None
    boundary_note = (
        f"matched OSM feature '{location.matched_name}'" if location.matched_name
        else "no OSM match; using a default-size crop around the CCD coordinate"
    )

    result = vision_extract.analyze_image(
        image.file_path, image.meters_per_pixel, boundary_confirmed, boundary_note
    )
    time.sleep(config.OPENAI_DELAY_SECONDS)

    if result.error:
        print(f"  FAILED vision extraction: {result.error}", file=sys.stderr)
        return _failed_row(row, location, f"vision extraction failed: {result.error}", image)

    v = result.raw
    return {
        "school_id": school_id,
        "school_name": school_name,
        "solar_present": v.get("solar_present"),
        "solar_area_m2": v.get("solar_area_m2"),
        "solar_confidence": v.get("solar_confidence"),
        "portables_count": v.get("portables_count"),
        "portables_confidence": v.get("portables_confidence"),
        "fence_status": v.get("fence_status"),
        "fence_type": v.get("fence_type"),
        "fence_confidence": v.get("fence_confidence"),
        "track_present": v.get("track_present"),
        "track_confidence": v.get("track_confidence"),
        "sports_fields_count": v.get("sports_fields_count"),
        "sports_fields_confidence": v.get("sports_fields_confidence"),
        "hard_courts_count": v.get("hard_courts_count"),
        "hard_courts_confidence": v.get("hard_courts_confidence"),
        "pool_present": v.get("pool_present"),
        "pool_confidence": v.get("pool_confidence"),
        "imagery_date": image.acquisition_date,
        "imagery_source": "USGS NAIP",
        "meters_per_pixel": round(image.meters_per_pixel, 3),
        "location_lat": location.lat,
        "location_lon": location.lon,
        "location_source": location.source,
        "location_confidence": round(location.confidence, 2),
        "vision_model": result.model,
        "notes": v.get("notes", ""),
    }


def _failed_row(row, location, reason, image=None):
    """A row that keeps the schema intact but makes the failure obvious rather than silent."""
    blank = {col: None for col in OUTPUT_COLUMNS}
    blank.update({
        "school_id": row["school_id"],
        "school_name": row["school_name"],
        "location_lat": location.lat,
        "location_lon": location.lon,
        "location_source": location.source,
        "location_confidence": round(location.confidence, 2),
        "imagery_date": image.acquisition_date if image else None,
        "imagery_source": "USGS NAIP" if image else None,
        "notes": reason,
    })
    return blank


def main():
    schools = pd.read_csv(config.DATA_CSV, dtype={"school_id": str})

    rows = []
    for _, row in schools.iterrows():
        try:
            rows.append(process_school(row))
        except Exception as exc:  # a bug or an unhandled API error shouldn't sink the whole batch
            print(f"  UNEXPECTED FAILURE on {row['school_id']}: {exc}", file=sys.stderr)
            blank = {col: None for col in OUTPUT_COLUMNS}
            blank["school_id"] = row["school_id"]
            blank["school_name"] = row["school_name"]
            blank["notes"] = f"unexpected pipeline error: {exc}"
            rows.append(blank)

    out = pd.DataFrame(rows, columns=OUTPUT_COLUMNS)
    out.to_csv(config.MEASUREMENTS_CSV, index=False)
    print(f"\nWrote {len(out)} rows to {config.MEASUREMENTS_CSV}", file=sys.stderr)


if __name__ == "__main__":
    main()
