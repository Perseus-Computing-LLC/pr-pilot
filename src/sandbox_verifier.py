"""
Sandboxed verification worker for PR Pilot.

Applies patches and runs real tests in an isolated directory,
producing evidence-backed pass/fail results instead of LLM-only judgment.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

# Test framework detection patterns: (name, detection_glob, test_command_template)
TEST_FRAMEWORKS = [
    ("pytest", ["*test*.py", "tests/", "test/"], ["pytest", "-x", "--tb=short"]),
    ("unittest", ["*test*.py", "tests/", "test/"], ["python", "-m", "unittest", "discover", "-v"]),
    ("jest", ["*.test.js", "*.test.ts", "__tests__/"], ["npx", "jest", "--passWithNoTests"]),
    ("cargo test", ["Cargo.toml"], ["cargo", "test"]),
    ("go test", ["*_test.go"], ["go", "test", "./..."]),
    ("npm test", ["package.json"], ["npm", "test"]),
    ("make test", ["Makefile"], ["make", "test"]),
]


@dataclass
class SandboxResult:
    """Result of a sandboxed verification run."""
    status: str  # "pass", "fail", "error"
    summary: str
    checks: list[dict] = field(default_factory=list)
    test_output: str = ""
    test_exit_code: int = 0
    duration_seconds: float = 0
    sandbox_path: str = ""


class SandboxVerifier:
    """Applies patches and runs tests in an isolated filesystem sandbox.

    The workflow:
    1. Clone the repo to a temp directory
    2. Checkout the PR branch
    3. Apply each generated patch
    4. Run the project's test suite
    5. Collect real stdout/stderr as evidence
    """

    def __init__(self, github_token: str, timeout_secs: int = 300):
        self.github_token = github_token
        self.timeout_secs = timeout_secs

    def verify(
        self,
        repo_url: str,
        branch_name: str,
        patches: list[dict],
        test_files: list[dict] | None = None,
    ) -> SandboxResult:
        """Run sandboxed verification on a PR.

        Args:
            repo_url: HTTPS clone URL (token embedded for auth).
            branch_name: The PR head branch to checkout.
            patches: List of patch dicts from the Fixer agent.
            test_files: Optional list of test file dicts from the Tester agent.

        Returns:
            SandboxResult with pass/fail status and real evidence.
        """
        start = time.monotonic()
        sandbox_dir = tempfile.mkdtemp(prefix="pr-pilot-sandbox-")
        checks = []

        try:
            # Step 1: Clone repo
            clone_check = self._clone_repo(repo_url, branch_name, sandbox_dir)
            checks.append(clone_check)
            if not clone_check["passed"]:
                return SandboxResult(
                    status="error",
                    summary=f"Failed to clone repository: {clone_check['detail']}",
                    checks=checks,
                    sandbox_path=sandbox_dir,
                    duration_seconds=time.monotonic() - start,
                )

            # Step 2: Apply fixer patches
            all_patches = patches[:]  # Fixer's patches
            if test_files:
                all_patches.extend(test_files)  # Tester's generated tests

            for i, patch in enumerate(all_patches):
                patch_check = self._apply_patch(sandbox_dir, patch, i)
                checks.append(patch_check)

            # Step 3: Detect and run test framework
            test_check = self._run_tests(sandbox_dir)
            checks.append(test_check)

            # Determine overall status
            all_passed = all(c["passed"] for c in checks)
            has_test_run = any(c["check_name"] == "test_run" for c in checks)

            if not has_test_run:
                status = "inconclusive"
                summary = "Patches applied successfully but no test framework detected."
            elif all_passed:
                status = "pass"
                summary = "All patches applied and tests passed."
            elif test_check.get("exit_code", 0) != 0:
                status = "fail"
                summary = f"Tests failed with exit code {test_check.get('exit_code')}."
            else:
                status = "fail"
                summary = "Some checks failed (see details)."

            return SandboxResult(
                status=status,
                summary=summary,
                checks=checks,
                test_output=test_check.get("detail", ""),
                test_exit_code=test_check.get("exit_code", 0),
                sandbox_path=sandbox_dir,
                duration_seconds=time.monotonic() - start,
            )

        except Exception as exc:
            logger.error("sandbox_error", error=str(exc))
            return SandboxResult(
                status="error",
                summary=f"Sandbox verification failed: {exc}",
                checks=checks,
                sandbox_path=sandbox_dir,
                duration_seconds=time.monotonic() - start,
            )

    def _clone_repo(self, repo_url: str, branch: str, sandbox_dir: str) -> dict:
        """Clone the repository and checkout the PR branch."""
        try:
            # Embed token in clone URL
            if "github.com" in repo_url and self.github_token:
                auth_url = repo_url.replace(
                    "https://github.com/",
                    f"https://x-access-token:{self.github_token}@github.com/",
                )
            else:
                auth_url = repo_url

            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", branch, auth_url, sandbox_dir],
                capture_output=True,
                text=True,
                timeout=120,
            )

            if result.returncode == 0:
                return {
                    "check_name": "clone_repo",
                    "passed": True,
                    "detail": f"Cloned {repo_url} (branch: {branch})",
                }

            # Try without branch (default branch) then checkout
            logger.warning("clone_branch_failed", stderr=result.stderr[:200])
            # Try default branch clone
            result2 = subprocess.run(
                ["git", "clone", "--depth", "1", auth_url, sandbox_dir],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result2.returncode != 0:
                return {
                    "check_name": "clone_repo",
                    "passed": False,
                    "detail": f"Clone failed: {result2.stderr[:300]}",
                }

            # Try to checkout the PR branch
            checkout = subprocess.run(
                ["git", "-C", sandbox_dir, "fetch", "--depth", "1", "origin", branch],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if checkout.returncode != 0:
                return {
                    "check_name": "clone_repo",
                    "passed": False,
                    "detail": f"Clone ok but branch {branch} not found: {checkout.stderr[:200]}",
                }

            subprocess.run(
                ["git", "-C", sandbox_dir, "checkout", "FETCH_HEAD"],
                capture_output=True,
                text=True,
                timeout=30,
            )

            return {
                "check_name": "clone_repo",
                "passed": True,
                "detail": f"Cloned repo with default branch, then checked out {branch}",
            }

        except subprocess.TimeoutExpired:
            return {
                "check_name": "clone_repo",
                "passed": False,
                "detail": "Clone timed out after 120s",
            }
        except Exception as exc:
            return {
                "check_name": "clone_repo",
                "passed": False,
                "detail": f"Clone error: {exc}",
            }

    def _apply_patch(self, sandbox_dir: str, patch: dict, index: int) -> dict:
        """Apply a single patch to the sandbox."""
        patch_content = patch.get("patch", patch.get("content", ""))
        file_path = patch.get("file", patch.get("path", ""))

        if not patch_content:
            return {
                "check_name": f"patch_{index}",
                "passed": True,
                "detail": f"Empty patch for {file_path or 'unknown'} — skipped",
            }

        try:
            target_file = os.path.join(sandbox_dir, file_path) if file_path else None
            if target_file and not os.path.exists(target_file):
                # If file doesn't exist, create it with the patch content
                # (the patch might create a new file)
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                Path(target_file).write_text(patch_content)
                return {
                    "check_name": f"patch_{index}",
                    "passed": True,
                    "detail": f"Created new file {file_path} ({len(patch_content)} bytes)",
                }

            # Apply as unified diff using patch command
            proc = subprocess.run(
                ["patch", "-p1", "-t", "-N"],
                input=patch_content,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=sandbox_dir,
            )

            if proc.returncode == 0:
                return {
                    "check_name": f"patch_{index}",
                    "passed": True,
                    "detail": f"Applied patch to {file_path or f'patch #{index}'} ({len(patch_content)} bytes)",
                }
            else:
                return {
                    "check_name": f"patch_{index}",
                    "passed": False,
                    "detail": f"Patch failed for {file_path or f'patch #{index}'}: {proc.stderr[:300]}",
                }

        except subprocess.TimeoutExpired:
            return {
                "check_name": f"patch_{index}",
                "passed": False,
                "detail": f"Patch application timed out for {file_path or f'patch #{index}'}",
            }
        except FileNotFoundError:
            # patch command not available — write the file content directly
            if target_file:
                try:
                    os.makedirs(os.path.dirname(target_file), exist_ok=True)
                    Path(target_file).write_text(patch_content)
                    return {
                        "check_name": f"patch_{index}",
                        "passed": True,
                        "detail": f"Wrote file {file_path} directly ({len(patch_content)} bytes) — patch cmd not available",
                    }
                except Exception as exc:
                    return {
                        "check_name": f"patch_{index}",
                        "passed": False,
                        "detail": f"Failed to write {file_path}: {exc}",
                    }
            return {
                "check_name": f"patch_{index}",
                "passed": False,
                "detail": f"patch command not available and no file path specified",
            }
        except Exception as exc:
            return {
                "check_name": f"patch_{index}",
                "passed": False,
                "detail": f"Patch error for {file_path or f'patch #{index}'}: {exc}",
            }

    def _detect_test_framework(self, sandbox_dir: str) -> tuple[str | None, list[str]]:
        """Detect which test framework to use based on project files."""
        sandbox = Path(sandbox_dir)
        for name, patterns, command in TEST_FRAMEWORKS:
            for pattern in patterns:
                if list(sandbox.glob(pattern)):
                    return name, command
        return None, []

    def _run_tests(self, sandbox_dir: str) -> dict:
        """Detect and run the project's test suite, collecting real output."""
        framework_name, command = self._detect_test_framework(sandbox_dir)

        if not framework_name:
            # Check for common package manager test commands as fallback
            sandbox = Path(sandbox_dir)
            if (sandbox / "package.json").exists():
                framework_name = "npm test"
                command = ["npm", "test"]
            elif (sandbox / "Makefile").exists():
                framework_name = "make test"
                command = ["make", "test"]
            else:
                return {
                    "check_name": "test_run",
                    "passed": True,
                    "detail": "No test framework detected — cannot run tests.",
                    "exit_code": -1,
                }

        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout_secs,
                cwd=sandbox_dir,
                env={**os.environ, "CI": "true"},
            )

            output = result.stdout + "\n" + result.stderr
            # Truncate output to avoid blowing up evidence
            if len(output) > 10_000:
                output = output[:5_000] + "\n... truncated ...\n" + output[-5_000:]

            passed = result.returncode == 0
            return {
                "check_name": "test_run",
                "passed": passed,
                "detail": output,
                "exit_code": result.returncode,
                "framework": framework_name,
            }

        except subprocess.TimeoutExpired:
            return {
                "check_name": "test_run",
                "passed": False,
                "detail": f"Tests timed out after {self.timeout_secs}s ({framework_name})",
                "exit_code": -1,
            }
        except Exception as exc:
            return {
                "check_name": "test_run",
                "passed": False,
                "detail": f"Test execution error ({framework_name}): {exc}",
                "exit_code": -1,
            }


def cleanup_sandbox(sandbox_path: str) -> None:
    """Remove the sandbox directory."""
    if sandbox_path and os.path.isdir(sandbox_path):
        try:
            shutil.rmtree(sandbox_path, ignore_errors=True)
        except Exception:
            pass
