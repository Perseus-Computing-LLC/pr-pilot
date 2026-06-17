"""Regression test: GitHubClient.get_pr_diff must be defined exactly once.

The original client.py shipped a dead duplicate `get_pr_diff` that referenced
undefined names (`_get_client`, `_MAX_RETRIES`, `_RETRYABLE_STATUSES`,
`_BASE_DELAY`). Because Python keeps the *last* definition, the broken
function never actually ran — but the duplicate made the file misleading
and would silently re-activate if anyone ever refactored/renamed the
working version.

See: https://github.com/Perseus-Computing-LLC/pr-pilot/issues/46
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import pytest

from src.github_app.client import GitHubClient


CLIENT_PY = Path(__file__).resolve().parent.parent / "src" / "github_app" / "client.py"


def _count_get_pr_diff_defs() -> int:
    """Count `def get_pr_diff` / `async def get_pr_diff` definitions in client.py."""
    source = CLIENT_PY.read_text()
    tree = ast.parse(source)
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "get_pr_diff":
            count += 1
    return count


class TestGetPrDiffUniqueness:
    """Regression for issue #46: dead duplicate get_pr_diff."""

    def test_get_pr_diff_defined_exactly_once(self) -> None:
        assert _count_get_pr_diff_defs() == 1, (
            "GitHubClient.get_pr_diff must be defined exactly once. "
            "Duplicate definitions are dead code that reference undefined names."
        )

    def test_get_pr_diff_signature(self) -> None:
        """The surviving definition must have the correct public signature."""
        sig = inspect.signature(GitHubClient.get_pr_diff)
        params = list(sig.parameters.keys())
        assert params == ["self", "owner", "repo", "pr_number"], (
            f"Unexpected signature: {params}"
        )

    @pytest.mark.asyncio
    async def test_get_pr_diff_uses_request_helper(self) -> None:
        """The working definition must call self._request, not an undefined _get_client."""
        source = CLIENT_PY.read_text()
        # Find the function body via AST
        tree = ast.parse(source)
        func = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_pr_diff"
        )
        body_src = ast.unparse(func)
        assert "self._request" in body_src, "get_pr_diff must route through self._request"
        assert "_get_client" not in body_src, (
            "get_pr_diff must not reference the undefined _get_client"
        )
        assert "_MAX_RETRIES" not in body_src, (
            "get_pr_diff must not reference the undefined _MAX_RETRIES"
        )
        assert "_BASE_DELAY" not in body_src, (
            "get_pr_diff must not reference the undefined _BASE_DELAY"
        )
