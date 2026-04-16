"""Unit tests for the triage comment formatter. Pure string logic — no mocks needed."""
import pytest
from app.triage.formatter import format_triage_comment
from app.triage.schemas import TriageOutput


def full_output():
    return TriageOutput(
        duplicate_of=7,
        labels=["bug", "performance"],
        relevant_files=["src/server.py", "src/cache.py"],
        suggested_assignees=["alice", "bob"],
        confidence="high",
        reasoning="This is a clear regression introduced in #45 that affects the cache layer.",
    )


def minimal_output():
    return TriageOutput(
        duplicate_of=None,
        labels=[],
        relevant_files=[],
        suggested_assignees=[],
        confidence="low",
        reasoning="Insufficient context to triage confidently.",
    )


def test_comment_contains_issue_number():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "#42" in comment


def test_comment_contains_confidence():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "high" in comment.lower()


def test_comment_shows_duplicate_link():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "#7" in comment


def test_comment_shows_labels():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "bug" in comment
    assert "performance" in comment


def test_comment_shows_relevant_files():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "src/server.py" in comment
    assert "src/cache.py" in comment


def test_comment_shows_assignees():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "@alice" in comment
    assert "@bob" in comment


def test_comment_shows_reasoning():
    comment = format_triage_comment(full_output(), issue_number=42)
    assert "regression" in comment


def test_comment_minimal_output_no_duplicate_section():
    comment = format_triage_comment(minimal_output(), issue_number=1)
    assert "Possible duplicate" not in comment


def test_comment_minimal_output_no_labels_shows_none():
    comment = format_triage_comment(minimal_output(), issue_number=1)
    assert "none" in comment.lower() or "no label" in comment.lower() or "—" in comment


def test_comment_is_nonempty_string():
    comment = format_triage_comment(minimal_output(), issue_number=1)
    assert isinstance(comment, str)
    assert len(comment) > 50
