"""Agent 1: Reviewer — analyzes PR diff against project rules."""

from __future__ import annotations

import json
from typing import Any

from src.agents.base import AgentResult, BaseAgent


REVIEWER_SYSTEM_PROMPT = """You are an expert code reviewer for PR Pilot — an AI-native code quality service.

Your job: analyze pull request changes against best practices and project rules.
You review code for: security vulnerabilities, performance regressions, style violations,
missing tests, error handling gaps, and potential bugs.

Output a structured JSON review with these fields:
- status: "pass" (no issues) or "fail" (issues found) or "escalate" (needs human)
- summary: 1-3 sentence high-level summary
- findings: list of {severity, category, file, line, description, suggestion}
  severity: "critical" | "high" | "medium" | "low"
  category: "security" | "performance" | "style" | "testing" | "error_handling" | "bug"
- metadata: {files_changed, lines_added, lines_removed}

Be thorough but practical. Flag real issues, not nitpicks.
If the change is trivial (docs, config, comments), return quick approval.
"""

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["pass", "fail", "escalate"]},
        "summary": {"type": "string"},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "category": {
                        "type": "string",
                        "enum": [
                            "security",
                            "performance",
                            "style",
                            "testing",
                            "error_handling",
                            "bug",
                        ],
                    },
                    "file": {"type": "string"},
                    "line": {"type": "integer"},
                    "description": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "category", "file", "description", "suggestion"],
            },
        },
        "metadata": {
            "type": "object",
            "properties": {
                "files_changed": {"type": "integer"},
                "lines_added": {"type": "integer"},
                "lines_removed": {"type": "integer"},
            },
        },
    },
    "required": ["status", "summary", "findings"],
}


class ReviewerAgent(BaseAgent):
    """Agent 1: Analyzes PR diff for bugs, security, performance, and style issues."""

    name = "reviewer"

    def _build_system_prompt(self) -> str:
        return REVIEWER_SYSTEM_PROMPT

    async def execute(self, context: dict[str, Any]) -> AgentResult:
        """Review the PR diff and return structured findings."""
        diff_text = context.get("diff", "")
        pr_title = context.get("pr_title", "")
        pr_description = context.get("pr_description", "")
        repo_name = context.get("repo_name", "")
        project_rules = context.get("project_rules", "")

        # Truncate massive diffs
        max_chars = 100_000
        if len(diff_text) > max_chars:
            diff_text = diff_text[:max_chars] + f"\n\n... (truncated, original {len(diff_text)} chars)"

        prompt = f"""Review this pull request:

REPOSITORY: {repo_name}
PR TITLE: {pr_title}
PR DESCRIPTION: {pr_description}

PROJECT RULES:
{project_rules or "Standard best practices apply — security, performance, testing, error handling, style."}

DIFF:
```diff
{diff_text}
```

Output your review as structured JSON."""
        try:
            response = await self._call_gemini(prompt, REVIEW_SCHEMA)
            review = json.loads(response)
        except (json.JSONDecodeError, RuntimeError) as exc:
            metadata: dict[str, Any] = {"error": str(exc)}
            if "response" in locals():
                metadata["raw_response"] = str(response)
            return AgentResult(
                agent_name=self.name,
                status="error",
                summary=f"Reviewer failed to produce valid review: {exc}",
                metadata=metadata,
            )

        return AgentResult(
            agent_name=self.name,
            status=review.get("status", "fail"),
            summary=review.get("summary", ""),
            findings=review.get("findings", []),
            metadata=review.get("metadata", {}),
        )
