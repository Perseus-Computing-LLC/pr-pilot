"""Agent 4: Verifier — runs tests and validates no regressions."""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import AgentResult, BaseAgent


VERIFIER_SYSTEM_PROMPT = """You are the Verifier agent for PR Pilot — an AI-native code quality service.

Your job: confirm that all generated fixes and tests are valid.
Check for:
1. Compilation/syntax errors in generated code
2. Test failures
3. New linting violations
4. Regression risks (does the fix break existing functionality?)

Output structured JSON:
- status: "pass" (all checks passed) or "fail" (issues found) or "inconclusive" (can't verify)
- summary: what was verified
- checks: list of {check_name, passed, detail}
"""

VERIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail", "inconclusive"]},
        "summary": {"type": "string"},
        "checks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "check_name": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "detail": {"type": "string"},
                },
                "required": ["check_name", "passed", "detail"],
            },
        },
    },
    "required": ["status", "summary", "checks"],
}


class VerifierAgent(BaseAgent):
    """Agent 4: Validates fixes and tests, confirms no regressions."""

    name = "verifier"

    def _build_system_prompt(self) -> str:
        return VERIFIER_SYSTEM_PROMPT

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Verify fixes and tests."""
        patches = context.get("patches", [])
        test_files = context.get("test_files", [])
        reviewer_findings = context.get("findings", [])
        repo_name = context.get("repo_name", "")

        if not patches and not test_files:
            return AgentResult(
                agent_name=self.name,
                status="pass",
                summary="Nothing to verify — no patches or tests generated.",
            )

        # Limit serialized patch/test size to avoid sending corrupted JSON to Gemini.
        # Truncate the lists before serialization so the JSON structure stays valid.
        MAX_VERIFIER_ITEMS = 20
        serialized_patches = json.dumps(patches[:MAX_VERIFIER_ITEMS], indent=2) if patches else "None"
        serialized_tests = json.dumps(test_files[:MAX_VERIFIER_ITEMS], indent=2) if test_files else "None"

        prompt = f"""Verify these generated patches and tests for correctness.

REPOSITORY: {repo_name}

ORIGINAL FINDINGS (what was fixed):
{json.dumps(reviewer_findings[:10], indent=2) if reviewer_findings else 'None'}

GENERATED PATCHES:
```json
{serialized_patches}
```

GENERATED TESTS:
```json
{serialized_tests}
```

Check each patch for:
1. Syntax correctness
2. Does it actually fix the reported issue?
3. Does it introduce new bugs or side effects?
4. Are the tests correct and relevant?

Report your verification results."""

        try:
            response = await self._call_gemini(prompt, VERIFIER_SCHEMA)
            result = json.loads(response)
        except Exception as exc:
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Verifier failed: {exc}",
                metadata={"error": str(exc)},
            )

        return AgentResult(
            agent_name=self.name,
            status=result.get("status", "fail"),
            summary=result.get("summary", ""),
            metadata={
                "checks": result.get("checks", []),
                "patch_count": len(patches),
                "test_count": len(test_files),
            },
        )
