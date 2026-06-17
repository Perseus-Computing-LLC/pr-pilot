# PR Pilot — Outreach & Launch Copy

## GitHub Marketplace Listing

**Name:** PR Pilot
**Short description (max 200 chars):**
Autonomous code review powered by Gemini. Five AI agents review every PR, find bugs, generate fixes, write tests, and decide what to ship. Install and your PRs review themselves.

**Full description:**

PR Pilot is an AI-native code quality service. When you open a pull request, five autonomous agents spring into action:

1. **Reviewer** — Analyzes every changed file for bugs, security vulnerabilities, performance regressions, and style violations
2. **Fixer** — Generates minimal, correct code patches for every issue found
3. **Tester** — Detects your test framework and writes unit tests for changed code
4. **Verifier** — Validates all fixes and tests, confirming no regressions
5. **Escalator** — Makes the final call: auto-approve safe changes, request revisions, or escalate to a human

90%+ of reviews are handled autonomously. You just merge.

**Pricing:**
- Free 14-day trial (no credit card)
- Starter: $49/mo (3 repos, 500 reviews/mo)
- Team: $99/mo (10 repos, unlimited reviews)
- Business: $199/mo (25 repos, priority support)

**Category:** Code review
**Supported languages:** All — language-agnostic agent pipeline

---

## Launch Posts

### X/Twitter (280 chars)

> Small dev teams skip code review because they can't afford it. PR Pilot fixes that — 5 AI agents autonomously review every pull request, find bugs, generate fixes, and write tests. 90%+ autonomous. Install the GitHub App and your PRs review themselves. https://github.com/Perseus-Computing-LLC/pr-pilot

### X/Twitter — Bug Catch (content marketing angle)

> Just ran PR Pilot against a PR with an SQL injection vulnerability. The pipeline caught it, generated a fix, wrote tests, verified no regressions, and posted the review — in 94 seconds. No human touched it. Five agents. One pipeline. https://github.com/Perseus-Computing-LLC/pr-pilot

### Hacker News (Show HN title)

> Show HN: PR Pilot — Autonomous code review with 5 AI agents (no humans in the loop)

**Body:**

> Built for the Gemini XPRIZE. The business IS the agent chain — Reviewer → Fixer → Tester → Verifier → Escalator handle the entire PR review lifecycle autonomously.
>
> Technical details: FastAPI on Cloud Run, Gemini 2.5 Pro with structured JSON output, GitHub App with installation tokens, fully auditable agent decision trail.
>
> Tested end-to-end with a real PR containing an SQL injection vulnerability: the chain caught it, generated a parameterized query fix, wrote pytest tests, verified no regressions, and posted the review in 94 seconds. 5 agents, 0 human touches.
>
> Free for open source. $49-199/mo for private repos. 14-day trial.
>
> Repo: https://github.com/Perseus-Computing-LLC/pr-pilot

### Reddit r/programming

**Title:** I built a 5-agent autonomous code review pipeline that handles PRs without human intervention

**Body:**

> PR Pilot runs on your repos via a GitHub App. Open a PR and five AI agents fire in sequence:
>
> - Reviewer: Analyzes the diff for bugs, security issues, performance
> - Fixer: Generates minimal patches for every issue
> - Tester: Detects your framework and writes unit tests
> - Verifier: Validates everything, checks for regressions
> - Escalator: Decides to auto-approve, request changes, or escalate
>
> The whole pipeline takes ~90 seconds. 90%+ of reviews are autonomous.
>
> I built it for the Gemini XPRIZE — the differentiator is that the agents ARE the business. No human reviews standard PRs.
>
> Tech: FastAPI + Gemini 2.5 Pro + GitHub App API + Cloud Run. Structured JSON output between agents means downstream agents get typed, validated input.
>
> Open source (MIT): https://github.com/Perseus-Computing-LLC/pr-pilot

### Discord (dev communities)

> Built PR Pilot — an AI-native code review service where 5 agents autonomously handle every PR. The chain: Reviewer finds bugs → Fixer generates patches → Tester writes tests → Verifier confirms no regressions → Escalator decides to ship or escalate. 90%+ autonomous. Built for the Gemini XPRIZE. Open source. https://github.com/Perseus-Computing-LLC/pr-pilot

### Indie Hackers

**Title:** PR Pilot: 5 AI agents that autonomously review your pull requests

**Body:**

> I'm building PR Pilot for the Gemini XPRIZE. The core idea: small dev teams (2-10 people) can't afford dedicated code review. They ship bugs, miss security issues, accumulate tech debt.
>
> PR Pilot gives them enterprise-grade code quality for $99/month. Five AI agents handle the entire PR review pipeline:
>
> 1. Reviewer: Finds bugs, security issues, performance regressions
> 2. Fixer: Generates code patches
> 3. Tester: Writes unit tests
> 4. Verifier: Validates everything
> 5. Escalator: Decides to approve, request changes, or escalate
>
> The agents ARE the business — this isn't AI-assisted code review, it's autonomous code review. Humans only step in for the genuinely hard calls.
>
> Tech stack: FastAPI + Gemini 2.5 Pro + GitHub App + Cloud Run
> Pricing: $49-199/mo with 14-day free trial
>
> Open source: https://github.com/Perseus-Computing-LLC/pr-pilot
>
> I'm targeting 20-30 paying customers in 90 days. If you're a small team that skips code review because you can't afford it, try the free trial.

---

## Keywords for Discovery

`autonomous code review`, `AI code review`, `Gemini code review`, `automated PR review`, `AI-native`, `pull request bot`, `code quality`, `GitHub App`, `AI agent pipeline`, `autonomous agents`, `XPRIZE`, `dev tools`, `developer tools`

---

## Key Messages for Different Channels

| Channel | Angle |
|---|---|
| Hacker News | Technical architecture, agent chain design, structured output |
| Reddit | Personal project story, open source, built for XPRIZE |
| X/Twitter | Bug catches, speed, "94 seconds" stat, before/after |
| Indie Hackers | Business angle, pricing, target market, MRR goal |
| Discord | Quick pitch, "autonomous code review", link drop |
| GitHub Marketplace | Technical description, integrations, pricing tiers |
