from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.db.session import get_db
from app.routers.deps import get_current_user
from app.models.user import User
from app.core.config import settings
import stripe

router = APIRouter(prefix="/payment", tags=["payment"])

@router.post("/create-checkout-session")
async def create_checkout_session(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a Stripe Checkout session for subscription."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        # Create or retrieve Stripe customer
        if current_user.stripe_customer_id:
            customer = stripe.Customer.retrieve(current_user.stripe_customer_id)
        else:
            customer = stripe.Customer.create(
                email=current_user.email,
                name=current_user.name,
            )
            current_user.stripe_customer_id = customer.id
            db.add(current_user)
            await db.commit()

        # Create checkout session for Pro plan ($19/month)
        checkout_session = stripe.checkout.Session.create(
            customer=customer.id,
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Pro Plan',
                        'description': 'Unlimited AI Optimization, Priority Job Matching, Career Coaching Access, Custom Cover Letters, Interview Simulator',
                    },
                    'unit_amount': 1900,  # $19.00 in cents
                    'recurring': {
                        'interval': 'month',
                    },
                },
                'quantity': 1,
            }],
            mode='subscription',
            success_url=f"{settings.FRONTEND_URL}/payment/success?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=f"{settings.FRONTEND_URL}/pricing",
        )

        return {"checkout_url": checkout_session.url}

    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/webhook")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events."""
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(status_code=500, detail="Stripe not configured")
    
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=500, detail="Stripe Webhook not configured")
    
    stripe.api_key = settings.STRIPE_SECRET_KEY
    
    payload = await request.body()
    sig_header = request.headers.get('stripe-signature')

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except stripe.error.SignatureVerificationError as e:
        raise HTTPException(status_code=400, detail="Invalid signature")

    # Handle the event
    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        customer_id = session['customer']
        subscription_id = session['subscription']

        # Update user subscription
        user = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user.scalar_one_or_none()
        if user:
            user.subscription_plan = "pro"
            user.subscription_status = "active"
            user.subscription_id = subscription_id
            db.add(user)
            await db.commit()

    elif event['type'] == 'invoice.payment_succeeded':
        # Subscription renewed
        pass

    elif event['type'] == 'invoice.payment_failed':
        # Payment failed, subscription might be past_due
        invoice = event['data']['object']
        customer_id = invoice['customer']
        user = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user.scalar_one_or_none()
        if user:
            user.subscription_status = "past_due"
            db.add(user)
            await db.commit()

    elif event['type'] == 'customer.subscription.deleted':
        # Subscription canceled
        subscription = event['data']['object']
        customer_id = subscription['customer']
        user = await db.execute(
            select(User).where(User.stripe_customer_id == customer_id)
        )
        user = user.scalar_one_or_none()
        if user:
            user.subscription_plan = "free"
            user.subscription_status = "inactive"
            db.add(user)
            await db.commit()

    return {"status": "success"}