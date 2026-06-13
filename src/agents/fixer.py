"""Agent 2: Fixer — generates code patches for issues found by the Reviewer."""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import AgentResult, BaseAgent


FIXER_SYSTEM_PROMPT = """You are the Fixer agent for PR Pilot — an AI-native code quality service.

Your job: generate minimal, correct code patches for issues identified during code review.
For each finding, produce a patch that fixes the issue without introducing new problems.

Rules:
1. Follow the project's existing style and conventions
2. Make the smallest possible change — don't refactor unrelated code
3. Include context: which file, which lines, what to change
4. If a fix is too complex or risky, flag it as "escalate" instead of guessing
5. Never introduce new dependencies without clear justification

Output a structured JSON with:
- status: "pass" (all fixes generated) or "partial" (some escalated) or "fail" (no fixes possible)
- summary: what was fixed and what was escalated
- patches: list of {file, type: "replace"|"insert"|"delete", old_snippet, new_snippet, line_start, line_end, reason}
"""

FIXER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "partial", "fail"]},
        "summary": {"type": "string"},
        "patches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "file": {"type": "string"},
                    "type": {"type": "string", "enum": ["replace", "insert", "delete"]},
                    "old_snippet": {"type": "string"},
                    "new_snippet": {"type": "string"},
                    "line_start": {"type": "integer"},
                    "line_end": {"type": "integer"},
                    "reason": {"type": "string"},
                    "finding_ref": {"type": "string"},
                },
                "required": ["file", "type", "old_snippet", "new_snippet", "reason"],
            },
        },
        "escalated": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "finding_ref": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        },
    },
    "required": ["status", "summary", "patches"],
}


class FixerAgent(BaseAgent):
    """Agent 2: Generates code patches for issues identified by the Reviewer."""

    name = "fixer"

    def _build_system_prompt(self) -> str:
        return FIXER_SYSTEM_PROMPT

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Generate patches for review findings."""
        findings = context.get("findings", [])
        repo_name = context.get("repo_name", "")
        diff_text = context.get("diff", "")

        if not findings:
            return AgentResult(
                agent_name=self.name,
                status="pass",
                summary="No findings to fix — nothing to do.",
            )

        # Fix all findings. The Reviewer's status of "escalate" on individual
        # findings means they were too complex; the Fixer still attempts them
        # but may add them to the "escalated" list if the fix is too risky.
        fixable = findings
        escalated_by_reviewer = [f for f in findings if f.get("status") == "escalate"]

        if not fixable:
            return AgentResult(
                agent_name=self.name,
                status="partial",
                summary=f"All {len(findings)} findings were escalated by the reviewer.",
                metadata={"escalated_count": len(findings)},
            )

        findings_json = json.dumps(fixable, indent=2)

        # Truncate diff for context
        max_chars = 80_000
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars] + "\n... (truncated)"

        prompt = f"""Generate fixes for these code review findings.

REPOSITORY: {repo_name}

FINDINGS TO FIX:
```json
{findings_json}
```

ORIGINAL DIFF (for context):
```diff
{diff_text}
```

For each finding, generate the minimal code change to fix it.
If a fix is too complex or risky, add it to "escalated" with a reason."""

        try:
            response = await self._call_gemini(prompt, FIXER_SCHEMA)
            result = json.loads(response)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Fixer failed: {exc}",
                metadata={"error": str(exc)},
            )

        return AgentResult(
            agent_name=self.name,
            status=result.get("status", "fail"),
            summary=result.get("summary", ""),
            patches=result.get("patches", []),
            metadata={
                "fixable_count": len(fixable),
                "escalated_by_reviewer": len(escalated_by_reviewer),
                "escalated_by_fixer": len(result.get("escalated", [])),
            },
        )
