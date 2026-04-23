# Database Column Issue Fix

## Problem
Production database missing subscription columns added to User model, causing login failures.

## Solution
- Added defer() options to all user SELECT queries in crud/user.py to exclude new columns until DB is migrated
- ALTER TABLE commands in app startup to add columns on deployment (fixed to run separately)
- Alembic configured for future migrations

## Stripe Configuration Issue
- Need to set STRIPE_SECRET_KEY environment variable in Render dashboard
- Map SECRET_KEY_STRIPE to STRIPE_SECRET_KEY
- Also set STRIPE_PUBLISHABLE_KEY and STRIPE_WEBHOOK_SECRET if using webhooks

## Next Steps
1. Commit and push the ALTER fix (separate statements)
2. In Render dashboard: Environment > Add env vars:
   - STRIPE_SECRET_KEY = [your SECRET_KEY_STRIPE value]
   - STRIPE_PUBLISHABLE_KEY = [your PUBLISHABLE_KEY value]
3. Redeploy - columns will be added, Stripe will be configured
4. Test payment flow