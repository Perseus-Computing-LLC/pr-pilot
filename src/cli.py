"""PR Pilot CLI — runs the agent chain from GitHub Actions.
Reads PR context from environment/GitHub API, executes the 5-agent pipeline,
and posts results as a PR review.
"""

import asyncio
import os
import sys
from pathlib import Path

# Add src to path for direct execution
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx
import structlog

from src.orchestration.engine import AgentChain
from src.config import GEMINI_API_KEY


logger = structlog.get_logger("pr-pilot-cli")

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")
GITHUB_EVENT_PATH = os.getenv("GITHUB_EVENT_PATH", "")
GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")


def get_pr_context() -> dict:
    """Extract PR context from GitHub Actions environment."""
    import json

    if not GITHUB_EVENT_PATH or not os.path.exists(GITHUB_EVENT_PATH):
        logger.error("no_event_path")
        sys.exit(1)

    with open(GITHUB_EVENT_PATH) as f:
        event = json.load(f)

    pr = event.get("pull_request", {})
    if not pr:
        logger.error("not_a_pr_event")
        sys.exit(1)

    return {
        "pr_number": pr.get("number"),
        "pr_title": pr.get("title", ""),
        "pr_description": pr.get("body", "") or "",
        "repo_name": GITHUB_REPOSITORY,
        "changed_files": [],  # Will be populated
        "project_files": "",  # Will be populated
        "project_rules": "",
        "diff_url": pr.get("diff_url", ""),
        "comments_url": pr.get("comments_url", ""),
        "review_comments_url": pr.get("review_comments_url", ""),
    }


async def fetch_diff(context: dict) -> str:
    """Fetch the PR diff from GitHub API."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3.diff",
        "User-Agent": "pr-pilot/0.1.0",
    }

    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    async with httpx.AsyncClient(follow_redirects=True) as client:
        resp = await client.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}",
            headers=headers,
        )
        resp.raise_for_status()
        return resp.text


async def fetch_changed_files(context: dict) -> list[str]:
    """Fetch list of changed files."""
    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "pr-pilot/0.1.0",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers=headers,
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return [f["filename"] for f in resp.json()]


async def post_review(
    context: dict,
    body: str,
    event: str = "COMMENT",
    comments: list[dict] | None = None,
) -> None:
    """Post a PR review using GitHub Actions token."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "pr-pilot/0.1.0",
    }

    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    payload = {
        "body": body,
        "event": event,
    }
    if comments:
        payload["comments"] = comments

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
            headers=headers,
            json=payload,
        )
        if resp.status_code >= 400:
            logger.error("review_post_failed", status=resp.status_code, body=resp.text[:500])
            # Fallback: post a comment
            comment_resp = await client.post(
                f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{pr_number}/comments",
                headers=headers,
                json={"body": body},
            )
            logger.info("comment_posted", status=comment_resp.status_code)
        else:
            logger.info("review_posted", pr=pr_number, event=event)


def build_review_body(results: dict) -> str:
    """Build a clean PR review body from agent results."""
    reviewer = results.get("reviewer", {})
    fixer = results.get("fixer", {})
    tester = results.get("tester", {})
    verifier = results.get("verifier", {})
    decision = results.get("decision", "unknown")

    body = [
        "## 🤖 PR Pilot Review",
        "",
        "### 🔍 Reviewer (Agent 1)",
        reviewer.get("summary", "No findings."),
        "",
    ]

    findings = reviewer.get("findings", [])
    if findings:
        body.append("### 📋 Issues Found")
        body.append("")
        for f in findings:
            sev = f.get("severity", "?").upper()
            cat = f.get("category", "?")
            desc = f.get("description", "Issue")
            file_path = f.get("file", "?")
            line = f.get("line", "")
            loc = f"`{file_path}" + (f":{line}`" if line else "`")
            body.append(f"- **[{sev}]** {cat} — {desc} ({loc})")

    body.extend([
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
        body.append("### 🚀 Decision: AUTO APPROVE")
        body.append("All checks passed. This PR is safe to merge.")
    elif decision == "request_changes":
        body.append("### ⚠️ Decision: REQUEST CHANGES")
        body.append("Issues found. Please review the findings above and apply suggested fixes.")
    else:
        body.append("### 👤 Decision: ESCALATE TO HUMAN")
        body.append("This PR requires human review — too complex or risky for autonomous handling.")

    body.extend([
        "",
        f"**Pipeline duration:** ~{results.get('reviewer', {}).get('duration_seconds', 0) + results.get('fixer', {}).get('duration_seconds', 0) + results.get('tester', {}).get('duration_seconds', 0) + results.get('verifier', {}).get('duration_seconds', 0) + results.get('escalator', {}).get('duration_seconds', 0):.1f}s",
        "",
        "---",
        "*Review by [PR Pilot](https://github.com/tcconnally/pr-pilot) — AI-native code quality service*",
    ])

    return "\n".join(body)


async def main():
    """Main entrypoint for GitHub Actions."""
    if not GEMINI_API_KEY:
        logger.error("no_gemini_key")
        print("::error::GEMINI_API_KEY not set. Add it as a repository secret.")
        sys.exit(1)

    if not GITHUB_TOKEN:
        logger.error("no_github_token")
        sys.exit(1)

    logger.info("pr_pilot_actions_starting", repo=GITHUB_REPOSITORY)

    # Get PR context
    context = get_pr_context()
    logger.info("pr_context", number=context["pr_number"], title=context["pr_title"])

    # Fetch diff and files
    try:
        diff_text = await fetch_diff(context)
        context["diff"] = diff_text
        logger.info("diff_fetched", size=len(diff_text))
    except Exception as e:
        logger.error("diff_fetch_failed", error=str(e))
        sys.exit(1)

    try:
        changed_files = await fetch_changed_files(context)
        context["changed_files"] = changed_files
        logger.info("files_fetched", count=len(changed_files))
    except Exception:
        context["changed_files"] = []

    # Run the agent chain
    logger.info("running_agent_chain")
    chain = AgentChain()
    results = await chain.run(context)

    # Build review body
    decision = results.get("decision", "escalate_to_human")
    review_body = build_review_body(results)

    # Map decision to GitHub review event
    event_map = {
        "auto_approve": "APPROVE",
        "request_changes": "REQUEST_CHANGES",
        "escalate_to_human": "COMMENT",
    }
    github_event = event_map.get(decision, "COMMENT")

    # Post review
    await post_review(context, review_body, github_event)

    logger.info("pr_pilot_complete", decision=decision, event=github_event)

    # Set output for workflow
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"decision={decision}\n")
            f.write(f"autonomous={str(results.get('autonomy', False)).lower()}\n")


if __name__ == "__main__":
    asyncio.run(main())
