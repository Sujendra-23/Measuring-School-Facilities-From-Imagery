"""
Score output/measurements.csv against YOUR hand labels.

There are no hand-labeled facility results in this repo until you fill in
validation/labels.csv (copy validation/labels_template.csv and complete the `label`
column). Until then this script has nothing to report and says so; every other
validation file here is model-vs-model or a location check, not facility ground
truth. See the README's "Independent evaluation" section.

Run from the repo root:
    python validation/evaluate_labels.py
    python validation/evaluate_labels.py --labels path/to/labels.csv --out validation/evaluation_report.md

What it reports, over the rows you actually labeled (blank, `unsure` and `?` rows
are skipped and counted):
  1. Per-field accuracy, for all seven attributes.
  2. Precision / recall / F1 for the boolean fields (solar, track, pool), with
     "present" as the positive class.
  3. For the count fields (portables, sports fields, hard courts): exact-match
     rate, within-one rate, and mean absolute error.
  4. Confusion tables for portables (count vs count) and fence status.
  5. Confidence calibration: stated confidence in bins vs how often the model was
     actually right, pooled across fields, plus expected calibration error (ECE).
     A model that says 0.9 should be right about 9 times in 10; on 25 schools each
     bin is a handful of rows, so read the table as a direction, not a measurement.
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import config  # noqa: E402

# attribute -> (measurements.csv value column, its confidence column, kind)
FIELDS = {
    "solar": ("solar_present", "solar_confidence", "bool"),
    "portables_count": ("portables_count", "portables_confidence", "count"),
    "fence_status": ("fence_status", "fence_confidence", "category"),
    "track": ("track_present", "track_confidence", "bool"),
    "sports_fields_count": ("sports_fields_count", "sports_fields_confidence", "count"),
    "hard_courts_count": ("hard_courts_count", "hard_courts_confidence", "count"),
    "pool": ("pool_present", "pool_confidence", "bool"),
}
FENCE_VALUES = ["full", "partial", "none"]
SKIP_LABELS = {"", "unsure", "?", "n/a", "na"}
# Left-closed bins; the top one also holds a confidence of exactly 1.0.
CALIBRATION_BINS = [0.0, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0 + 1e-9]
CALIBRATION_LABELS = ["[0.0, 0.5)", "[0.5, 0.6)", "[0.6, 0.7)", "[0.7, 0.8)", "[0.8, 0.9)", "[0.9, 1.0]"]
DEFAULT_LABELS = os.path.join(os.path.dirname(__file__), "labels.csv")

_TRUE = {"true", "t", "yes", "y", "1"}
_FALSE = {"false", "f", "no", "n", "0"}


class LabelError(ValueError):
    """A label cell can't be read as the attribute's type; the message names the row."""


def _parse_bool(text):
    lowered = text.strip().lower()
    if lowered in _TRUE:
        return True
    if lowered in _FALSE:
        return False
    raise ValueError("expected true/false")


def _parse_count(text):
    value = float(text.strip())
    if value != int(value) or value < 0:
        raise ValueError("expected a whole number >= 0")
    return int(value)


def _parse_category(text):
    lowered = text.strip().lower()
    if lowered not in FENCE_VALUES:
        raise ValueError("expected full, partial or none")
    return lowered


PARSERS = {"bool": _parse_bool, "count": _parse_count, "category": _parse_category}


def _normalize_prediction(kind, value):
    """measurements.csv stores booleans as 'True'/'False' text and counts as numbers."""
    if kind == "bool":
        return _parse_bool(str(value))
    if kind == "count":
        return int(float(value))
    return str(value).strip().lower()


def load_labeled_rows(labels_csv, measurements_csv):
    """
    Join hand labels to model output. Returns (rows, summary) where rows is a list of
    dicts: school_id, attribute, kind, truth, predicted, confidence.
    """
    labels = pd.read_csv(labels_csv, dtype=str, keep_default_na=False)
    missing_columns = {"school_id", "attribute", "label"} - set(labels.columns)
    if missing_columns:
        raise LabelError(f"{labels_csv} is missing columns: {sorted(missing_columns)}")
    measurements = pd.read_csv(measurements_csv, dtype={"school_id": str}).set_index("school_id")

    rows, skipped, errors = [], 0, []
    for line_number, record in enumerate(labels.to_dict("records"), start=2):
        attribute = record["attribute"].strip()
        if attribute not in FIELDS:
            errors.append(f"line {line_number}: unknown attribute {attribute!r}")
            continue
        raw = record["label"].strip()
        if raw.lower() in SKIP_LABELS:
            skipped += 1
            continue
        value_column, confidence_column, kind = FIELDS[attribute]
        school_id = record["school_id"].strip()
        if school_id not in measurements.index:
            errors.append(f"line {line_number}: school {school_id} is not in {measurements_csv}")
            continue
        try:
            truth = PARSERS[kind](raw)
        except ValueError as exc:
            errors.append(f"line {line_number}: {school_id} {attribute} label {raw!r}: {exc}")
            continue
        predicted_row = measurements.loc[school_id]
        rows.append({
            "school_id": school_id,
            "attribute": attribute,
            "kind": kind,
            "truth": truth,
            "predicted": _normalize_prediction(kind, predicted_row[value_column]),
            "confidence": float(predicted_row[confidence_column]),
        })
    if errors:
        raise LabelError("Fix these label rows and re-run:\n  " + "\n  ".join(errors))
    return rows, {"labeled": len(rows), "skipped": skipped, "total": len(labels)}


def per_field_accuracy(rows):
    table = []
    for attribute in FIELDS:
        subset = [r for r in rows if r["attribute"] == attribute]
        if subset:
            correct = sum(r["truth"] == r["predicted"] for r in subset)
            table.append({"attribute": attribute, "n": len(subset), "correct": correct,
                          "accuracy": correct / len(subset)})
    return pd.DataFrame(table, columns=["attribute", "n", "correct", "accuracy"])


def boolean_metrics(rows):
    """Precision/recall/F1 with True as the positive class. None where undefined (no denominator)."""
    table = []
    for attribute, (_, _, kind) in FIELDS.items():
        if kind != "bool":
            continue
        subset = [r for r in rows if r["attribute"] == attribute]
        if not subset:
            continue
        tp = sum(r["truth"] and r["predicted"] for r in subset)
        fp = sum((not r["truth"]) and r["predicted"] for r in subset)
        fn = sum(r["truth"] and (not r["predicted"]) for r in subset)
        tn = len(subset) - tp - fp - fn
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision and recall else (
            0.0 if precision is not None and recall is not None else None)
        table.append({"attribute": attribute, "n": len(subset), "tp": tp, "fp": fp, "fn": fn,
                      "tn": tn, "precision": precision, "recall": recall, "f1": f1})
    return pd.DataFrame(table, columns=["attribute", "n", "tp", "fp", "fn", "tn",
                                        "precision", "recall", "f1"])


def count_metrics(rows):
    table = []
    for attribute, (_, _, kind) in FIELDS.items():
        if kind != "count":
            continue
        subset = [r for r in rows if r["attribute"] == attribute]
        if not subset:
            continue
        errors = [abs(r["truth"] - r["predicted"]) for r in subset]
        table.append({
            "attribute": attribute,
            "n": len(subset),
            "exact_match": sum(e == 0 for e in errors) / len(subset),
            "within_one": sum(e <= 1 for e in errors) / len(subset),
            "mae": sum(errors) / len(subset),
        })
    return pd.DataFrame(table, columns=["attribute", "n", "exact_match", "within_one", "mae"])


def confusion_table(rows, attribute):
    """Rows = your label, columns = the model's answer, counts in cells."""
    subset = [r for r in rows if r["attribute"] == attribute]
    if not subset:
        return None
    if attribute == "fence_status":
        order = FENCE_VALUES
    else:
        order = sorted({r["truth"] for r in subset} | {r["predicted"] for r in subset})
    table = pd.DataFrame(0, index=pd.Index(order, name="label \\ model"), columns=order)
    for r in subset:
        table.loc[r["truth"], r["predicted"]] += 1
    return table


def calibration_table(rows):
    """Bin by the model's stated confidence; compare mean stated confidence to actual accuracy."""
    if not rows:
        return pd.DataFrame(columns=["bin", "n", "mean_confidence", "accuracy", "gap"]), None
    frame = pd.DataFrame(rows)
    frame["correct"] = frame["truth"] == frame["predicted"]
    frame["bin"] = pd.cut(frame["confidence"], CALIBRATION_BINS, right=False, labels=CALIBRATION_LABELS)
    table = []
    for label, group in frame.groupby("bin", observed=True):
        table.append({
            "bin": label,
            "n": len(group),
            "mean_confidence": group["confidence"].mean(),
            "accuracy": group["correct"].mean(),
            "gap": group["confidence"].mean() - group["correct"].mean(),
        })
    result = pd.DataFrame(table)
    ece = float((result["n"] * result["gap"].abs()).sum() / result["n"].sum())
    return result, ece


def _fmt(frame):
    return frame.to_string(index=False, float_format=lambda v: f"{v:.2f}", na_rep="n/a")


def build_report(rows, summary):
    lines = [f"Hand-labeled rows used: {summary['labeled']} of {summary['total']} "
             f"({summary['skipped']} left blank or marked unsure).", ""]
    if not rows:
        lines.append("No labeled rows: nothing to evaluate. Fill in the `label` column of "
                     "validation/labels.csv first.")
        return "\n".join(lines) + "\n"

    lines += ["## Per-field accuracy", _fmt(per_field_accuracy(rows)), ""]
    booleans = boolean_metrics(rows)
    if len(booleans):
        lines += ["## Boolean fields (positive class = present)", _fmt(booleans), ""]
    counts = count_metrics(rows)
    if len(counts):
        lines += ["## Count fields", _fmt(counts), ""]
    for attribute, title in (("portables_count", "Portables"), ("fence_status", "Fence status")):
        table = confusion_table(rows, attribute)
        if table is not None:
            lines += [f"## Confusion: {title} (rows = your label, columns = model)", table.to_string(), ""]
    calibration, ece = calibration_table(rows)
    lines += ["## Confidence calibration (all fields pooled)", _fmt(calibration),
              f"Expected calibration error: {ece:.3f}" if ece is not None else "", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    parser.add_argument("--labels", default=DEFAULT_LABELS, help="filled-in labels CSV")
    parser.add_argument("--measurements", default=config.MEASUREMENTS_CSV)
    parser.add_argument("--out", help="also write the report to this file")
    args = parser.parse_args()

    if not os.path.exists(args.labels):
        print(f"{args.labels} does not exist. No hand labels = no independent evaluation.\n"
              "Copy validation/labels_template.csv to validation/labels.csv and fill in `label`.",
              file=sys.stderr)
        return 1
    try:
        rows, summary = load_labeled_rows(args.labels, args.measurements)
    except LabelError as exc:
        print(exc, file=sys.stderr)
        return 1

    report = build_report(rows, summary)
    print(report)
    if args.out:
        with open(args.out, "w") as f:
            f.write(report)
        print(f"Wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
