"""Render a TriageOutput as a GitHub-flavoured markdown comment."""
from app.triage.schemas import TriageOutput

_CONFIDENCE_EMOJI = {
    "high": "🟢",
    "medium": "🟡",
    "low": "🔴",
}


def format_triage_comment(output: TriageOutput, issue_number: int) -> str:
    """
    Format a TriageOutput as a GitHub markdown comment body.

    Args:
        output:       The structured triage decision from the LLM.
        issue_number: The GitHub issue number being triaged.

    Returns:
        A markdown string ready to POST to the GitHub Issues API.
    """
    emoji = _CONFIDENCE_EMOJI.get(output.confidence, "⚪")
    lines = [
        f"## 🤖 TriageCopilot — Issue #{issue_number}",
        "",
        f"**Confidence:** {emoji} {output.confidence}",
        "",
    ]

    if output.duplicate_of:
        lines += [
            f"⚠️ **Possible duplicate of #{output.duplicate_of}**",
            "",
        ]

    # Labels
    if output.labels:
        label_text = " ".join(f"`{lbl}`" for lbl in output.labels)
    else:
        label_text = "—"
    lines += [f"**Suggested labels:** {label_text}", ""]

    # Relevant files
    if output.relevant_files:
        lines.append("**Relevant files:**")
        for path in output.relevant_files:
            lines.append(f"- `{path}`")
        lines.append("")
    else:
        lines += ["**Relevant files:** —", ""]

    # Suggested assignees
    if output.suggested_assignees:
        assignee_text = " ".join(f"@{a}" for a in output.suggested_assignees)
        lines += [f"**Suggested assignees:** {assignee_text}", ""]

    # Reasoning
    lines += [
        "**Reasoning:**",
        output.reasoning,
        "",
        "---",
        "_Posted by [TriageCopilot](https://github.com/apps/triagecopilot). "
        "Review and adjust before applying._",
    ]

    return "\n".join(lines)
