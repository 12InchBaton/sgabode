"""Stripe payment endpoints for boosted listings."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from database import get_db
from models import Listing, ListingPayment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


class PaymentIntentRequest(BaseModel):
    listing_id: int
    agent_id: int


@router.post("/create-intent")
async def create_payment_intent(
    payload: PaymentIntentRequest, db: AsyncSession = Depends(get_db)
):
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=503, detail="Payments not configured")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    result = await db.execute(select(Listing).where(Listing.id == payload.listing_id))
    listing = result.scalar_one_or_none()
    if not listing:
        raise HTTPException(status_code=404, detail="Listing not found")

    intent = stripe.PaymentIntent.create(
        amount=settings.LISTING_BOOST_PRICE,
        currency="sgd",
        metadata={
            "listing_id": payload.listing_id,
            "agent_id": payload.agent_id,
        },
    )

    payment = ListingPayment(
        listing_id=payload.listing_id,
        agent_id=payload.agent_id,
        stripe_payment_id=intent["id"],
        amount=settings.LISTING_BOOST_PRICE / 100,
        status="pending",
    )
    db.add(payment)
    await db.commit()

    return {"client_secret": intent["client_secret"], "payment_intent_id": intent["id"]}


@router.post("/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Webhook not configured")

    import stripe
    stripe.api_key = settings.STRIPE_SECRET_KEY

    body = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            body, stripe_signature, settings.STRIPE_WEBHOOK_SECRET
        )
    except stripe.error.SignatureVerificationError:
        raise HTTPException(status_code=400, detail="Invalid signature")

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        payment_id = pi["id"]
        listing_id = int(pi["metadata"].get("listing_id", 0))

        # Update payment record
        result = await db.execute(
            select(ListingPayment).where(ListingPayment.stripe_payment_id == payment_id)
        )
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = "paid"
            payment.paid_at = datetime.now(timezone.utc)

        # Mark listing as paid/verified
        if listing_id:
            result = await db.execute(select(Listing).where(Listing.id == listing_id))
            listing = result.scalar_one_or_none()
            if listing:
                listing.is_paid = True
                listing.verified = True

        await db.commit()

    elif event["type"] == "payment_intent.payment_failed":
        pi = event["data"]["object"]
        result = await db.execute(
            select(ListingPayment).where(ListingPayment.stripe_payment_id == pi["id"])
        )
        payment = result.scalar_one_or_none()
        if payment:
            payment.status = "failed"
            await db.commit()

    return {"received": True}
