# Database Column Issue Fix

## Problem
Production database missing subscription columns added to User model, causing login failures.

## Solution
- Added defer() options to all user SELECT queries in crud/user.py to exclude new columns until DB is migrated
- ALTER TABLE commands in app startup to add columns on deployment
- Alembic configured for future migrations

## Next Steps
1. Commit and push the defer changes
2. Deploy on Render - login should work
3. ALTER will add columns during startup
4. Remove defer options after confirming columns exist