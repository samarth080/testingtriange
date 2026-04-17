"""Call an LLM for issue triage and parse structured JSON output.

Provider priority:
  1. Anthropic Claude (if anthropic_api_key is set)
  2. Groq (if groq_api_key is set) — free tier, OpenAI-compatible
  3. Google Gemini via REST API (if gemini_api_key is set)
"""
import json
import logging

from app.retrieval import SearchResult
from app.triage.prompt import SYSTEM_PROMPT, build_user_prompt
from app.triage.schemas import TriageOutput

logger = logging.getLogger(__name__)

_MAX_TOKENS = 1024


async def triage_with_llm(
    title: str,
    body: str | None,
    labels: list[str],
    context_results: list[SearchResult],
    api_key: str,
    gemini_api_key: str = "",
    groq_api_key: str = "",
) -> TriageOutput:
    """
    Call an LLM with the new issue and retrieved context.

    Provider priority: Anthropic → Groq → Gemini.
    Falls back to a minimal low-confidence output on parse failure.
    """
    user_prompt = build_user_prompt(title, body, labels, context_results)

    if api_key:
        raw_text = await _call_anthropic(api_key, user_prompt)
    elif groq_api_key:
        raw_text = await _call_groq(groq_api_key, user_prompt)
    elif gemini_api_key:
        raw_text = await _call_gemini(gemini_api_key, user_prompt)
    else:
        logger.error("No LLM API key configured — returning low-confidence output")
        return TriageOutput(confidence="low", reasoning="No LLM API key configured.")

    # Strip markdown code fences that models sometimes include despite instructions
    raw_text = raw_text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    logger.debug("LLM triage raw response: %s", raw_text)

    try:
        data = json.loads(raw_text)
        return TriageOutput(**data)
    except Exception as exc:
        logger.error("Failed to parse LLM triage output: %s — raw: %s", exc, raw_text[:300])
        return TriageOutput(
            confidence="low",
            reasoning=f"Parse error — raw LLM response: {raw_text[:200]}",
        )


async def _call_anthropic(api_key: str, user_prompt: str) -> str:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    message = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    return message.content[0].text.strip()


async def _call_groq(api_key: str, user_prompt: str) -> str:
    from openai import AsyncOpenAI
    client = AsyncOpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
    )
    response = await client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        max_tokens=_MAX_TOKENS,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content.strip()


async def _call_gemini(api_key: str, user_prompt: str) -> str:
    import httpx
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models"
        f"/gemini-2.0-flash:generateContent?key={api_key}"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {"maxOutputTokens": _MAX_TOKENS},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
