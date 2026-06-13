"""
GitHub App webhook handler.
Receives PR events, triggers the agent chain, and posts results back to GitHub.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Any

import structlog
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from src.orchestration.engine import AgentChain
from src.github_app.client import GitHubClient
from src.github_app.idempotency import build_delivery_key, default_store
from src.config import (
    ALLOW_UNSIGNED_WEBHOOKS,
    CHAIN_TIMEOUT_SECONDS,
    GITHUB_WEBHOOK_SECRET,
    GITHUB_APP_ID,
    GITHUB_APP_PRIVATE_KEY,
    MAX_DIFF_SIZE_BYTES,
)
from src.review_poster import (
    apply_safety_gate,
    build_review_body,
    build_review_body_with_safety_note,
    decision_to_github_event,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/webhook", tags=["github"])


def verify_signature(payload: bytes, signature: str) -> bool:
    """Verify GitHub webhook signature.

    Fails closed: if no secret is configured we reject the request unless the
    operator has explicitly opted into an unsigned-dev bypass via
    ALLOW_UNSIGNED_WEBHOOKS=true. This must never be set in production.
    """
    if not GITHUB_WEBHOOK_SECRET:
        if ALLOW_UNSIGNED_WEBHOOKS:
            logger.warning("webhook_secret_not_configured_dev_bypass")
            return True
        logger.error("webhook_secret_not_configured_rejecting")
        return False

    if not signature:
        return False

    mac = hmac.new(
        GITHUB_WEBHOOK_SECRET.encode(),
        payload,
        hashlib.sha256,
    )
    expected = f"sha256={mac.hexdigest()}"
    return hmac.compare_digest(expected, signature)


@router.post("/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
    x_github_delivery: str = Header(default=""),
) -> dict[str, Any]:
    """Receive GitHub webhook events and acknowledge quickly.

    Webhook processing must return fast: the full agent chain takes tens of
    seconds, far longer than GitHub's delivery timeout, which would otherwise
    trigger retries and duplicate reviews. We verify and dedupe synchronously,
    then run the review in a background task and return 202 immediately.
    """
    body = await request.body()

    # Verify signature
    if not verify_signature(body, x_hub_signature_256):
        logger.error("invalid_signature")
        raise HTTPException(status_code=401, detail="Invalid signature")

    payload = await request.json()
    logger.info("webhook_received", github_event=x_github_event, action=payload.get("action", ""))

    # Only handle PR events
    if x_github_event not in ("pull_request",):
        return {"status": "ignored", "event": x_github_event}

    action = payload.get("action", "")
    if action not in ("opened", "synchronize", "reopened"):
        logger.info("action_ignored", action=action)
        return {"status": "ignored", "action": action}

    # Extract and validate PR info before accepting the delivery.
    pr = payload.get("pull_request", {})
    repo = payload.get("repository", {})
    installation = payload.get("installation", {})

    pr_number = pr.get("number")
    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("full_name", "")
    pr_title = pr.get("title", "")
    pr_description = pr.get("body", "") or ""
    head_sha = pr.get("head", {}).get("sha", "")

    if not pr_number or not owner or not head_sha:
        logger.error("invalid_payload_structure", pr=pr_number, owner=owner, sha=head_sha)
        return {"status": "error", "detail": "Payload missing required PR fields (number, owner, head.sha)"}

    # Idempotency: collapse redeliveries and repeated synchronize events for the
    # same head commit so we do not run the chain or post a review twice.
    dedup_key = build_delivery_key(x_github_delivery, repo_name, pr_number, head_sha)
    if not default_store.add(dedup_key):
        logger.info("duplicate_delivery_skipped", key=dedup_key, pr=pr_number)
        return {"status": "duplicate", "key": dedup_key}

    logger.info("pr_event_accepted", owner=owner, repo=repo_name, pr=pr_number, action=action)

    # Schedule the heavy work and acknowledge immediately.
    background_tasks.add_task(
        _process_pr_review,
        owner=owner,
        repo_name=repo_name,
        pr_number=pr_number,
        pr_title=pr_title,
        pr_description=pr_description,
        installation=installation,
        dedup_key=dedup_key,
    )
    return {"status": "accepted", "pr": pr_number, "key": dedup_key}


async def _process_pr_review(
    *,
    owner: str,
    repo_name: str,
    pr_number: int,
    pr_title: str,
    pr_description: str,
    installation: dict[str, Any],
    dedup_key: str,
) -> dict[str, Any]:
    """Background worker: run the agent chain and post the review to GitHub."""
    # Get installation token for this repo
    try:
        gh_client = GitHubClient(token="")  # will be replaced
        installation_id = installation.get("id", 0)
        if installation_id and GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY:
            token = await gh_client.get_installation_token(
                installation_id, GITHUB_APP_ID, GITHUB_APP_PRIVATE_KEY
            )
            gh_client = GitHubClient(token=token)
        else:
            logger.warning("no_installation_token — using webhook context only")
            return {"status": "skipped", "detail": "GitHub App not configured"}
    except Exception as exc:
        logger.error("token_error", error=str(exc))
        return {"status": "error", "detail": f"Failed to get installation token: {exc}"}

    # Fetch PR diff and files
    try:
        diff_text, pr_data = await gh_client.get_pr_diff(owner, repo_name.split("/")[-1], pr_number)
        changed_files = [f["filename"] for f in await gh_client.get_pr_files(owner, repo_name.split("/")[-1], pr_number)]
        project_files_list = await gh_client.get_repo_file_listing(owner, repo_name.split("/")[-1])
    except Exception as exc:
        logger.error("fetch_error", error=str(exc))
        return {"status": "error", "detail": f"Failed to fetch PR data: {exc}"}

    # Enforce diff size limit before running the chain. Oversized PRs are not
    # auto-reviewed; they are escalated to a human with an explanatory comment.
    diff_bytes = len(diff_text.encode("utf-8")) if diff_text else 0
    if diff_bytes > MAX_DIFF_SIZE_BYTES:
        logger.warning(
            "diff_too_large",
            pr=pr_number,
            diff_bytes=diff_bytes,
            limit=MAX_DIFF_SIZE_BYTES,
        )
        msg = (
            "## PR Pilot\n\n"
            f"This PR's diff ({diff_bytes:,} bytes) exceeds the configured review "
            f"limit ({MAX_DIFF_SIZE_BYTES:,} bytes). Skipping automated review and "
            "escalating to a human reviewer."
        )
        try:
            await gh_client.post_comment(owner, repo_name.split("/")[-1], pr_number, msg)
        except Exception:
            pass
        return {"status": "skipped", "detail": "diff too large", "diff_bytes": diff_bytes}

    # Build context for the agent chain
    pr_context = {
        "diff": diff_text,
        "pr_title": pr_title,
        "pr_description": pr_description,
        "repo_name": repo_name,
        "changed_files": changed_files,
        "project_files": "\n".join(project_files_list),
        "pr_number": pr_number,
        "project_rules": "",  # Could be loaded from .pr-pilot/config.yaml in the repo
    }

    # Run the agent chain with an overall timeout to prevent hanging
    # background tasks from consuming Cloud Run resources indefinitely.
    chain = AgentChain()
    try:
        if CHAIN_TIMEOUT_SECONDS > 0:
            results = await asyncio.wait_for(
                chain.run(pr_context), timeout=CHAIN_TIMEOUT_SECONDS
            )
        else:
            results = await chain.run(pr_context)
    except asyncio.TimeoutError:
        logger.error("chain_timeout", pr=pr_number, timeout=CHAIN_TIMEOUT_SECONDS)
        try:
            await gh_client.post_comment(
                owner, repo_name.split("/")[-1], pr_number,
                f"## PR Pilot\\n\\nThe agent chain timed out after {CHAIN_TIMEOUT_SECONDS}s. "
                "Escalating to human review."
            )
        except Exception:
            pass
        return {"status": "timeout", "detail": f"Chain exceeded {CHAIN_TIMEOUT_SECONDS}s timeout"}
    except Exception as exc:
        logger.error("chain_unhandled_error", pr=pr_number, error=str(exc))
        try:
            await gh_client.post_comment(
                owner, repo_name.split("/")[-1], pr_number,
                "## PR Pilot\\n\\nAn unexpected error occurred during automated review. "
                "Escalating to human review."
            )
        except Exception:
            pass
        return {"status": "error", "detail": str(exc)}

    # If an agent errored, the chain aborted — say so honestly instead of
    # posting a review that implies the PR was analyzed and found clean.
    pipeline_error = results.get("pipeline_error")
    if pipeline_error:
        msg = (
            "## PR Pilot\n\n"
            "Automated review pipeline could not complete: the "
            f"**{pipeline_error['agent']}** agent encountered an error "
            f"({pipeline_error['summary']}). No automated judgment was made — "
            "escalating to human review."
        )
        try:
            await gh_client.post_comment(owner, repo_name.split("/")[-1], pr_number, msg)
        except Exception as exc:
            logger.error("pipeline_error_comment_failed", error=str(exc))
        return {
            "status": "pipeline_error",
            "chain_id": results.get("chain_id"),
            "agent": pipeline_error["agent"],
        }

    # Post results to GitHub
    decision = results.get("decision", "escalate_to_human")
    escalator = results.get("escalator", {})

    if escalator.get("findings"):
        finding = escalator["findings"][0] if escalator["findings"] else {}
        review_body = finding.get("review_body", build_review_body(results))
        review_comments = finding.get("review_comments", [])
    else:
        review_body = build_review_body(results)
        review_comments = []

    # R-3: filter inline comments to only those with valid path+line
    # in the actual diff. A single hallucinated path/line 422s the
    # entire review submission, losing all inline comments.
    # We check: path is in changed_files AND the line falls inside
    # a parsed diff hunk for that file (not just > 0 — the line must
    # actually appear in the diff the LLM was given, otherwise it's a
    # hallucination).
    if review_comments and diff_text:
        # Build a map of file → set of valid line numbers from diff hunks.
        import re as _re
        _hunk_re = _re.compile(r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@')
        _file_re = _re.compile(r'^diff --git a/(.+) b/(.+)$')
        file_line_ranges: dict[str, set[int]] = {}
        current_file: str | None = None
        for raw_line in diff_text.splitlines():
            fm = _file_re.match(raw_line)
            if fm:
                current_file = fm.group(2)  # new file path
                if current_file not in file_line_ranges:
                    file_line_ranges[current_file] = set()
                continue
            hm = _hunk_re.match(raw_line)
            if hm and current_file:
                start = int(hm.group(1))
                count = int(hm.group(2) or 1)
                file_line_ranges[current_file].update(range(start, start + count))

        valid_comments = []
        for c in review_comments:
            c_path = c.get("path", "")
            c_line = c.get("line", 0)
            reason = ""
            if c_path not in changed_files:
                reason = "path not in changed_files"
            elif not isinstance(c_line, int) or c_line <= 0:
                reason = "invalid line number"
            elif c_path in file_line_ranges and c_line not in file_line_ranges[c_path]:
                reason = f"line {c_line} not in any diff hunk for {c_path}"
            if reason:
                logger.warning(
                    "dropping_invalid_comment",
                    path=c_path,
                    line=c_line,
                    reason=reason,
                )
            else:
                valid_comments.append(c)
        if len(valid_comments) < len(review_comments):
            logger.info(
                "filtered_review_comments",
                original=len(review_comments),
                valid=len(valid_comments),
            )
        review_comments = valid_comments

    raw_event = decision_to_github_event(decision)
    github_event = apply_safety_gate(raw_event)
    review_body = build_review_body_with_safety_note(results, original_event=raw_event)

    try:
        await gh_client.post_review(
            owner,
            repo_name.split("/")[-1],
            pr_number,
            body=review_body,
            event=github_event,
            comments=review_comments if review_comments else None,
        )
        logger.info("review_posted", pr=pr_number, decision=decision, github_event=github_event)
    except Exception as exc:
        logger.error("post_review_error", error=str(exc))
        # Fallback: post a simple comment
        try:
            await gh_client.post_comment(owner, repo_name.split("/")[-1], pr_number, review_body)
        except Exception:
            pass

    return {
        "status": "complete",
        "chain_id": results.get("chain_id"),
        "decision": decision,
        "autonomy": results.get("autonomy"),
    }
