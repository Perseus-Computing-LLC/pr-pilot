"""
Agent 4: Verifier — runs tests and validates no regressions.

Two modes:
  - Sandboxed (default when available): Actually clones the PR branch,
    applies patches, and runs real tests in an isolated directory.
  - LLM-only (fallback): Uses Gemini to judge patches/tests without
    executing them.
"""
from __future__ import annotations

import json
import asyncio
from typing import Any

from src.agents.base import AgentResult, BaseAgent
from src.sandbox_verifier import SandboxVerifier, SandboxResult, cleanup_sandbox
from src.config import SANDBOX_ENABLED, SANDBOX_TIMEOUT_SECS

import structlog

logger = structlog.get_logger(__name__)


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
        """Verify fixes and tests.

        When SANDBOX_ENABLED is set and repo info is available, performs
        real sandboxed verification — cloning, patching, and running tests.
        Falls back to LLM-only verification otherwise.
        """
        patches = context.get("patches", [])
        test_files = context.get("test_files", [])
        reviewer_findings = context.get("findings", [])
        repo_name = context.get("repo_name", "")

        # Try sandboxed verification first
        sandbox_result = await self._run_sandbox_if_available(context, patches, test_files)
        if sandbox_result:
            return sandbox_result

        # Fall back to LLM-only verification
        return await self._run_llm_verification(patches, test_files, reviewer_findings, repo_name)

    async def _run_sandbox_if_available(
        self,
        context: dict[str, Any],
        patches: list,
        test_files: list,
    ) -> AgentResult | None:
        """Attempt sandboxed verification. Returns result if available, None to fall back."""
        if not SANDBOX_ENABLED:
            return None

        github_token = context.get("github_token", "")
        repo_url = context.get("repo_clone_url", "") or context.get("repo_url", "")
        branch_name = context.get("branch_name", "") or context.get("pr_branch", "")

        if not all([github_token, repo_url, branch_name]):
            logger.warning(
                "sandbox_skipped_missing_info",
                has_token=bool(github_token),
                has_url=bool(repo_url),
                has_branch=bool(branch_name),
            )
            return None

        if not patches and not test_files:
            return AgentResult(
                agent_name=self.name,
                status="pass",
                summary="Nothing to verify — no patches or tests generated.",
            )

        logger.info("sandbox_verification_start", repo=repo_url[:80], branch=branch_name)
        try:
            verifier = SandboxVerifier(
                github_token=github_token,
                timeout_secs=SANDBOX_TIMEOUT_SECS,
            )
            # Run in thread since clone/subprocess are synchronous
            result = await asyncio.to_thread(
                verifier.verify, repo_url, branch_name, patches, test_files
            )
            if not isinstance(result, SandboxResult):
                result = SandboxResult(status="error", summary=f"Unexpected result type: {type(result)}")

            # Clean up sandbox directory
            if result.sandbox_path:
                asyncio.get_event_loop().run_in_executor(
                    None, cleanup_sandbox, result.sandbox_path
                )

            metadata = {
                "checks": result.checks,
                "test_output": result.test_output[:2000],
                "test_exit_code": result.test_exit_code,
                "duration_seconds": result.duration_seconds,
                "sandbox_enabled": True,
            }

            return AgentResult(
                agent_name=self.name,
                status=result.status,
                summary=result.summary,
                metadata=metadata,
            )
        except Exception as exc:
            logger.error("sandbox_verification_error", error=str(exc))
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Sandbox verification failed: {exc}",
                metadata={"sandbox_enabled": True, "error": str(exc)},
            )

    async def _run_llm_verification(
        self,
        patches: list,
        test_files: list,
        reviewer_findings: list,
        repo_name: str,
    ) -> AgentResult:
        """LLM-only verification (original behavior)."""

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
