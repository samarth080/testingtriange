"""Unit tests for eval/metrics.py pure functions. No I/O or DB needed."""
import os
import sys

import pytest

# Add eval/ to path so we can import metrics without installing
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../eval"))

from metrics import aggregate_metrics, format_report, label_metrics


# ---------------------------------------------------------------------------
# label_metrics
# ---------------------------------------------------------------------------


def test_label_metrics_perfect_match():
    result = label_metrics(["bug", "perf"], ["bug", "perf"])
    assert result["precision"] == 1.0
    assert result["recall"] == 1.0
    assert result["f1"] == 1.0


def test_label_metrics_no_overlap():
    result = label_metrics(["bug"], ["enhancement"])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_label_metrics_partial_overlap():
    result = label_metrics(["bug", "docs"], ["bug", "perf"])
    # TP=1, predicted=2 → P=0.5, actual=2 → R=0.5, F1=0.5
    assert result["precision"] == 0.5
    assert result["recall"] == 0.5
    assert abs(result["f1"] - 0.5) < 1e-9


def test_label_metrics_empty_predicted():
    result = label_metrics([], ["bug"])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_label_metrics_empty_actual():
    # No ground truth labels — treat as all-zero (can't recall what doesn't exist)
    result = label_metrics(["bug"], [])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_label_metrics_both_empty():
    result = label_metrics([], [])
    assert result["precision"] == 0.0
    assert result["recall"] == 0.0
    assert result["f1"] == 0.0


def test_label_metrics_case_insensitive():
    """Predicted 'Bug' should match actual 'bug'."""
    m = label_metrics(["Bug", "Feature"], ["bug", "feature"])
    assert m["f1"] == 1.0


def test_label_metrics_strips_whitespace():
    """Labels with surrounding spaces should match."""
    m = label_metrics([" bug "], ["bug"])
    assert m["f1"] == 1.0


def test_label_metrics_mixed_case_partial():
    """Case normalization on partial overlap: 1/2 predicted correct."""
    m = label_metrics(["BUG", "Enhancement"], ["bug", "feature"])
    # TP=1 (bug), pred_set=2, actual_set=2
    assert m["precision"] == pytest.approx(0.5)
    assert m["recall"] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# aggregate_metrics
# ---------------------------------------------------------------------------


def test_aggregate_metrics_basic():
    per_issue = [
        {"precision": 1.0, "recall": 1.0, "f1": 1.0, "latency_ms": 100, "confidence": "high"},
        {"precision": 0.0, "recall": 0.0, "f1": 0.0, "latency_ms": 200, "confidence": "low"},
    ]
    agg = aggregate_metrics(per_issue)
    assert agg["label_precision"] == 0.5
    assert agg["label_recall"] == 0.5
    assert agg["label_f1"] == 0.5
    assert agg["n_issues"] == 2
    assert agg["confidence_distribution"]["high"] == 1
    assert agg["confidence_distribution"]["low"] == 1
    assert agg["confidence_distribution"]["medium"] == 0


def test_aggregate_metrics_latency_stats():
    # 4 issues with latencies 100, 200, 300, 400
    per_issue = [
        {"precision": 1.0, "recall": 1.0, "f1": 1.0, "latency_ms": lat, "confidence": "high"}
        for lat in [100, 200, 300, 400]
    ]
    agg = aggregate_metrics(per_issue)
    assert agg["latency_avg_ms"] == 250
    # p50 = index 2 of sorted [100,200,300,400] → 300
    assert agg["latency_p50_ms"] == 300
    # p95 = index 3 of 4 items → 400
    assert agg["latency_p95_ms"] == 400


def test_aggregate_metrics_empty_returns_empty_dict():
    assert aggregate_metrics([]) == {}


def test_aggregate_metrics_missing_latency_skipped():
    per_issue = [
        {"precision": 1.0, "recall": 1.0, "f1": 1.0, "confidence": "high"},
    ]
    agg = aggregate_metrics(per_issue)
    assert "latency_avg_ms" not in agg
    assert agg["n_issues"] == 1


# ---------------------------------------------------------------------------
# format_report
# ---------------------------------------------------------------------------


def test_format_report_contains_repo_name():
    agg = aggregate_metrics([
        {"precision": 1.0, "recall": 1.0, "f1": 1.0, "latency_ms": 50, "confidence": "high"}
    ])
    per_issue = [
        {"github_number": 42, "actual_labels": ["bug"], "predicted_labels": ["bug"],
         "precision": 1.0, "recall": 1.0, "f1": 1.0, "latency_ms": 50}
    ]
    report = format_report("acme/myrepo", per_issue, agg)
    assert "acme/myrepo" in report


def test_format_report_contains_issue_row():
    agg = aggregate_metrics([
        {"precision": 0.5, "recall": 1.0, "f1": 0.67, "latency_ms": 100, "confidence": "medium"}
    ])
    per_issue = [
        {"github_number": 7, "actual_labels": ["bug"], "predicted_labels": ["bug", "perf"],
         "precision": 0.5, "recall": 1.0, "f1": 0.67, "latency_ms": 100}
    ]
    report = format_report("org/repo", per_issue, agg)
    assert "#7" in report
    assert "bug" in report


def test_format_report_is_nonempty_string():
    report = format_report("x/y", [], {})
    assert isinstance(report, str)
    assert len(report) > 0
