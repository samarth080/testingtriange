"""Call Claude Sonnet for issue triage and parse structured JSON output."""
import json
import logging

import anthropic

from app.retrieval import SearchResult
from app.triage.prompt import SYSTEM_PROMPT, build_user_prompt
from app.triage.schemas import TriageOutput

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-6"
_MAX_TOKENS = 1024


async def triage_with_llm(
    title: str,
    body: str | None,
    labels: list[str],
    context_results: list[SearchResult],
    api_key: str,
) -> TriageOutput:
    """
    Call Claude Sonnet with the new issue and retrieved context.

    Parses the response as JSON and validates against TriageOutput.
    Falls back to a minimal low-confidence output on parse failure.
    """
    user_prompt = build_user_prompt(title, body, labels, context_results)
    client = anthropic.AsyncAnthropic(api_key=api_key)

    message = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw_text = message.content[0].text.strip()
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
