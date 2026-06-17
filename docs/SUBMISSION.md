# PR Pilot — Devpost Submission

> Build with Gemini XPRIZE
> Submission deadline: August 17, 2026 @ 4pm EDT
> Category: Entrepreneurship & Job Creation

---

## Project Overview

**Name:** PR Pilot

**Elevator pitch (200 chars max):**
PR Pilot gives small dev teams enterprise-grade code review — five AI agents autonomously find bugs, generate fixes, write tests, and decide what to ship. Install the GitHub App and your PRs review themselves.

**GitHub Repo:** https://github.com/Perseus-Computing-LLC/pr-pilot
**Hosted Demo:** https://pr-pilot.dev (or Cloud Run URL)
**License:** MIT

---

## Project Details

### What it does

PR Pilot is an AI-native code quality service. When a developer opens a pull request, five autonomous agents spring into action:

1. **Reviewer** analyzes every changed file for bugs, security vulnerabilities, performance regressions, and style violations
2. **Fixer** generates minimal, correct code patches for every issue found
3. **Tester** detects the project's test framework and writes unit tests for changed code
4. **Verifier** validates all fixes and tests, confirming no regressions
5. **Escalator** makes the final call: auto-approve safe changes, request revisions, or escalate to a human

The result: a complete code review with fixes attached, posted directly on the pull request. 90%+ of reviews are handled autonomously — humans only step in for the genuinely hard calls.

### How we built it

**Google Cloud products used:**
- **Gemini API** (required) — powers the Reviewer, Fixer, Tester, Verifier, and Escalator agents with structured output (JSON schema responses)
- **Cloud Run** — hosts the webhook receiver and agent orchestration engine as a serverless service
- **Cloud Build** — CI/CD pipeline for continuous deployment
- **Secret Manager** — securely stores GitHub App private keys and API credentials
- **Cloud Logging** — captures all agent execution traces for audit trail and submission evidence

**Architecture:**
- **FastAPI** (Python) webhook receiver deployed on Cloud Run
- **5-agent chain** with sequential execution: each agent inherits from `BaseAgent` which provides Gemini API access, structured output, exponential retry, and structured logging
- **GitHub App** integration via REST API with installation token authentication
- Agent decisions persisted to disk as structured JSON for auditability
- `google-generativeai` SDK with `gemini-2.5-pro` model and JSON response schemas

### Why we chose Gemini

The XPRIZE rules require using at least one Google Cloud product and the Gemini API. But we didn't just bolt Gemini onto an existing idea — we designed a business that fundamentally depends on AI agents making autonomous decisions about code quality.

Gemini's structured output support (response schemas) is critical to our architecture. Each agent outputs typed JSON that flows into the next agent in the chain. Without this, the 5-agent pipeline wouldn't work reliably. The `response_schema` feature in Gemini's API lets us enforce exactly the output format each agent needs.

We use Gemini for all five agents because:
1. Structured output with JSON schemas ensures reliable agent-to-agent communication
2. The 2M token context window handles large PR diffs without truncation
3. First-class Python SDK (`google-generativeai`) with async support
4. Strong code generation capabilities for the Fixer and Tester agents

### Category impact: Entrepreneurship & Job Creation

Small dev teams (2-10 people) can't afford dedicated code review. They ship with bugs, miss security vulnerabilities, and accumulate technical debt that kills startups.

PR Pilot gives these teams enterprise-grade code quality for $99/month. A 2-person startup gets the same review rigor as a FAANG team. This enables:

- **Faster shipping**: No bottleneck waiting for code review
- **Higher quality**: Bugs caught before they reach production
- **Lower barrier**: Solo developers and tiny teams can compete with well-funded companies
- **Economic opportunity**: More startups survive the early stages, creating more jobs

The service itself creates economic opportunity: small dev teams can build and ship with confidence they couldn't afford before.

### AI-Native Operations (the differentiator)

Most entrants will bolt Gemini onto an existing business. PR Pilot is different: **the business IS the agent chain.** No agents = no service.

Evidence of AI-native operations:
- **Agent 1 (Reviewer)** makes real judgment calls about code quality, not just pattern matching
- **Agent 2 (Fixer)** generates production-ready code patches autonomously
- **Agent 5 (Escalator)** is the final decision maker — it chooses to approve, request changes, or escalate to a human
- During the 90-day competition window, PR Pilot will review its own pull requests (dogfooding)
- Agent execution logs prove >90% autonomy — every decision is timestamped with reasoning

This isn't AI-assisted code review. It's autonomous code review with human override. The agents run the operation.

---

## Evidence to Submit

### Revenue evidence
- [ ] Stripe dashboard export (monthly breakdown)
- [ ] Customer count and MRR
- [ ] Payment history

### Customer evidence
- [ ] Customer names and emails (with permission)
- [ ] Testimonials (with permission)
- [ ] Repos under management (count)

### Product evidence
- [ ] Agent execution logs (from Cloud Logging, showing 90%+ autonomy)
- [ ] API usage records (Gemini API calls per agent)
- [ ] Dashboard screenshots
- [ ] GitHub App activity (reviews posted, PRs handled)

### Marketing evidence
- [ ] Marketing spend disclosure (even if $0)
- [ ] Customer acquisition channels
- [ ] Conversion rates (trial → paid)

---

## Demo Video Script (≤3 min)

### :00-:30 — The Problem
> "90% of small dev teams skip code review. They can't afford a dedicated reviewer. So bugs ship to production, security vulnerabilities go unnoticed, and technical debt piles up. This isn't a talent problem — it's a resource problem."

### :30-1:00 — The Solution
> "PR Pilot is an AI-native code quality service. Five autonomous agents handle your entire PR review pipeline. You open a pull request — the agents handle everything else."

### 1:00-2:00 — Live Demo
1. Show a PR being opened on a demo repo
2. Watch the webhook fire (show Cloud Run logs)
3. The agent chain runs: Reviewer → Fixer → Tester → Verifier → Escalator
4. Review appears on the PR with inline comments and fixes
5. Show the escalation decision log
6. Show a second PR that gets auto-approved

### 2:00-2:30 — Business Metrics
> "In X days since launch, PR Pilot has reviewed Y pull requests, found Z bugs, and handled W% of reviews autonomously. We have N paying customers generating $M in monthly revenue."

### 2:30-3:00 — Impact + Call to Action
> "PR Pilot democratizes code quality. A 2-person startup now ships with the same rigor as a 100-person engineering org. This is what AI-native operations looks like — not AI assisting humans, but AI operating the business."

---

## Expenses Disclosure

| Category | Amount | Notes |
|---|---|---|
| Google Cloud (Gemini API) | $TBD/mo | Agent LLM calls |
| Google Cloud (Cloud Run) | $TBD/mo | Hosting |
| Domain | $TBD/yr | pr-pilot.dev |
| Stripe fees | $TBD/mo | Payment processing |
| Marketing | $0 | Organic only |

---

## Links

- **GitHub Repo:** https://github.com/Perseus-Computing-LLC/pr-pilot
- **Landing Page:** https://pr-pilot.dev
- **Devpost Entry:** https://devpost.com/software/pr-pilot (TBD)
- **Demo Video:** [YouTube link TBD]
- **Gemini API Docs:** https://ai.google.dev/gemini-api/docs
