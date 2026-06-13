# PR Pilot — Autonomous PR Review

**5 agents. One pipeline. Zero manual review.**

PR Pilot autonomously reviews pull requests using a 5-agent chain — Reviewer analyzes, Fixer patches, Tester validates, Verifier gates, Escalator decides. Built for the [Build with Gemini XPRIZE](https://xprize.devpost.com/).

[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue)]()

## Agent Pipeline

```
Webhook → Reviewer → Fixer → Tester → Verifier → Escalator → Review Posted
```

| Agent | Role | Latency |
|---|---|---|
| **Reviewer** | Analyzes PR diff for bugs, security, performance, style | ~14s |
| **Fixer** | Generates minimal code patches for issues found | ~29s |
| **Tester** | Detects test framework, generates tests for changed code | ~16s |
| **Verifier** | Validates fixes and tests — no regressions | ~17s |
| **Escalator** | Decides: auto-approve, request changes, or escalate | ~18s |

**Pipeline total: ~94s** | **Cost: ~$0.04/review** (Gemini 2.5 Flash)

## Graduated Autonomy (The Safety Gate)

PR Pilot doesn't just approve or reject. It operates at three graduated levels — each escalating only when confidence demands it.

| Level | Action | When |
|---|---|---|
| **L1 · Comment** | Issues found, fixes attached as review comments. No merge blocked. | Low confidence findings |
| **L2 · Request Changes** | Medium-confidence issues that should block merge. Fixes provided inline. PR blocked until author responds. | Missing validation, incomplete tests |
| **L3 · Verified Auto-Approve** | All agents agree: PR is clean, fixes verified, tests pass. Auto-approves and merges. No human in the loop. | Clean PRs, all gates passed |

```
L1:  Reviewer: "line 42: unsafe shell exec"
     Fixer: "Use subprocess.run with list args"
     Escalator: COMMENT

L2:  Reviewer: "missing input validation"
     Fixer: "Add pydantic model for request body"
     Verifier: "Patch compiles, needs tests"
     Escalator: REQUEST_CHANGES

L3:  Reviewer: "No issues found"
     Tester: "Coverage maintained at 87%"
     Verifier: "All gates passed"
     Escalator: VERIFIED_AUTO_APPROVE
```

The safety gate is what separates autonomous review from automated rubber-stamping.

## Architecture

```
FastAPI webhook → AgentChain orchestration → Gemini API → GitHub comment/post
```

- **Cloud Run deployable** — one `gcloud run deploy` command, zero-downtime, auto-scaling
- **Full audit trail** — every agent's reasoning, every fix generated, every decision logged to `data/reviews/`. Structured JSON for compliance and transparency.
- **GitHub App integration** — webhook receiver, PR API client, review comment posting
- **Agent operations dashboard** — real-time review status UI at `/dashboard`. Disabled by default; enable with `DASHBOARD_TOKEN` in your `.env`. See `.env.example` for details.

## Quick Start

```bash
# Install
pip install -e ".[dev]"

# Configure
cp .env.example .env
# Fill in GEMINI_API_KEY, GITHUB_APP_ID, etc.

# Deploy to Cloud Run
gcloud run deploy pr-pilot \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GEMINI_API_KEY=...,GITHUB_APP_ID=...

# Open a PR — PR Pilot reviews it
git checkout -b feat/new-feature
git push && gh pr create
# Seconds later: @pr-pilot-bot commented: "Reviewed. 2 suggestions. 0 issues."
```

## XPRIZE Compliance

Built for the Build with Gemini XPRIZE. Every requirement met with documentation to match.

| Requirement | Implementation |
|---|---|
| **Gemini API** | All 5 agents use Gemini 2.5 Flash via `google-generativeai`. Structured output support. Exponential retry. |
| **Google Cloud Deploy** | Cloud Run (serverless), Cloud Build (CI/CD), Artifact Registry (containers). |
| **Stripe Integration** | Stripe Checkout for premium features. Usage-based billing via Stripe Metered billing API. Webhook handling. |
| **Code Quality** | Type hints throughout. Structured logging (structlog). 85%+ test coverage. Pre-commit hooks. |
| **Open Source** | MIT licensed. Public repo with contribution guide, issue templates, and pull request template. |

## Requirements

- Python 3.11+
- Gemini API key
- GitHub App (for webhook events and PR API access)
- Google Cloud Run (optional — works locally too)

## License

MIT — see [LICENSE](LICENSE)

---

Built for the [Build with Gemini XPRIZE](https://xprize.devpost.com/) · [Website](https://perseus.observer/pr-pilot/)
