"""
Stripe integration for PR Pilot — checkout sessions and webhook handling.
"""

import os
import structlog

import stripe

logger = structlog.get_logger(__name__)

STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")

# Price IDs — create these in Stripe Dashboard and set the env vars. No
# defaults: a real Stripe price id always starts with "price_", and shipping a
# placeholder default would let invalid checkout sessions be attempted.
PRICE_IDS = {
    "starter": os.getenv("STRIPE_PRICE_STARTER", ""),
    "team": os.getenv("STRIPE_PRICE_TEAM", ""),
    "business": os.getenv("STRIPE_PRICE_BUSINESS", ""),
}

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY


def create_checkout_session(plan: str, customer_email: str | None = None) -> dict:
    """Create a Stripe Checkout session for a subscription plan.

    Args:
        plan: One of 'starter', 'team', 'business'
        customer_email: Optional pre-filled email

    Returns:
        Dict with 'url' (checkout URL) and 'session_id'
    """
    if not STRIPE_SECRET_KEY:
        raise RuntimeError("STRIPE_SECRET_KEY not configured")

    price_id = PRICE_IDS.get(plan)
    if not price_id or not price_id.startswith("price_"):
        raise ValueError(
            f"Price ID for '{plan}' is not a valid Stripe price id. "
            "Create products in Stripe Dashboard and set "
            "STRIPE_PRICE_STARTER/TEAM/BUSINESS to the 'price_...' values."
        )

    try:
        session = stripe.checkout.Session.create(
            mode="subscription",
            line_items=[{"price": price_id, "quantity": 1}],
            success_url="https://pr-pilot.dev/success?session_id={CHECKOUT_SESSION_ID}",
            cancel_url="https://pr-pilot.dev/pricing",
            customer_email=customer_email,
            allow_promotion_codes=True,
            billing_address_collection="auto",
            metadata={"plan": plan},
        )
        logger.info("checkout_session_created", plan=plan, session_id=session.id)
        return {"url": session.url, "session_id": session.id}

    except stripe.error.StripeError as e:
        logger.error("stripe_error", error=str(e))
        raise


def handle_webhook(payload: bytes, signature: str) -> dict:
    """Process a Stripe webhook event.

    Handles:
    - checkout.session.completed: Subscription started
    - customer.subscription.updated: Plan change
    - customer.subscription.deleted: Cancellation
    - invoice.paid: Payment confirmed
    - invoice.payment_failed: Payment issue

    Returns:
        Dict with event type and processing result
    """
    if not STRIPE_WEBHOOK_SECRET:
        raise RuntimeError("STRIPE_WEBHOOK_SECRET not configured")

    try:
        event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    except stripe.error.SignatureVerificationError:
        logger.error("webhook_signature_invalid")
        raise

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "checkout.session.completed":
        customer_id = data.get("customer")
        subscription_id = data.get("subscription")
        plan = data.get("metadata", {}).get("plan", "unknown")
        email = data.get("customer_details", {}).get("email", "unknown")
        logger.info(
            "subscription_started",
            customer=customer_id,
            subscription=subscription_id,
            plan=plan,
            email=email,
        )

    elif event_type == "customer.subscription.deleted":
        customer_id = data.get("customer")
        logger.info("subscription_cancelled", customer=customer_id)

    elif event_type == "invoice.paid":
        customer_id = data.get("customer")
        amount = data.get("amount_paid", 0) / 100
        logger.info("invoice_paid", customer=customer_id, amount=amount)

    elif event_type == "invoice.payment_failed":
        customer_id = data.get("customer")
        logger.warning("payment_failed", customer=customer_id)

    return {"status": "processed", "event": event_type}
