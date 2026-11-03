# Database Column Issue Fix

## Problem
Production database missing subscription columns added to User model, causing login failures.

## Solution
- Added defer() options to all user SELECT queries in crud/user.py to exclude new columns until DB is migrated
- ALTER TABLE commands in app startup to add columns on deployment (fixed to run separately)
- Alembic configured for future migrations

## Stripe Configuration Fixed
- Updated config.py to read SECRET_KEY_STRIPE and PUBLISHABLE_KEY from environment
- No need to change env vars on Render, they already exist

## Next Steps
1. Commit and push the config fix
2. Redeploy - Stripe should be configured, columns added
3. Test payment flow
4. Remove defer options from queries after confirming