"""
Pure metric computation for the TriageCopilot eval harness.

No I/O, no database, no backend imports — only Python stdlib.
All functions are deterministic and side-effect-free.
"""
from __future__ import annotations

import statistics


def normalize_label(s: str) -> str:
    """Normalize a label string for comparison: lowercase and strip whitespace."""
    return s.lower().strip()


def label_metrics(predicted: list[str], actual: list[str]) -> dict[str, float]:
    """
    Compute precision, recall, and F1 for one issue's label prediction.

    Labels are normalized (lowercase + strip) before comparison so that
    'Bug' and 'bug' are treated as the same label.

    Args:
        predicted: Labels suggested by the triage pipeline.
        actual:    Ground-truth labels from the real issue.

    Returns:
        Dict with keys "precision", "recall", "f1" — all floats in [0, 1].
    """
    if not actual:
        return {"precision": 0.0, "recall": 0.0, "f1": 0.0}

    pred_set = {normalize_label(s) for s in predicted}
    actual_set = {normalize_label(s) for s in actual}
    tp = len(pred_set & actual_set)

    precision = tp / len(pred_set) if pred_set else 0.0
    recall = tp / len(actual_set)
    denom = precision + recall
    f1 = (2 * precision * recall) / denom if denom > 0 else 0.0

    return {"precision": precision, "recall": recall, "f1": f1}


def aggregate_metrics(per_issue: list[dict]) -> dict:
    """
    Aggregate per-issue metric dicts into summary statistics.

    Each entry in `per_issue` must have: precision, recall, f1, confidence.
    latency_ms is optional; missing values are skipped from latency stats.

    Returns:
        Dict with label_precision, label_recall, label_f1, n_issues,
        confidence_distribution, and latency stats (if any latency data).
    """
    if not per_issue:
        return {}

    precisions = [r["precision"] for r in per_issue]
    recalls = [r["recall"] for r in per_issue]
    f1s = [r["f1"] for r in per_issue]

    confidence_counts: dict[str, int] = {"high": 0, "medium": 0, "low": 0}
    for r in per_issue:
        level = r.get("confidence", "low")
        confidence_counts[level] = confidence_counts.get(level, 0) + 1

    result: dict = {
        "label_precision": statistics.mean(precisions),
        "label_recall": statistics.mean(recalls),
        "label_f1": statistics.mean(f1s),
        "confidence_distribution": confidence_counts,
        "n_issues": len(per_issue),
    }

    latencies = [r["latency_ms"] for r in per_issue if r.get("latency_ms") is not None]
    if latencies:
        sorted_lat = sorted(latencies)
        n = len(sorted_lat)
        result["latency_avg_ms"] = int(statistics.mean(latencies))
        result["latency_p50_ms"] = sorted_lat[n // 2]
        result["latency_p95_ms"] = sorted_lat[int(n * 0.95)]

    return result


def format_report(repo: str, per_issue: list[dict], agg: dict) -> str:
    """
    Render eval results as a GitHub-flavoured markdown string.

    Args:
        repo:      Repository slug e.g. "owner/name".
        per_issue: List of per-issue result dicts (from eval_issue()).
        agg:       Aggregate metrics dict (from aggregate_metrics()).

    Returns:
        Markdown string suitable for writing to a .md file.
    """
    lines = [
        f"# TriageCopilot Eval — {repo}",
        "",
        f"**Issues evaluated:** {agg.get('n_issues', 0)}",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Label Precision | {agg.get('label_precision', 0.0):.3f} |",
        f"| Label Recall | {agg.get('label_recall', 0.0):.3f} |",
        f"| Label F1 | {agg.get('label_f1', 0.0):.3f} |",
        f"| Latency avg | {agg.get('latency_avg_ms', '—')}ms |",
        f"| Latency p50 | {agg.get('latency_p50_ms', '—')}ms |",
        f"| Latency p95 | {agg.get('latency_p95_ms', '—')}ms |",
        "",
        "## Confidence Distribution",
        "",
        "| Confidence | Count |",
        "|---|---|",
    ]

    for level, count in agg.get("confidence_distribution", {}).items():
        lines.append(f"| {level} | {count} |")

    lines += [
        "",
        "## Per-Issue Results",
        "",
        "| Issue # | Actual Labels | Predicted Labels | P | R | F1 | Latency |",
        "|---|---|---|---|---|---|---|",
    ]

    for r in per_issue:
        actual_str = ", ".join(r.get("actual_labels", [])) or "—"
        predicted_str = ", ".join(r.get("predicted_labels", [])) or "—"
        lat = r.get("latency_ms")
        lat_str = f"{lat}ms" if lat is not None else "—"
        lines.append(
            f"| #{r['github_number']} | {actual_str} | {predicted_str} "
            f"| {r['precision']:.2f} | {r['recall']:.2f} | {r['f1']:.2f} | {lat_str} |"
        )

    return "\n".join(lines) + "\n"
