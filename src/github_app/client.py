"""
GitHub API client for PR Pilot.
Handles fetching PR diffs, posting reviews, and managing comments.
"""

from __future__ import annotations

import asyncio
import structlog
from typing import Any

import httpx

logger = structlog.get_logger(__name__)

# Retryable HTTP status codes
_RETRYABLE_STATUSES = {429, 500, 502, 503, 504}
_MAX_RETRIES = 3
_BASE_DELAY = 2.0  # seconds


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

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _request(
        self,
        method: str,
        url: str,
        headers: dict | None = None,
        **kwargs: Any,
    ) -> httpx.Response:
        """Send an HTTP request with retry on rate limits and transient errors.

        Retries on 429 (rate limit), 403 with Retry-After (secondary limit),
        and 5xx server errors. Respects Retry-After and X-RateLimit-Reset headers.
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
            headers={"Accept": "application/vnd.github.v3.diff"},
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
        test framework; an incomplete listing is harmless.
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        resp = await self._request("GET", url)
        if resp.status_code != 200:
            return []
        contents = resp.json()
        files = []
        for item in contents:
            if item["type"] == "file":
                files.append(item["path"])
            elif (
                item["type"] == "dir"
                and item["name"] not in (".git", "node_modules", "__pycache__")
            ):
                if path.count("/") < 1:
                    files.extend(
                        await self.get_repo_file_listing(owner, repo, item["path"])
                    )
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
        import time
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
