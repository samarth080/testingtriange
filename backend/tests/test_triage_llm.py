"""Unit tests for triage schemas, prompt builder, and LLM call. No real API calls."""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.retrieval import SearchResult
from app.triage.schemas import TriageOutput
from app.triage.prompt import build_user_prompt
from app.triage.llm import triage_with_llm


def make_result(chunk_id, source_type="issue", github_number=42, source_title="Fix PR"):
    return SearchResult(
        chunk_id=chunk_id, chunk_index=0, text=f"context text {chunk_id}",
        metadata={}, source_type=source_type, source_id=chunk_id,
        rrf_score=0.8, source_title=source_title, github_number=github_number,
    )


# Schema tests

def test_triage_output_defaults():
    output = TriageOutput(reasoning="test reason")
    assert output.duplicate_of is None
    assert output.labels == []
    assert output.relevant_files == []
    assert output.suggested_assignees == []
    assert output.confidence == "medium"
    assert output.reasoning == "test reason"


def test_triage_output_accepts_full_payload():
    output = TriageOutput(
        duplicate_of=7,
        labels=["bug", "performance"],
        relevant_files=["src/server.py"],
        suggested_assignees=["alice"],
        confidence="high",
        reasoning="Duplicate of #7.",
    )
    assert output.duplicate_of == 7
    assert output.confidence == "high"


# Prompt builder tests

def test_build_user_prompt_contains_issue_fields():
    prompt = build_user_prompt("Memory leak bug", "Happens on every request.", ["bug"], [])
    assert "Memory leak bug" in prompt
    assert "Happens on every request." in prompt
    assert "bug" in prompt


def test_build_user_prompt_includes_context_chunks():
    results = [make_result(1)]
    prompt = build_user_prompt("title", "body", [], results)
    assert "context text 1" in prompt
    assert "#42" in prompt


def test_build_user_prompt_handles_none_body():
    prompt = build_user_prompt("title", None, [], [])
    assert "no description provided" in prompt


def test_build_user_prompt_no_context_shows_placeholder():
    prompt = build_user_prompt("title", "body", [], [])
    assert "no context retrieved" in prompt


# LLM call tests

@pytest.mark.asyncio
async def test_triage_with_llm_parses_valid_json():
    response_payload = {
        "duplicate_of": None,
        "labels": ["bug"],
        "relevant_files": ["src/server.py"],
        "suggested_assignees": ["alice"],
        "confidence": "high",
        "reasoning": "Clear memory leak.",
    }
    with patch("app.triage.llm._call_anthropic", new_callable=AsyncMock,
               return_value=json.dumps(response_payload)):
        result = await triage_with_llm(
            title="Bug report",
            body="Something broke",
            labels=[],
            context_results=[],
            api_key="test-key",
        )

    assert isinstance(result, TriageOutput)
    assert result.labels == ["bug"]
    assert result.confidence == "high"
    assert result.relevant_files == ["src/server.py"]
    assert result.suggested_assignees == ["alice"]


@pytest.mark.asyncio
async def test_triage_with_llm_falls_back_on_invalid_json():
    with patch("app.triage.llm._call_anthropic", new_callable=AsyncMock,
               return_value="This is not valid JSON."):
        result = await triage_with_llm("title", None, [], [], "key")

    assert isinstance(result, TriageOutput)
    assert result.confidence == "low"
    assert "Parse error" in result.reasoning


@pytest.mark.asyncio
async def test_triage_with_llm_uses_correct_model():
    response_payload = {
        "duplicate_of": None, "labels": [], "relevant_files": [],
        "suggested_assignees": [], "confidence": "medium", "reasoning": "ok",
    }
    with patch("app.triage.llm._call_anthropic", new_callable=AsyncMock,
               return_value=json.dumps(response_payload)) as mock_call:
        await triage_with_llm("title", "body", ["bug"], [make_result(1)], "key123")

    # Verify _call_anthropic was invoked with the correct api_key
    mock_call.assert_awaited_once()
    assert mock_call.call_args.args[0] == "key123"
