"""Tests for the operational hardening: GitHub rate-limit retries and
chain short-circuit on agent error."""

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest

import src.github_app.client as client_mod
from src.agents.base import AgentResult, BaseAgent
from src.github_app.client import GitHubClient, _rate_limit_wait
from src.orchestration.engine import AgentChain


# ── _rate_limit_wait classification ─────────────────────────────────────────


def _resp(status: int, headers: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status, headers=headers or {}, request=httpx.Request("GET", "https://x")
    )


def test_retry_after_header_is_honored():
    assert _rate_limit_wait(_resp(429, {"retry-after": "7"})) == 7.0


def test_primary_rate_limit_uses_reset_timestamp():
    import time

    reset = str(int(time.time()) + 30)
    wait = _rate_limit_wait(
        _resp(403, {"x-ratelimit-remaining": "0", "x-ratelimit-reset": reset})
    )
    assert 25 <= wait <= 35


def test_plain_403_is_not_a_rate_limit():
    assert _rate_limit_wait(_resp(403)) is None


def test_success_is_not_a_rate_limit():
    assert _rate_limit_wait(_resp(200)) is None


# ── _request retry behavior ─────────────────────────────────────────────────


class FakeAsyncClient:
    """Stand-in for httpx.AsyncClient that pops canned responses."""

    responses: list = []  # class-level queue, set per test
    requests_made: list = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def request(self, method, url, **kwargs):
        FakeAsyncClient.requests_made.append((method, url))
        item = FakeAsyncClient.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


@pytest.fixture
def fake_http(monkeypatch):
    FakeAsyncClient.responses = []
    FakeAsyncClient.requests_made = []
    monkeypatch.setattr(client_mod.httpx, "AsyncClient", FakeAsyncClient)
    # Don't actually sleep during backoff.
    monkeypatch.setattr(client_mod.asyncio, "sleep", _instant_sleep)
    return FakeAsyncClient


async def _instant_sleep(_seconds):
    return None


def test_request_retries_429_then_succeeds(fake_http):
    fake_http.responses = [
        _resp(429, {"retry-after": "1"}),
        _resp(200),
    ]
    client = GitHubClient(token="t")
    resp = asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert resp.status_code == 200
    assert len(fake_http.requests_made) == 2


def test_request_retries_transient_5xx(fake_http):
    fake_http.responses = [_resp(502), _resp(200)]
    client = GitHubClient(token="t")
    resp = asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert resp.status_code == 200


def test_request_retries_network_errors(fake_http):
    fake_http.responses = [
        httpx.ConnectError("boom", request=httpx.Request("GET", "https://x")),
        _resp(200),
    ]
    client = GitHubClient(token="t")
    resp = asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert resp.status_code == 200


def test_request_does_not_retry_permission_403(fake_http):
    fake_http.responses = [_resp(403)]
    client = GitHubClient(token="t")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert len(fake_http.requests_made) == 1


def test_request_gives_up_after_max_attempts(fake_http):
    fake_http.responses = [_resp(429, {"retry-after": "1"})] * 3
    client = GitHubClient(token="t")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert len(fake_http.requests_made) == 3


def test_request_refuses_to_wait_past_cap(fake_http):
    fake_http.responses = [_resp(429, {"retry-after": "3600"})]
    client = GitHubClient(token="t")
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client._request("GET", "https://api.github.com/x"))
    assert len(fake_http.requests_made) == 1  # no pointless hour-long sleep


# ── chain short-circuit on agent error ──────────────────────────────────────


CONTEXT = {
    "diff": "+x",
    "pr_title": "t",
    "pr_description": "d",
    "repo_name": "r",
    "changed_files": [],
    "project_files": "",
    "pr_number": 1,
    "project_rules": "",
}


def test_chain_short_circuits_when_reviewer_errors(monkeypatch, tmp_path):
    import src.orchestration.engine as engine

    monkeypatch.setattr(engine, "STATE_DIR", tmp_path)

    async def _exploding_call(self, prompt, schema=None):
        raise RuntimeError("Gemini quota exceeded")

    downstream_ran = []
    chain = AgentChain()

    async def _spy_fixer(context):
        downstream_ran.append("fixer")
        return AgentResult(agent_name="fixer", status="pass", summary="")

    chain.fixer.run = _spy_fixer

    with patch.object(BaseAgent, "_call_gemini", _exploding_call):
        results = asyncio.run(chain.run(CONTEXT))

    assert results["pipeline_error"]["agent"] == "reviewer"
    assert results["decision"] == "escalate_to_human"
    assert results["autonomy"] is False
    assert downstream_ran == []  # fixer never ran on errored reviewer output
    assert "fixer" not in results


def test_chain_error_state_is_persisted(monkeypatch, tmp_path):
    import src.orchestration.engine as engine

    monkeypatch.setattr(engine, "STATE_DIR", tmp_path)

    async def _exploding_call(self, prompt, schema=None):
        raise RuntimeError("boom")

    chain = AgentChain()
    with patch.object(BaseAgent, "_call_gemini", _exploding_call):
        results = asyncio.run(chain.run(CONTEXT))

    saved = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert saved["pipeline_error"]["agent"] == "reviewer"
    assert saved["chain_id"] == results["chain_id"]


def test_chain_unchanged_when_agents_succeed(monkeypatch, tmp_path):
    """A 'fail' status (negative findings) must NOT trigger the short-circuit."""
    import src.orchestration.engine as engine

    monkeypatch.setattr(engine, "STATE_DIR", tmp_path)

    chain = AgentChain()
    for name in ("reviewer", "fixer", "tester", "verifier", "escalator"):
        agent = getattr(chain, name)

        async def _ok(context, _n=name):
            return AgentResult(
                agent_name=_n,
                status="fail" if _n == "reviewer" else "pass",
                summary="analyzed",
                metadata={"decision": "request_changes"} if _n == "escalator" else {},
            )

        agent.run = _ok

    results = asyncio.run(chain.run(CONTEXT))
    assert "pipeline_error" not in results
    assert results["decision"] == "request_changes"
    assert all(n in results for n in ("reviewer", "fixer", "tester", "verifier", "escalator"))
