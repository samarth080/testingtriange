"""System prompt and user prompt builder for LLM triage."""
from app.retrieval import SearchResult


SYSTEM_PROMPT = """\
You are TriageCopilot, an expert GitHub issue triage assistant.
Given a new issue and relevant context retrieved from the repository history,
produce a structured triage decision as JSON.

Return ONLY valid JSON matching this schema (no markdown fences, no extra text):
{
  "duplicate_of": <int | null>,
  "labels": [<string>, ...],
  "relevant_files": [<string>, ...],
  "suggested_assignees": [<string>, ...],
  "confidence": "low" | "medium" | "high",
  "reasoning": "<string>"
}

Rules:
- duplicate_of: the github_number of an existing issue if this is a duplicate, else null
- labels: only suggest labels that appear in the retrieved context; max 5
- relevant_files: file paths that likely need changes to fix this issue; max 10
- suggested_assignees: github logins of people who worked on relevant files or issues; leave empty [] if no real logins appear in the retrieved context — never invent or guess usernames
- confidence: your overall certainty about this triage decision
- reasoning: 2-4 sentences explaining the key evidence and your decision
"""


def build_user_prompt(
    title: str,
    body: str | None,
    labels: list[str],
    context_results: list[SearchResult],
) -> str:
    """Build the user-turn prompt from issue fields and retrieved context."""
    body_text = body or "(no description provided)"
    label_text = ", ".join(labels) if labels else "(none)"

    context_parts = []
    for i, r in enumerate(context_results, start=1):
        source_label = f"[{r.source_type}] {r.source_title}"
        if r.github_number:
            source_label += f" (#{r.github_number})"
        context_parts.append(f"--- Context {i}: {source_label} ---\n{r.text}")

    context_block = "\n\n".join(context_parts) if context_parts else "(no context retrieved)"

    return f"""\
## New Issue

**Title:** {title}
**Labels:** {label_text}
**Body:**
{body_text}

## Retrieved Context

{context_block}

Triage this issue now. Return only the JSON object.
"""
