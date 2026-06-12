"""
GitHub API client for PR Pilot.
Handles fetching PR diffs, posting reviews, and managing comments.
"""

from __future__ import annotations

import structlog
from typing import Any

import httpx

logger = structlog.get_logger(__name__)


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

    async def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> tuple[str, dict]:
        """Fetch the raw diff and PR metadata for a pull request.
        
        Returns:
            Tuple of (diff_text, pr_metadata_dict)
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}"
        async with httpx.AsyncClient() as client:
            # Standard JSON response for metadata
            resp = await client.get(url, headers=self.headers)
            resp.raise_for_status()
            pr_data = resp.json()

            # Raw diff
            diff_resp = await client.get(
                url,
                headers={**self.headers, "Accept": "application/vnd.github.v3.diff"},
            )
            diff_resp.raise_for_status()
            return diff_resp.text, pr_data

    async def get_pr_files(self, owner: str, repo: str, pr_number: int) -> list[dict]:
        """List all changed files in a PR, following pagination."""
        url = f"{self.base_url}/repos/{owner}/{repo}/pulls/{pr_number}/files"
        files: list[dict] = []
        async with httpx.AsyncClient() as client:
            page = 1
            while True:
                resp = await client.get(
                    url, headers=self.headers, params={"per_page": 100, "page": page}
                )
                resp.raise_for_status()
                batch = resp.json()
                files.extend(batch)
                if len(batch) < 100:
                    break
                page += 1
        return files

    async def get_repo_file_listing(self, owner: str, repo: str, path: str = "") -> list[str]:
        """Get a listing of files in the repo (for test framework detection)."""
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        async with httpx.AsyncClient() as client:
            resp = await client.get(url, headers=self.headers)
            if resp.status_code != 200:
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

        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers, json=payload)
            resp.raise_for_status()
            return resp.json()

    async def post_comment(
        self, owner: str, repo: str, pr_number: int, body: str
    ) -> dict:
        """Post a general comment on the PR."""
        url = f"{self.base_url}/repos/{owner}/{repo}/issues/{pr_number}/comments"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=self.headers, json={"body": body})
            resp.raise_for_status()
            return resp.json()

    async def get_installation_token(
        self, installation_id: int, app_id: str, private_key: str
    ) -> str:
        """Get an installation access token for a GitHub App."""
        # Generate JWT for app authentication
        import time
        import jwt

        now = int(time.time())
        payload = {
            "iat": now - 60,
            "exp": now + 600,
            "iss": app_id,
        }
        encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

        # Exchange JWT for installation token
        url = f"{self.base_url}/app/installations/{installation_id}/access_tokens"
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {encoded_jwt}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            resp.raise_for_status()
            return resp.json()["token"]
