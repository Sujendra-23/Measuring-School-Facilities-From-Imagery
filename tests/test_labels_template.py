"""The blank hand-labeling sheet: shape, and no leaked model predictions."""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validation"))
import evaluate_labels as ev  # noqa: E402
import make_labels_template as mk  # noqa: E402

ROOT = os.path.join(os.path.dirname(__file__), "..")


def test_committed_template_covers_every_school_and_attribute_and_is_blank():
    template = pd.read_csv(mk.TEMPLATE_PATH, dtype=str, keep_default_na=False)
    schools = pd.read_csv(os.path.join(ROOT, "output", "measurements.csv"), dtype={"school_id": str})
    assert len(template) == len(schools) * len(mk.ATTRIBUTES) == 175
    assert set(template["school_id"]) == set(schools["school_id"])
    assert set(template["attribute"]) == set(ev.FIELDS) == set(mk.ATTRIBUTES)
    assert (template["label"] == "").all() and (template["notes"] == "").all()
    assert (template["image_path"] == "output/images/" + template["school_id"] + ".png").all()


def test_template_carries_no_model_output():
    template = pd.read_csv(mk.TEMPLATE_PATH, dtype=str, keep_default_na=False)
    assert list(template.columns) == mk.COLUMNS
    assert not any("confidence" in c or "predicted" in c or "model" in c for c in template.columns)


def test_build_template_from_a_fixture_never_reads_predictions(tmp_path):
    measurements = tmp_path / "m.csv"
    pd.DataFrame({"school_id": ["1", "2"], "school_name": ["One", "Two"],
                  "solar_present": [True, False], "solar_confidence": [0.9, 0.1]}).to_csv(measurements, index=False)
    built = mk.build_template(str(measurements), image_dir=str(tmp_path / "images"))
    assert len(built) == 2 * len(mk.ATTRIBUTES)
    assert (built["label"] == "").all()
    assert "solar_present" not in built.columns


def test_a_blank_template_evaluates_to_nothing(tmp_path):
    rows, summary = ev.load_labeled_rows(mk.TEMPLATE_PATH, os.path.join(ROOT, "output", "measurements.csv"))
    assert rows == [] and summary["labeled"] == 0 and summary["skipped"] == 175
