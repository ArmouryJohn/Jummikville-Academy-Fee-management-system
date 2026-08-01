# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Setup
python -m venv venv
venv\Scripts\activate            # Windows (Mac/Linux: source venv/bin/activate)
pip install -r requirements.txt

# Seed the database once (creates school, fee categories, sample students/fees)
python seed.py

# Run the app (serves both the API and the frontend at http://localhost:8000)
uvicorn app.main:app --reload --port 8000

# Interactive API docs
# http://localhost:8000/docs
```

Testing: `test_api.py` and `test_whatsapp.py` are **smoke scripts run against a live server**, not pytest suites (despite `pytest` being in requirements). They use the `requests` library (not listed in requirements.txt — install separately) and hit a hardcoded `BASE` URL. `test_api.py` targets port **8001**, so start the server there first:

```bash
uvicorn app.main:app --port 8001
python test_api.py        # in another terminal
```

Note: `test_api.py` asserts against `/` returning JSON, but `/` now serves the frontend HTML — that test is stale.

## Architecture

FastAPI backend + a single-page vanilla-JS frontend, served from the **same origin** by one `uvicorn` process. The layered backend flow is: `routers/` (HTTP) → `services/` (business logic) → `models/` (SQLAlchemy tables), with `schemas/` (Pydantic) validating request/response at the router boundary.

### Money is always integer kobo
Every monetary value is stored as an integer in **kobo** (₦1 = 100 kobo) to avoid float rounding errors. Only convert to Naira for display via `kobo_to_naira()` in [app/utils/formatting.py](app/utils/formatting.py). Never store or compute money as a float.

### FeeType vs FeeRecord (see [app/models/fee.py](app/models/fee.py))
- **FeeType** = the catalog entry: `category + section (Nursery/Primary/Secondary) + term + amount_kobo`. Section is part of the key so the same category can cost different amounts per section in the same term. `FeeType.name` is a computed property that returns the linked `FeeCategory.name` — there is one source of truth for the name.
- **FeeRecord** = one student's progress against one FeeType: `total_fees_kobo`, `amount_paid_kobo`, `status`.
- **`balance_kobo` is ALWAYS computed** (`total - paid`), never a stored column, so it can't drift. Use `remaining_kobo` / `overpaid_kobo` for the non-negative split.
- A **SQLAlchemy event listener** (`_auto_recalculate_status`) auto-updates `status` (`unpaid`/`partial`/`paid`/`overpaid`) whenever `amount_paid_kobo` changes. Do **not** re-set `amount_paid_kobo` inside that listener (infinite recursion).

### One payment pipeline for every method
All payments — Paystack, cash, POS, transfer — flow through `record_payment()` in [app/services/payment_service.py](app/services/payment_service.py). It records the payment, bumps `amount_paid_kobo`, logs an activity entry (same transaction), commits, then sends the WhatsApp confirmation. Fix or extend payment behavior **here** and it applies to all methods. WhatsApp failures are caught and logged — they never fail the payment.

### Paystack (see [app/services/paystack.py](app/services/paystack.py), [app/routers/webhooks.py](app/routers/webhooks.py))
- The reference format `JMK-{fee_record_id}-{timestamp}` encodes which fee record a webhook applies to. `generate_reference()` writes it; `parse_fee_record_id_from_reference()` reads it back.
- Webhook signature is verified with **HMAC-SHA512** against the **raw request body bytes** (read before JSON parsing — re-serialization would break the hash) using `hmac.compare_digest` (timing-safe).
- **Idempotency**: `record_payment` skips any payment whose `paystack_reference` already exists, so webhook retries never double-credit.
- Local webhook testing needs a public URL — use `ngrok http 8000` and point the Paystack dashboard at `https://xxxxx.ngrok.io/api/v1/webhooks/paystack`.

### Auth (see [app/services/auth_deps.py](app/services/auth_deps.py), [app/services/security.py](app/services/security.py))
- JWT stored in an **httpOnly cookie** (`jummikville_session`) — JS can't read it (XSS protection). Passwords hashed with **PBKDF2-SHA256** from stdlib `hashlib` (no bcrypt/passlib build dependency).
- **Sliding session**: `get_current_user` re-issues the cookie with a fresh expiry on every request, so `session_timeout_minutes` (default 30) is an *idle* timeout.
- Routers are protected **at registration** in [app/main.py](app/main.py): protected routers get `dependencies=[Depends(get_current_user)]` when included, so new endpoints on those routers are guarded automatically. `auth` and `webhooks` are the only public routers (webhooks are secured by signature instead).

### Startup seeding (in [app/main.py](app/main.py) `on_startup`)
On every startup the app runs `Base.metadata.create_all` (creates missing tables only), then `_seed_admin_user` and `_seed_fee_categories`. Both are **idempotent and additive** — they only create what's missing and never overwrite existing rows (a changed password or renamed category is left alone). If `ADMIN_PASSWORD` is unset, a random admin password is generated and printed to the startup log **once**.

### Frontend ([frontend/](frontend/))
No build step. `index.html` + `app.js` load Tailwind, Alpine.js, and Chart.js from CDNs. **`app.js` must load before Alpine's CDN script** — Alpine fires `alpine:init` on load and app.js registers screens/store on that event; reversing the order yields a blank page. The frontend is mounted last in `main.py` as `StaticFiles` at `/` (must stay last so it doesn't shadow API routes).

### Multi-school design
Models carry a `school_id` and the code is written for multiple schools, but the system currently runs one school identified by the slug `jummikville`.

## Configuration
All settings load from `.env` via `pydantic-settings` ([app/config.py](app/config.py)). Copy `.env.example` to `.env`. `APP_ENV=production` flips `is_production`, which disables SQL echo, sets the secure cookie flag, tightens CORS, and requires a real `JWT_SECRET`. Default DB is SQLite (`jummikville.db`); switch to PostgreSQL by changing `DATABASE_URL` only. Schema changes beyond additive table creation should use Alembic (already a dependency).
