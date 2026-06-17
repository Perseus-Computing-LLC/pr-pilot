"""
Shared review-posting logic used by both the CLI (GitHub Actions) and
the webhook (Cloud Run) entry points. Extracting this into one module
ensures fixes (safety gates, event mapping, fallback behaviour) apply
to both paths.
"""

from __future__ import annotations

from typing import Any

import structlog

from src.config import VERIFIED_AUTO_APPROVE

logger = structlog.get_logger(__name__)

# ── public helpers ────────────────────────────────────────────────────

def build_review_body(results: dict[str, Any]) -> str:
    """Build a clean PR review body from agent chain results."""
    reviewer = results.get("reviewer", {})
    fixer = results.get("fixer", {})
    tester = results.get("tester", {})
    verifier = results.get("verifier", {})
    decision = results.get("decision", "unknown")

    parts: list[str] = [
        "## 🤖 PR Pilot Review",
        "",
        "### 🔍 Reviewer (Agent 1)",
        reviewer.get("summary", "No findings."),
        "",
    ]

    findings = reviewer.get("findings", [])
    if findings:
        parts.append("### 📋 Issues Found")
        parts.append("")
        for f in findings:
            sev = f.get("severity", "?").upper()
            cat = f.get("category", "?")
            desc = f.get("description", "Issue")
            file_path = f.get("file", "?")
            line = f.get("line", "")
            loc = f"`{file_path}" + (f":{line}`" if line else "`")
            parts.append(f"- **[{sev}]** {cat} — {desc} ({loc})")

    parts.extend([
        "",
        "### 🔧 Fixer (Agent 2)",
        fixer.get("summary", "No fixes generated."),
        "",
        "### 🧪 Tester (Agent 3)",
        tester.get("summary", "No tests generated."),
        "",
        "### ✅ Verifier (Agent 4)",
        verifier.get("summary", "Verification skipped."),
        "",
    ])

    if decision == "auto_approve":
        parts.append("### 🚀 Decision: AUTO APPROVE")
        parts.append("All checks passed. This PR is safe to merge.")
    elif decision == "request_changes":
        parts.append("### ⚠️ Decision: REQUEST CHANGES")
        parts.append("Issues found. Please review the findings above and apply suggested fixes.")
    else:
        parts.append("### 👤 Decision: ESCALATE TO HUMAN")
        parts.append("This PR requires human review — too complex or risky for autonomous handling.")

    # Aggregate pipeline duration from actual agent results
    total_duration = sum(
        results.get(name, {}).get("duration_seconds", 0)
        for name in ("reviewer", "fixer", "tester", "verifier", "escalator")
    )

    parts.extend([
        "",
        f"**Pipeline duration:** ~{total_duration:.1f}s",
        "",
        "---",
        "*Review by [PR Pilot](https://github.com/Perseus-Computing-LLC/pr-pilot) — AI-native code quality service*",
    ])

    return "\n".join(parts)


def decision_to_github_event(decision: str) -> str:
    """Map an agent-chain decision to a GitHub review event (raw, no safety gate).

    Callers must apply the safety gate separately via :func:`apply_safety_gate`.
    """
    event_map = {
        "auto_approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
        "escalate_to_human": "COMMENT",
    }
    return event_map.get(decision, "COMMENT")


def apply_safety_gate(event: str) -> str:
    """Downgrade APPROVE to COMMENT unless verified auto-approve is enabled.

    The Verifier does not yet apply patches, write tests, or run project
    commands in a sandbox, so an LLM-only ``auto_approve`` must not become
    a binding GitHub APPROVE. This gate downgrades to COMMENT unless an
    operator has explicitly enabled VERIFIED_AUTO_APPROVE.
    """
    if event == "APPROVE" and not VERIFIED_AUTO_APPROVE:
        logger.warning(
            "auto_approve_downgraded",
            reason="no_verified_evidence",
        )
        return "COMMENT"
    return event


def build_review_body_with_safety_note(
    results: dict[str, Any], *, original_event: str
) -> str:
    """Return the review body, prepending a safety note when a downgrade occurred."""
    if original_event == "APPROVE" and not VERIFIED_AUTO_APPROVE:
        return (
            "> Note: PR Pilot suggested approval, but automated approval is "
            "disabled until changes are verified in a sandbox. Posting as a "
            "comment for human review.\n\n"
        ) + build_review_body(results)
    return build_review_body(results)
