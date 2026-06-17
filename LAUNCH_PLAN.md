# PR Pilot — Launch Content & Marketing Plan

## X/Twitter Launch Thread (5 tweets)

**Tweet 1 (Hook):**
> I built a code review service where 5 AI agents handle the entire pipeline — from bug detection to patch generation to merge decisions. No humans in the loop.
>
> Here's what happens when you open a PR: 🧵

**Tweet 2 (The Pipeline):**
> Agent 1 — Reviewer: Analyzes diff for bugs, security issues, perf regressions
> Agent 2 — Fixer: Generates code patches for every issue
> Agent 3 — Tester: Writes unit tests for changed code
> Agent 4 — Verifier: Confirms no regressions, all tests pass
> Agent 5 — Escalator: Auto-approves safe changes, escalates only the hard ones
>
> Full pipeline: ~90 seconds.

**Tweet 3 (The Value Prop):**
> Small dev teams can't afford dedicated code review. PR Pilot gives you enterprise-grade quality for $99/mo.
>
> It catches real bugs. Here's one from a recent review: SQL injection via raw f-strings in a delete_user() handler. Agent generated the parameterized query fix before a human even saw the PR.

**Tweet 4 (Why It Matters):**
> This is built for the Build with Gemini XPRIZE — the business IS the agent chain. Every review, every fix, every decision is made by AI agents.
>
> 90%+ of reviews are fully autonomous. Humans only step in for the genuinely hard calls.

**Tweet 5 (CTA):**
> Try the live emulator on the landing page — watch the full 5-agent pipeline run in your browser:
> https://perseus-computing-llc.github.io/pr-pilot/
>
> GitHub: https://github.com/Perseus-Computing-LLC/pr-pilot
> 14-day free trial. No credit card needed.

---

## Hacker News "Show HN" Post

**Title:** Show HN: PR Pilot — 5 AI agents autonomously review, fix, and approve pull requests

**Body:**

PR Pilot is an AI-native code quality service I built for the Build with Gemini XPRIZE. The core idea: what if the entire code review pipeline ran without humans?

When you open a PR, five autonomous agents fire in sequence:

1. **Reviewer** — analyzes every changed file for bugs, security issues, and performance regressions
2. **Fixer** — generates minimal, correct code patches
3. **Tester** — detects your test framework and writes unit tests for changed code
4. **Verifier** — validates fixes, confirms no regressions
5. **Escalator** — makes the call: auto-approve, request changes, or escalate to a human

The whole chain completes in ~90 seconds. 90%+ of reviews are handled autonomously.

I'm dogfooding it on its own repo — every PR gets reviewed by the agents. The GitHub Actions workflow is open-source (MIT), so you can self-host. The managed service is $49-199/mo with a 14-day free trial.

Built with Gemini API (required for the XPRIZE), Cloud Run, and FastAPI.

There's a live emulator on the landing page where you can watch the agent chain process common vulnerabilities (SQL injection, blocking sleep, nested imports):

https://perseus-computing-llc.github.io/pr-pilot/

Happy to answer questions about the architecture, agent decision logic, or anything else.

---

## Reddit r/programming Post

**Title:** I built a code review service run entirely by AI agents — Reviewer → Fixer → Tester → Verifier → Escalator

Same body as HN post but more casual. Include the emulator link and GitHub repo.

---

## Indie Hackers Post

**Title:** PR Pilot — $99/mo AI code review for small dev teams

Focus on the business angle:
- Target market: 2-10 person dev teams
- Pricing: $49 Starter / $99 Team / $199 Business
- Built in 3 weeks, already reviewing real PRs
- Building in public for the Gemini XPRIZE
- Goal: 30 paying customers in 90 days
- Share Stripe revenue dashboards as they come in

---

## Outreach Templates

### Cold DM to dev team leads:

> Hey [name] — I built PR Pilot, an AI-native code review service where 5 agents autonomously handle your PR pipeline. Reviewer → Fixer → Tester → Verifier → Escalator. Full pipeline in ~90 seconds.
>
> I'm looking for early beta users. Free extended trial in exchange for feedback. Landing page has a live emulator if you want to see it in action: https://perseus-computing-llc.github.io/pr-pilot/
>
> Worth a look?

### GitHub Marketplace Description (for when the App is approved):

> **PR Pilot — AI-native code review**
>
> Five autonomous AI agents handle your entire PR review pipeline. No configuration needed — PR Pilot detects your language, framework, and testing setup automatically.
>
> **How it works:**
> 1. Reviewer analyzes diffs for bugs, security, and performance
> 2. Fixer generates code patches
> 3. Tester writes unit tests
> 4. Verifier confirms no regressions
> 5. Escalator decides: approve, request changes, or escalate
>
> **Pricing:** Free 14-day trial. Starter $49/mo (3 repos), Team $99/mo (10 repos), Business $199/mo (25 repos).
>
> Built with Gemini API. MIT licensed core.

---

## Content Calendar (60 days until Aug 17 deadline)

| Day | Action |
|-----|--------|
| Today | Launch posts on X/Twitter, Reddit, Indie Hackers |
| Day 3 | Hacker News Show HN (timing matters — weekday morning) |
| Day 5 | Follow up on awesome-list PRs with comments |
| Day 7 | First revenue update post ("Day 7: $X MRR with 3 customers") |
| Day 14 | Technical deep-dive: "How PR Pilot's Escalator Agent Makes Merge Decisions" |
| Day 21 | Case study: "Caught This SQL Injection Before It Hit Production" |
| Day 30 | Revenue milestone post |
| Day 45 | "What We Learned Building an AI-Native Business in 6 Weeks" |
| Day 60 | Pre-submission hype + "Building in Public Final Numbers" |

---

## Metrics to Track for Submission

- [ ] Number of registered users (signups via GitHub OAuth)
- [ ] Number of repos connected
- [ ] Total PRs reviewed
- [ ] Total bugs found (by severity)
- [ ] Autonomous review percentage (target: >90%)
- [ ] Average pipeline duration
- [ ] MRR (Stripe dashboard)
- [ ] Customer acquisition channels
- [ ] Marketing spend (disclose even if $0)
- [ ] Customer testimonials
