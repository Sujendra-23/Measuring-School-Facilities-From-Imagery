"""
validation/evaluate_labels.py on a tiny synthetic fixture (four invented schools).

No hand-labeled facility data exists in this repo: these tests only check that the
scoring arithmetic is right, using numbers small enough to verify by hand. They say
nothing about how accurate the pipeline is.
"""

import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "validation"))
import evaluate_labels as ev  # noqa: E402

MEASUREMENT_COLUMNS = [
    "school_id", "school_name", "solar_present", "solar_confidence", "portables_count",
    "portables_confidence", "fence_status", "fence_confidence", "track_present",
    "track_confidence", "sports_fields_count", "sports_fields_confidence",
    "hard_courts_count", "hard_courts_confidence", "pool_present", "pool_confidence",
]


def _measurement(school_id, solar, solar_c, portables, portables_c, fence, fence_c, pool_c=0.95):
    return {
        "school_id": school_id, "school_name": f"School {school_id}",
        "solar_present": solar, "solar_confidence": solar_c,
        "portables_count": portables, "portables_confidence": portables_c,
        "fence_status": fence, "fence_confidence": fence_c,
        "track_present": False, "track_confidence": 0.8,
        "sports_fields_count": 0, "sports_fields_confidence": 0.5,
        "hard_courts_count": 0, "hard_courts_confidence": 0.5,
        "pool_present": False, "pool_confidence": pool_c,
    }


@pytest.fixture
def files(tmp_path):
    # measurements.csv writes booleans as the text "True"/"False", as the real file does.
    measurements = pd.DataFrame(
        [
            _measurement("A", True, 0.9, 0, 0.9, "partial", 0.6),
            _measurement("B", True, 0.8, 2, 0.8, "partial", 0.6),
            _measurement("C", False, 0.7, 0, 0.7, "none", 0.9),
            _measurement("D", False, 0.6, 1, 0.5, "full", 0.4),
        ],
        columns=MEASUREMENT_COLUMNS,
    )
    measurements_path = tmp_path / "measurements.csv"
    measurements.to_csv(measurements_path, index=False)

    labels = [
        # solar: A right, B wrong (model said yes), C wrong (model said no), D right
        ("A", "solar", "TRUE"), ("B", "solar", "no"), ("C", "solar", " 1 "), ("D", "solar", "false"),
        # portables: A right, B off by one, C right, D right
        ("A", "portables_count", "0"), ("B", "portables_count", "1"),
        ("C", "portables_count", "0"), ("D", "portables_count", "1.0"),
        # fence: A right, B wrong (said partial, truly full), C right, D left blank
        ("A", "fence_status", "Partial"), ("B", "fence_status", "full"),
        ("C", "fence_status", "none"), ("D", "fence_status", ""),
        # pool: all four labeled absent, model also says absent
        ("A", "pool", "false"), ("B", "pool", "false"), ("C", "pool", "false"), ("D", "pool", "false"),
        # not labeled at all: unsure and ? rows must be skipped, not scored
        ("A", "track", "unsure"), ("B", "track", "?"),
    ]
    labels_path = tmp_path / "labels.csv"
    pd.DataFrame(labels, columns=["school_id", "attribute", "label"]).to_csv(labels_path, index=False)
    return str(labels_path), str(measurements_path)


@pytest.fixture
def rows(files):
    loaded, summary = ev.load_labeled_rows(*files)
    return loaded, summary


def test_blank_and_unsure_rows_are_skipped_and_counted(rows):
    _, summary = rows
    assert summary == {"labeled": 15, "skipped": 3, "total": 18}


def test_per_field_accuracy(rows):
    table = ev.per_field_accuracy(rows[0]).set_index("attribute")
    assert table.loc["solar", "accuracy"] == pytest.approx(2 / 4)
    assert table.loc["portables_count", "accuracy"] == pytest.approx(3 / 4)
    assert table.loc["fence_status", ["n", "correct"]].tolist() == [3, 2]
    assert table.loc["pool", "accuracy"] == 1.0
    assert "track" not in table.index  # only unsure labels: no row, not a fake 0%


def test_boolean_precision_recall(rows):
    table = ev.boolean_metrics(rows[0]).set_index("attribute")
    solar = table.loc["solar"]
    # truth A=T B=F C=T D=F, model A=T B=T C=F D=F  ->  TP 1, FP 1 (B), FN 1 (C), TN 1
    assert (solar["tp"], solar["fp"], solar["fn"], solar["tn"]) == (1, 1, 1, 1)
    assert solar["precision"] == pytest.approx(0.5)
    assert solar["recall"] == pytest.approx(0.5)
    assert solar["f1"] == pytest.approx(0.5)
    pool = table.loc["pool"]
    assert pd.isna(pool["precision"]) and pd.isna(pool["recall"]) and pd.isna(pool["f1"])


def test_count_metrics(rows):
    portables = ev.count_metrics(rows[0]).set_index("attribute").loc["portables_count"]
    # |error| = 0, 1, 0, 0
    assert portables["exact_match"] == pytest.approx(0.75)
    assert portables["within_one"] == pytest.approx(1.0)
    assert portables["mae"] == pytest.approx(0.25)


def test_confusion_tables(rows):
    portables = ev.confusion_table(rows[0], "portables_count")
    assert portables.loc[0, 0] == 2          # A and C: labeled 0, model 0
    assert portables.loc[1, 2] == 1          # B: labeled 1, model said 2
    assert portables.loc[1, 1] == 1          # D: labeled 1, model said 1
    assert portables.to_numpy().sum() == 4
    fence = ev.confusion_table(rows[0], "fence_status")
    assert list(fence.index) == ["full", "partial", "none"]
    assert fence.loc["partial", "partial"] == 1
    assert fence.loc["full", "partial"] == 1  # B: truly full, model said partial
    assert fence.loc["none", "none"] == 1
    assert fence.to_numpy().sum() == 3
    assert ev.confusion_table(rows[0], "track") is None


def test_calibration_bins_and_ece_by_hand():
    def row(confidence, right):
        return {"confidence": confidence, "truth": 1, "predicted": 1 if right else 0}

    rows = [row(0.95, True), row(0.95, False), row(0.55, True), row(0.55, True), row(0.85, False)]
    table, ece = ev.calibration_table(rows)
    by_bin = table.set_index("bin")
    assert by_bin.loc["[0.5, 0.6)", ["n", "mean_confidence", "accuracy"]].tolist() == [2, 0.55, 1.0]
    assert by_bin.loc["[0.8, 0.9)", ["n", "mean_confidence", "accuracy"]].tolist() == [1, 0.85, 0.0]
    assert by_bin.loc["[0.9, 1.0]", ["n", "mean_confidence", "accuracy"]].tolist() == [2, 0.95, 0.5]
    # ECE = (2*0.45 + 1*0.85 + 2*0.45) / 5
    assert ece == pytest.approx(0.53)


def test_confidence_of_exactly_one_lands_in_the_top_bin():
    table, _ = ev.calibration_table([{"confidence": 1.0, "truth": True, "predicted": True}])
    assert table["bin"].tolist() == ["[0.9, 1.0]"]


def test_bad_labels_are_reported_with_row_numbers(tmp_path, files):
    _, measurements_path = files
    bad = tmp_path / "bad.csv"
    pd.DataFrame(
        [("A", "solar", "maybe"), ("B", "fence_status", "gated"), ("C", "portables_count", "1.5"),
         ("Z", "pool", "false"), ("A", "moat", "true")],
        columns=["school_id", "attribute", "label"],
    ).to_csv(bad, index=False)
    with pytest.raises(ev.LabelError) as excinfo:
        ev.load_labeled_rows(str(bad), measurements_path)
    message = str(excinfo.value)
    for fragment in ("line 2", "expected true/false", "line 3", "expected full, partial or none",
                     "line 4", "whole number", "line 5", "not in", "line 6", "unknown attribute"):
        assert fragment in message


def test_empty_labels_report_nothing_to_evaluate(tmp_path, files):
    _, measurements_path = files
    blank = tmp_path / "blank.csv"
    pd.DataFrame([("A", "solar", ""), ("B", "pool", "")],
                 columns=["school_id", "attribute", "label"]).to_csv(blank, index=False)
    loaded, summary = ev.load_labeled_rows(str(blank), measurements_path)
    assert loaded == []
    assert "nothing to evaluate" in ev.build_report(loaded, summary)


def test_full_report_mentions_every_section(rows):
    report = ev.build_report(*rows)
    for heading in ("Per-field accuracy", "Boolean fields", "Count fields", "Confusion: Portables",
                    "Confusion: Fence status", "Confidence calibration", "Expected calibration error"):
        assert heading in report


def test_main_without_a_labels_file_exits_nonzero(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["evaluate_labels.py", "--labels", str(tmp_path / "nope.csv")])
    assert ev.main() == 1
    assert "No hand labels" in capsys.readouterr().err
