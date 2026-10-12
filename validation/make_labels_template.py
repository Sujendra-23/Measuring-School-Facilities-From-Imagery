"""
Build the blank hand-labeling sheet: validation/labels_template.csv.

One row per school x attribute (25 schools x 7 attributes = 175 rows). The school
id, name and cached image path are prefilled; the `label` and `notes` columns are
left empty on purpose. Model predictions are deliberately NOT included: a labeler
who can see what the model said anchors on it, which defeats the point of an
independent evaluation. Label from the image (or better, from a fresh look at the
campus in a map viewer) before ever opening output/measurements.csv.

How to use it:
    python validation/make_labels_template.py          # regenerates the blank template
    cp validation/labels_template.csv validation/labels.csv
    # fill in the `label` column of labels.csv by hand, then:
    python validation/evaluate_labels.py

Run from the repo root. output/images/ is gitignored, so the image paths point at
files that exist only on a machine that has run the pipeline; the script warns
about any that are missing but still writes the row.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config  # noqa: E402

# attribute -> (what to enter, the allowed values spelled out for the labeler)
ATTRIBUTES = {
    "solar": "true / false: any rooftop solar panels on a campus building",
    "portables_count": "integer >= 0: portable/modular classroom buildings",
    "fence_status": "full / partial / none: perimeter fencing around the campus",
    "track": "true / false: a running track (lane markings or paved oval)",
    "sports_fields_count": "integer >= 0: full-size team-sport fields",
    "hard_courts_count": "integer >= 0: distinct paved basketball/tennis courts",
    "pool": "true / false: a swimming pool on campus grounds",
}

COLUMNS = ["school_id", "school_name", "attribute", "image_path", "allowed_values", "label", "notes"]
TEMPLATE_PATH = os.path.join(os.path.dirname(__file__), "labels_template.csv")


def build_template(measurements_csv=config.MEASUREMENTS_CSV, image_dir=config.IMAGE_CACHE_DIR):
    # Only the id and name come from measurements.csv -- never a prediction.
    schools = pd.read_csv(measurements_csv, dtype={"school_id": str}, usecols=["school_id", "school_name"])
    rows = []
    for _, school in schools.iterrows():
        image_path = f"{image_dir}/{school['school_id']}.png"
        if not os.path.exists(image_path):
            print(f"warning: {image_path} not found on this machine", file=sys.stderr)
        for attribute, allowed in ATTRIBUTES.items():
            rows.append({
                "school_id": school["school_id"],
                "school_name": school["school_name"],
                "attribute": attribute,
                "image_path": image_path,
                "allowed_values": allowed,
                "label": "",
                "notes": "",
            })
    return pd.DataFrame(rows, columns=COLUMNS)


def main():
    template = build_template()
    template.to_csv(TEMPLATE_PATH, index=False)
    print(f"Wrote {len(template)} rows ({template['school_id'].nunique()} schools x "
          f"{len(ATTRIBUTES)} attributes) to {TEMPLATE_PATH}")


if __name__ == "__main__":
    main()
