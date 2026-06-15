"""
PR Pilot configuration — loaded from environment variables.
All agent and orchestration settings live here.
"""

import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── GitHub App ──────────────────────────────────────────────────────
GITHUB_APP_ID: str = os.getenv("GITHUB_APP_ID", "")
GITHUB_APP_PRIVATE_KEY: str = os.getenv("GITHUB_APP_PRIVATE_KEY", "")
GITHUB_WEBHOOK_SECRET: str = os.getenv("GITHUB_WEBHOOK_SECRET", "")
# Explicit, opt-in dev bypass for unsigned webhooks. Requires BOTH
# ALLOW_UNSIGNED_WEBHOOKS=true AND ENVIRONMENT=development to take effect.
# This prevents accidental activation in production.
ALLOW_UNSIGNED_WEBHOOKS: bool = (
    os.getenv("ALLOW_UNSIGNED_WEBHOOKS", "").lower() == "true"
    and os.getenv("ENVIRONMENT", "production").lower() == "development"
)

# Support private key as path or inline value
if GITHUB_APP_PRIVATE_KEY and os.path.isfile(GITHUB_APP_PRIVATE_KEY):
    GITHUB_APP_PRIVATE_KEY = Path(GITHUB_APP_PRIVATE_KEY).read_text()

# ── LLM Configuration ───────────────────────────────────────────────
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

# ── Server ──────────────────────────────────────────────────────────
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8080"))

# ── Dashboard ───────────────────────────────────────────────────────
# The dashboard exposes review session state (repo names, findings, patches).
# It is disabled unless an admin token is configured; when set, callers must
# present it as `Authorization: Bearer <token>`.
DASHBOARD_TOKEN: str = os.getenv("DASHBOARD_TOKEN", "")
# Comma-separated CORS allowlist for browser clients. Defaults to none (no
# cross-origin access); set explicit origins in production. Avoid "*".
CORS_ALLOW_ORIGINS: list[str] = [
    o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
]

# ── Agent Settings ──────────────────────────────────────────────────
MAX_AGENT_RETRIES: int = int(os.getenv("MAX_AGENT_RETRIES", "3"))
AGENT_TIMEOUT_SECONDS: int = int(os.getenv("AGENT_TIMEOUT_SECONDS", "300"))
# Overall timeout for the full 5-agent chain (seconds). The individual
# agent timeouts can stack up, so the chain timeout acts as a global
# upper bound on webhook-triggered background tasks. 0 = disabled.
CHAIN_TIMEOUT_SECONDS: int = int(os.getenv("CHAIN_TIMEOUT_SECONDS", "900"))
MAX_DIFF_SIZE_BYTES: int = int(os.getenv("MAX_DIFF_SIZE_BYTES", "500_000"))
# Warn when an accumulated agent prompt exceeds this byte count (the
# Escalator receives all four prior agent results and a large set of
# findings can push the combined payload toward token limits).
MAX_PROMPT_SIZE_WARN_BYTES: int = int(os.getenv("MAX_PROMPT_SIZE_WARN_BYTES", "500_000"))

# ── Review Safety ───────────────────────────────────────────────────
# The Verifier currently judges generated patches/tests with an LLM only; it
# does not apply patches, write tests, or run project commands in a sandbox.
# Until real verification exists, an "auto_approve" decision must NEVER be
# turned into a GitHub APPROVE. Setting this to true is reserved for when a
# sandboxed verification worker is implemented and producing real evidence.
VERIFIED_AUTO_APPROVE: bool = os.getenv("VERIFIED_AUTO_APPROVE", "").lower() == "true"

# ── Stripe ──────────────────────────────────────────────────────────
# Base URL used for success/cancel redirects after Stripe Checkout.
STRIPE_BASE_URL: str = os.getenv(
    "STRIPE_BASE_URL", "https://tcconnally.github.io/pr-pilot"
)

# ── Paths ───────────────────────────────────────────────────────────
PROJECT_ROOT: Path = Path(__file__).parent.parent
AGENT_LOG_DIR: Path = Path(os.getenv("AGENT_LOG_DIR", str(PROJECT_ROOT / "logs" / "agents")))
STATE_DIR: Path = Path(os.getenv("STATE_DIR", str(PROJECT_ROOT / "data" / "reviews")))

# ── State Management ─────────────────────────────────────────────────
# Maximum number of review state files to retain. Older files beyond this
# limit are deleted on each save. Set to 0 to disable cleanup.
MAX_REVIEW_STATES: int = int(os.getenv("MAX_REVIEW_STATES", "1000"))

# ── Review Rules ────────────────────────────────────────────────────
DEFAULT_REVIEW_RULES = {
    "security": True,
    "performance": True,
    "style": True,
    "testing": True,
    "error_handling": True,
}
