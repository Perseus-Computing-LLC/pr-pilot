"""Agent 5: Escalator — decides what needs human attention vs. can be auto-approved."""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import AgentResult, BaseAgent


ESCALATOR_SYSTEM_PROMPT = """You are the Escalator agent for PR Pilot — an AI-native code quality service.

Your job: make the final decision on every pull request. You review all agent outputs
and decide one of three actions:

1. **auto_approve** — The PR is safe to merge. All issues are resolved or trivial.
2. **request_changes** — Issues found. Post review comments with fixes attached.
3. **escalate_to_human** — This PR needs a human's judgment. Too complex, too risky,
   or outside the agent chain's capability.

Decision rules:
- Docs/config/test-only changes → auto_approve (after verification)
- Critical/high severity security or bug findings → escalate_to_human
- All issues fixed and verified → auto_approve
- Ambiguous, complex, or high-risk changes → escalate_to_human
- Standard fixes with passing verification → auto_approve with review comment

Your output decides what the GitHub PR receives: an approval, a review with comments,
or an @mention for human review.
"""

ESCALATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {
            "type": "string",
            "enum": ["auto_approve", "request_changes", "escalate_to_human"],
        },
        "confidence": {"type": "number"},
        "reasoning": {"type": "string"},
        "review_body": {"type": "string"},
        "review_comments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "line": {"type": "integer"},
                    "body": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
            },
        },
    },
    "required": ["decision", "confidence", "reasoning", "review_body"],
}


class EscalatorAgent(BaseAgent):
    """Agent 5: Final decision maker — auto-approve, request changes, or escalate."""

    name = "escalator"

    def _build_system_prompt(self) -> str:
        return ESCALATOR_SYSTEM_PROMPT

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Make the final decision on this PR."""
        reviewer = context.get("reviewer_result", {})
        fixer = context.get("fixer_result", {})
        tester = context.get("tester_result", {})
        verifier = context.get("verifier_result", {})

        prompt = f"""Make the final decision on this pull request.

AGENT CHAIN RESULTS:

REVIEWER (Agent 1): {json.dumps(reviewer, indent=2, default=str)}
FIXER (Agent 2): {json.dumps(fixer, indent=2, default=str)}
TESTER (Agent 3): {json.dumps(tester, indent=2, default=str)}
VERIFIER (Agent 4): {json.dumps(verifier, indent=2, default=str)}

Based on these results, decide:
- auto_approve: PR is safe to merge
- request_changes: Issues found that need fixing
- escalate_to_human: Too complex/risky for autonomous handling

Generate the review body and any inline comments."""

        try:
            response = await self._call_gemini(prompt, ESCALATOR_SCHEMA)
            result = json.loads(response)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Escalator failed: {exc}",
                metadata={"error": str(exc), "decision_fallback": "escalate_to_human"},
            )

        confidence = result.get("confidence", 0)

        return AgentResult(
            agent_name=self.name,
            status=(
                "approved"
                if result.get("decision") == "auto_approve"
                else "changes_requested"
                if result.get("decision") == "request_changes"
                else "escalated"
            ),
            summary=f"Decision: {result.get('decision')} (confidence: {max(min(confidence, 1.0), 0.0):.0%})",
            findings=[
                {
                    "decision": result.get("decision"),
                    "confidence": confidence,
                    "reasoning": result.get("reasoning"),
                    "review_body": result.get("review_body"),
                    "review_comments": result.get("review_comments", []),
                }
            ],
            metadata={
                "decision": result.get("decision"),
                "confidence": confidence,
            },
        )
