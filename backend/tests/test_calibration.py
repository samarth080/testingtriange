"""
Tests for the confidence threshold filter used in triage_tasks.

_meets_confidence_threshold(output_conf, min_conf) -> bool
  Returns True if the output confidence is >= the minimum required.
  Ranking: low < medium < high
"""
import pytest
from app.workers.triage_tasks import _meets_confidence_threshold


def test_high_meets_high():
    assert _meets_confidence_threshold("high", "high") is True


def test_medium_does_not_meet_high():
    assert _meets_confidence_threshold("medium", "high") is False


def test_low_does_not_meet_medium():
    assert _meets_confidence_threshold("low", "medium") is False


def test_high_meets_low():
    assert _meets_confidence_threshold("high", "low") is True


def test_medium_meets_medium():
    assert _meets_confidence_threshold("medium", "medium") is True


def test_low_meets_low():
    assert _meets_confidence_threshold("low", "low") is True
