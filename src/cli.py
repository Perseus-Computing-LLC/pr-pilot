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
from src.review_poster import (
    apply_safety_gate,
    build_review_body_with_safety_note,
    decision_to_github_event,
)


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


async def fetch_diff(context: dict, client: httpx.AsyncClient) -> str:
    """Fetch the PR diff from GitHub API."""
    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    resp = await client.get(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3.diff",
            "User-Agent": "pr-pilot/0.1.0",
        },
    )
    resp.raise_for_status()
    return resp.text


async def fetch_changed_files(context: dict, client: httpx.AsyncClient) -> list[str]:
    """Fetch list of changed files."""
    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    files: list[str] = []
    page = 1
    while True:
        resp = await client.get(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/files",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "pr-pilot/0.1.0",
            },
            params={"per_page": 100, "page": page},
        )
        resp.raise_for_status()
        batch = resp.json()
        files.extend(f["filename"] for f in batch)
        if len(batch) < 100:
            break
        page += 1
    return files


async def post_review(
    context: dict,
    body: str,
    event: str = "COMMENT",
    comments: list[dict] | None = None,
    client: httpx.AsyncClient | None = None,
) -> None:
    """Post a PR review using GitHub Actions token."""
    if client is None:
        client = httpx.AsyncClient()

    owner, repo = GITHUB_REPOSITORY.split("/")
    pr_number = context["pr_number"]

    payload = {
        "body": body,
        "event": event,
    }
    if comments:
        payload["comments"] = comments

    resp = await client.post(
        f"{GITHUB_API_URL}/repos/{owner}/{repo}/pulls/{pr_number}/reviews",
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "pr-pilot/0.1.0",
        },
        json=payload,
    )
    if resp.status_code >= 400:
        logger.error("review_post_failed", status=resp.status_code, body=resp.text[:500])
        # Fallback: post a comment
        comment_resp = await client.post(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/issues/{pr_number}/comments",
            headers={
                "Authorization": f"Bearer {GITHUB_TOKEN}",
                "Accept": "application/vnd.github.v3+json",
                "User-Agent": "pr-pilot/0.1.0",
            },
            json={"body": body},
        )
        logger.info("comment_posted", status=comment_resp.status_code)
    else:
        logger.info("review_posted", pr=pr_number, review_event=event)


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

    # Reuse a single httpx client for all GitHub API calls (connection pooling,
    # fewer TCP handshakes). The client lifecycle wraps the entire run.
    async with httpx.AsyncClient(follow_redirects=True) as http_client:
        # Fetch diff and files
        try:
            diff_text = await fetch_diff(context, http_client)
            context["diff"] = diff_text
            logger.info("diff_fetched", size=len(diff_text))
        except Exception as e:
            logger.error("diff_fetch_failed", error=str(e))
            sys.exit(1)

        try:
            changed_files = await fetch_changed_files(context, http_client)
            context["changed_files"] = changed_files
            logger.info("files_fetched", count=len(changed_files))
        except Exception:
            context["changed_files"] = []

        # Run the agent chain
        logger.info("running_agent_chain")
        chain = AgentChain()
        results = await chain.run(context)

        # Build review body and map decision to GitHub event (safety gate applied)
        decision = results.get("decision", "escalate_to_human")
        raw_event = decision_to_github_event(decision)
        github_event = apply_safety_gate(raw_event)
        review_body = build_review_body_with_safety_note(results, original_event=raw_event)

        # Post review
        await post_review(context, review_body, github_event, client=http_client)

    logger.info("pr_pilot_complete", decision=decision, github_event=github_event)

    # Set output for workflow
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as f:
            f.write(f"decision={decision}\n")
            f.write(f"autonomous={str(results.get('autonomy', False)).lower()}\n")


if __name__ == "__main__":
    asyncio.run(main())
