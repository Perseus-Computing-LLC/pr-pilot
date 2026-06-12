"""
PR Pilot - Main FastAPI application entrypoint.
Receives GitHub webhooks and triggers the 5-agent review chain.
"""

import json
from contextlib import asynccontextmanager
from pathlib import Path

import stripe
import structlog
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from src.config import HOST, PORT, STATE_DIR
from src.github_app.webhook import router as webhook_router
from src import stripe_handler

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown hooks."""
    logger.info("pr_pilot_starting", host=HOST, port=PORT)
    yield
    logger.info("pr_pilot_shutting_down")


app = FastAPI(
    title="PR Pilot",
    description="AI-native code quality service — 5-agent autonomous PR review pipeline",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(webhook_router)


@app.get("/")
async def root() -> dict:
    """Health check and basic info."""
    return {
        "service": "PR Pilot",
        "version": "0.1.0",
        "status": "running",
        "agents": ["reviewer", "fixer", "tester", "verifier", "escalator"],
    }


@app.get("/health")
async def health() -> dict:
    """Health check endpoint for Cloud Run / load balancers."""
    return {"status": "healthy"}


# ── Dashboard ────────────────────────────────────────────────────────

DASHBOARD_HTML = Path(__file__).parent / "dashboard.html"


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Serve the agent audit dashboard."""
    if DASHBOARD_HTML.exists():
        return DASHBOARD_HTML.read_text()
    return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)


@app.get("/dashboard/reviews")
async def dashboard_reviews():
    """API: list all review sessions from the state directory."""
    reviews = []
    if STATE_DIR.exists():
        for state_file in sorted(STATE_DIR.glob("*.json"), reverse=True):
            try:
                review = json.loads(state_file.read_text())
                reviews.append(review)
            except Exception:
                pass
    return {"reviews": reviews}


# ── Stripe Checkout ─────────────────────────────────────────────────

@app.post("/api/checkout")
async def create_checkout(request: Request) -> JSONResponse:
    """Create a Stripe Checkout session for a subscription plan."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    plan = body.get("plan", "team")
    email = body.get("email")

    try:
        session = stripe_handler.create_checkout_session(plan, email)
        return JSONResponse(session)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except stripe.error.StripeError as e:
        # Do not leak raw Stripe internals to callers.
        logger.error("stripe_checkout_error", error=str(e))
        raise HTTPException(status_code=502, detail="Payment provider error")
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/webhook/stripe")
async def stripe_webhook(request: Request, stripe_signature: str = Header(default="", alias="stripe-signature")):
    """Receive Stripe webhook events for subscription lifecycle."""
    payload = await request.body()

    try:
        result = stripe_handler.handle_webhook(payload, stripe_signature)
        return JSONResponse(result)
    except RuntimeError:
        raise HTTPException(status_code=500, detail="Stripe webhook not configured")
    except Exception as e:
        logger.error("stripe_webhook_error", error=str(e))
        raise HTTPException(status_code=400, detail="Webhook verification failed")
