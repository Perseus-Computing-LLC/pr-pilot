"""
GitHub API client for PR Pilot.
Handles fetching PR diffs, posting reviews, and managing comments.

All requests go through a retry wrapper that understands GitHub's rate
limiting (403/429 with Retry-After / X-RateLimit-Reset) and transient
5xx/network failures, so a burst of API calls doesn't silently drop a
review mid-chain.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import structlog

import httpx

logger = structlog.get_logger(__name__)

# Statuses worth a blind retry with backoff (no rate-limit semantics).
RETRYABLE_STATUSES = {500, 502, 503, 504}
MAX_ATTEMPTS = 3
# Never sleep longer than this on a rate limit — a webhook background task
# waiting out a long reset window would pile up; surface the error instead.
MAX_RATE_LIMIT_WAIT_SECONDS = 60.0


def _rate_limit_wait(resp: httpx.Response) -> float | None:
    """Seconds to wait if this response is a rate limit, else None.

    GitHub signals primary limits via X-RateLimit-Remaining: 0 plus a
    reset timestamp, and secondary limits via Retry-After. A plain 403
    without those headers is a permission error — not retryable.
    """
    if resp.status_code not in (403, 429):
        return None
    retry_after = resp.headers.get("retry-after")
    if retry_after:
        try:
            return max(float(retry_after), 1.0)
        except ValueError:
            return 1.0
    if resp.headers.get("x-ratelimit-remaining") == "0":
        reset = resp.headers.get("x-ratelimit-reset")
        if reset:
            try:
                return max(float(reset) - time.time() + 1.0, 1.0)
            except ValueError:
                return 1.0
        return 1.0
    if resp.status_code == 429:
        return 1.0
    return None  # 403 without rate-limit markers: permission error


class GitHubClient:
    """Thin wrapper around the GitHub REST API for PR operations."""

    def __init__(self, token: str) -> None:
        self.token = token
        self.base_url = "https://api.github.com"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "pr-pilot/0.1.0",
        }
        # R-1: shared client for connection reuse and consistent retry
        self._client: httpx.AsyncClient | None = None

    async def _request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Issue a request with rate-limit-aware retries.

        Retries up to MAX_ATTEMPTS on: rate limits (waiting out the
        documented reset, capped), transient 5xx, and network errors.
        Raises httpx.HTTPStatusError for everything else, and for
        rate limits whose reset is too far away to wait for.
        """
        last_exc: Exception | None = None
        for attempt in range(MAX_ATTEMPTS):
            try:
                async with httpx.AsyncClient() as client:
                    resp = await client.request(
                        method, url, headers=headers or self.headers, **kwargs
                    )
            except httpx.TransportError as exc:
                last_exc = exc
                logger.warning(
                    "github_network_error",
                    url=url,
                    attempt=attempt + 1,
                    error=str(exc),
                )
                await asyncio.sleep(2**attempt)
                continue

            wait = _rate_limit_wait(resp)
            if wait is not None:
                if attempt == MAX_ATTEMPTS - 1 or wait > MAX_RATE_LIMIT_WAIT_SECONDS:
                    logger.error(
                        "github_rate_limited_giving_up", url=url, wait_needed=wait
                    )
                    resp.raise_for_status()
                logger.warning(
                    "github_rate_limited",
                    url=url,
                    wait_seconds=round(wait, 1),
                    attempt=attempt + 1,
                )
                await asyncio.sleep(wait)
                continue

            if resp.status_code in RETRYABLE_STATUSES and attempt < MAX_ATTEMPTS - 1:
                logger.warning(
                    "github_server_error_retrying",
                    url=url,
                    status=resp.status_code,
                    attempt=attempt + 1,
                )
                await asyncio.sleep(2**attempt)
                continue

            resp.raise_for_status()
            return resp

        # Only reachable when every attempt hit a network error.
        raise last_exc if last_exc else RuntimeError(f"request failed: {url}")

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> tuple[str, dict]:
        """Fetch the raw diff and PR metadata for a pull request.

        Returns:
            Tuple of (diff_text, pr_metadata_dict)
        """
        client = self._get_client()
        merged_headers = {**self.headers, **(headers or {})}
        last_exception: Exception | None = None

        for attempt in range(_MAX_RETRIES + 1):
            try:
                resp = await client.request(
                    method, url, headers=merged_headers, **kwargs
                )
                status = resp.status_code

                if status < 400:
                    return resp

                # Determine retry eligibility
                should_retry = status in _RETRYABLE_STATUSES
                if status == 403:
                    # Check for secondary rate limit (Retry-After header)
                    retry_after = resp.headers.get("Retry-After") or resp.headers.get(
                        "retry-after", ""
                    )
                    if retry_after:
                        should_retry = True

                if not should_retry or attempt >= _MAX_RETRIES:
                    resp.raise_for_status()

                # Respect Retry-After or X-RateLimit-Reset
                delay = self._retry_delay(resp, attempt)
                logger.warning(
                    "GitHub API rate limited",
                    status=status,
                    attempt=attempt,
                    delay=delay,
                    url=url,
                )
                await asyncio.sleep(delay)
            except httpx.HTTPStatusError:
                raise
            except (httpx.ConnectError, httpx.TimeoutException) as e:
                last_exception = e
                if attempt < _MAX_RETRIES:
                    delay = _BASE_DELAY * (2**attempt)
                    logger.warning(
                        "GitHub API connection error, retrying",
                        attempt=attempt,
                        delay=delay,
                        error=str(e),
                    )
                    await asyncio.sleep(delay)
                    continue
                raise

        if last_exception:
            raise last_exception
        raise RuntimeError("max retries exhausted")

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        """Compute retry delay from response headers or exponential backoff."""
        # Respect Retry-After header if present
        retry_after = resp.headers.get("Retry-After") or resp.headers.get(
            "retry-after", ""
        )
        if retry_after:
            try:
                return float(retry_after)
            except ValueError:
                pass

        # Respect X-RateLimit-Reset if present
        import time

        reset_ts = resp.headers.get("X-RateLimit-Reset") or resp.headers.get(
            "x-ratelimit-reset", ""
        )
        if reset_ts:
            try:
                now = time.time()
                reset = float(reset_ts)
                wait = reset - now + 1  # +1s buffer
                if 0 < wait < 300:
                    return wait
            except (ValueError, TypeError):
                pass

        # Exponential backoff fallback
        return _BASE_DELAY * (2**attempt)

    async def get_pr_diff(
        self, owner: str, repo: str, pr_number: int
    ) -> tuple[str, dict]:
        """Fetch the raw diff and PR metadata for a pull request."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        resp = await self._request("GET", url)
        pr_data = resp.json()

        diff_resp = await self._request(
            "GET",
            url,
            headers={**self.headers, "Accept": "application/vnd.github.v3.diff"},
        )
        return diff_resp.text, pr_data

    async def get_pr_files(
        self, owner: str, repo: str, pr_number: int
    ) -> list[dict]:
        """List all changed files in a PR, following pagination."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files: list[dict] = []
        page = 1
        while True:
            resp = await self._request(
                "GET", url, params={"per_page": 100, "page": page}
            )
            batch = resp.json()
            files.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return files

    async def get_repo_file_listing(
        self, owner: str, repo: str, path: str = ""
    ) -> list[str]:
        """Get a best-effort listing of files in the repo (for test framework detection).

        File listing is best-effort: pagination is not handled, and repos with
        more than ~1000 files in a single directory will produce an incomplete
        listing. The result is only used to help the Tester agent guess the
        test framework; an incomplete listing is harmless — including when the
        request itself fails (404 on empty repos, etc.), hence the broad catch.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        try:
            resp = await self._request("GET", url)
        except (httpx.HTTPStatusError, httpx.TransportError):
            return []
        contents = resp.json()
        files = []
        for item in contents:
            if item["type"] == "file":
                files.append(item["path"])
            elif item["type"] == "dir" and item["name"] not in (".git", "node_modules", "__pycache__"):
                # Limited depth: only top 2 levels
                if path.count("/") < 1:
                    files.extend(await self.get_repo_file_listing(owner, repo, item["path"]))
        return files

    async def post_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        event: str = "COMMENT",
        comments: list[dict] | None = None,
    ) -> dict:
        """Post a PR review with optional inline comments."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/reviews"
        payload: dict[str, Any] = {
            "body": body,
            "event": event,  # APPROVE, REQUEST_CHANGES, COMMENT
        }
        if comments:
            payload["comments"] = comments

        resp = await self._request("POST", url, json=payload)
        return resp.json()

    async def post_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict:
        """Post a general comment on the PR."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        resp = await self._request("POST", url, json={"body": body})
        return resp.json()

    async def get_installation_token(
        self, installation_id: int, app_id: str, private_key: str
    ) -> str:
        """Get an installation access token for a GitHub App."""
        # Generate JWT for app authentication
        import jwt

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": app_id,
        }
        encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        resp = await self._request(
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {encoded_jwt}",
                "Accept": "application/vnd.github.v3+json",
            },
        )
        return resp.json()["token"]
