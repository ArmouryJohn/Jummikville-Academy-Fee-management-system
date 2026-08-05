# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A school fee-management system for Jummikville Academy: FastAPI backend + a build-less
Alpine.js/Tailwind frontend, with Paystack online payments and Twilio WhatsApp
notifications. Money is tracked per student; parents pay via Paystack links (sent over
WhatsApp) or staff record cash/POS/bank-transfer payments in-app. Every payment
produces a stored PDF receipt and is attributable to the admin who recorded it.

## Commands

```bash
# Setup
python -m venv venv && venv\Scripts\activate        # Windows (source venv/bin/activate on Unix)
pip install -r requirements.txt
copy .env.example .env                               # then fill in real secrets

# Seed demo data (schools, students, fee types/records) into jummikville.db
python seed.py

# Real unit tests — in-memory SQLite, no server, network stubbed. This is the
# suite to run on any code change (fast, hermetic).
python -m pytest tests/ -q

# One-time reconcile for a PRE-EXISTING jummikville.db (adds the webhook_events
# table + new Payment columns, and back-fills a Payment for any drift between the
# old stored amount_paid_kobo and the actual Payment rows). Idempotent. Fresh
# installs don't need this — tables auto-create on startup.
python migrate_derive_payments.py

# Run (serves BOTH the API and the frontend at http://localhost:8000/)
uvicorn app.main:app --reload --port 8000
#   /docs  → Swagger UI      /api → API info      /health → health check

# Smoke tests — require a RUNNING server. Note: test_api.py hits port 8001, so run
# the server on 8001 first (uvicorn ... --port 8001). Needs `requests` (pip install requests).
python test_api.py            # end-to-end API checks against a live server
python test_whatsapp.py       # Twilio WhatsApp send check

# Expose the webhook to the internet for local Paystack testing
ngrok http 8000               # set <ngrok-url>/api/v1/webhooks/paystack in the Paystack dashboard
```

There is no lint/format tooling configured. `tests/` holds real pytest unit tests
(in-memory SQLite, network stubbed) — run these on any change. The legacy top-level
`test_api.py` / `test_whatsapp.py` are separate standalone scripts that talk to a live
server, not part of the pytest suite.

## Architecture — the load-bearing rules

**Money is always integer kobo, never floats.** ₦75,000 is stored as `7500000`. This
avoids rounding errors on balances. Convert for display only, via
`app/utils/formatting.py:kobo_to_naira`.

**Balance and paid-amount are computed, never stored.** `FeeRecord.amount_paid_kobo` is a
Python property equal to `sum(p.amount_kobo for p in self.payments)` — the Payment rows are
the single source of truth for money received, so the record can never drift from its
payments. `balance_kobo` / `remaining_kobo` / `overpaid_kobo` derive from
`total_fees_kobo - amount_paid_kobo`. **Never add a `balance` or `amount_paid` column, and
never increment paid by hand** — record a Payment instead. The `status` string
('unpaid'/'partial'/'paid'/'overpaid') *is* stored (for fast queries) and is the one
denormalised field; it has a single writer, `FeeRecord.recalculate_status()`, which
`record_payment` calls after appending a Payment. Do not set `status` by hand. (There is no
longer a SQLAlchemy event listener on the paid amount — it was removed when paid became a
property.)

**All payments flow through one function.** Cash, POS, bank transfer, and Paystack all call
`app/services/payment_service.py:record_payment`. It appends a `Payment` row (which is what
moves the balance), calls `recalculate_status()`, writes an activity-log entry in the *same*
transaction, then best-effort generates the receipt PDF and fires the WhatsApp confirmation
(both best-effort — a receipt or WhatsApp failure never fails the payment). It records
`recorded_by_user_id` (the acting admin) for the audit trail. Add cross-cutting payment
behavior here, not in individual routers.

**Fees are two tables, one concept** (`app/models/fee.py`): `FeeType` is the school-wide
catalog entry (category + section + term + default amount); `FeeRecord` is one student's
instance of a fee type (what they owe/paid). `FeeType.name` is a property delegating to
its `FeeCategory` — categories are the permanent source of truth for fee names.

### Paystack payment flow

1. `POST /api/v1/payments/initialize` → `paystack.initialize_transaction` returns an
   `authorization_url` (the payment link). The reference is minted by
   `paystack.generate_reference` as **`JMK-{fee_record_id}-{timestamp}`** — the
   `fee_record_id` is encoded *into the reference* so the webhook can route the payment.
2. Parent pays; Paystack POSTs to `POST /api/v1/webhooks/paystack`
   (`app/routers/webhooks.py`).
3. The webhook (a) reads **raw bytes** and verifies an **HMAC-SHA512 signature over the raw
   request body** (must happen before JSON parsing — re-serialized JSON breaks the hash;
   403 on failure, before any DB write), (b) persists the raw delivery as a `WebhookEvent`
   row (`app/models/webhook_event.py`) for audit — every delivery is stored, even ones it
   skips, with `verified`/`processed` flags and a `processing_error`, (c) parses the
   `fee_record_id` back out of the reference, then (d) **server-to-server re-verifies the
   transaction** via `paystack.verify_transaction` and credits the **Paystack-verified
   amount**, never the amount claimed in the webhook body (closes a tamper vector), and
   calls `record_payment`.
4. **Idempotency**: duplicate webhooks/retries are ignored via the unique
   `paystack_reference` on Payment (`check_duplicate_reference`).

`app/services/paystack.py` is the most security-critical file — treat signature
verification and the reference format as a contract between initialize and webhook.

### Receipts

Every payment gets a one-page PDF receipt via `app/services/receipt_service.py`
(**fpdf2**). Generation is idempotent — one file per payment, reused if it already exists —
and best-effort (a failure never fails the payment). Files are written to repo-root
`storage/receipts/receipt-{payment_id}.pdf`, **deliberately outside `frontend/`** so they
are never served as public static files; downloads go through the auth-protected
`GET /api/v1/payments/{payment_id}/receipt` route (regenerates on demand if missing). The
payment stores `receipt_url` pointing at that route, not a filesystem path. `storage/` is
gitignored. Note: fpdf2's built-in Helvetica is latin-1 and cannot render `₦`, so receipts
print money as `NGN 75,000.00`; the rest of the app still uses `₦`.

### Term rollover

Starting a new term is **explicit and human-triggered only** — there is no auto-rollover.
`POST /api/v1/fees/terms/rollover` (`app/services/term_service.py`) clones the `FeeType`
catalog from `from_term` into `to_term`, creates fresh `FeeRecord`s for active students,
and — when `carry_forward` is set — carries each student's **unpaid remainder** forward as a
single "Outstanding (Prior Term)" arrears record. The paid portion stays in the prior term:
**prior-term records are never mutated.** The operation is idempotent — students who already
have `to_term` records are skipped — so a double-trigger changes nothing.

### Auth

Cookie-based sessions, not bearer tokens. Login sets an **httpOnly** cookie
(`jummikville_session`) holding a JWT; `app/services/auth_deps.py:get_current_user`
verifies it and **re-issues it on every request** (sliding idle timeout, default 30 min).
Routers are protected wholesale in `app/main.py` by attaching
`dependencies=[Depends(get_current_user)]` at `include_router` time — so a new protected
endpoint is guarded automatically by being in an already-guarded router. Only `auth` and
`webhooks` are mounted public (webhooks is secured by signature instead).

### App wiring & startup

`app/main.py` is the entry point. On startup it: creates all tables via
`Base.metadata.create_all` (no Alembic migrations run despite alembic being installed —
`create_all` adds *new* tables like `webhook_events` but never alters existing ones, so
adding a column to an existing table on a live DB needs manual handling — see
`migrate_derive_payments.py`), seeds the admin user, and seeds the 8 default fee categories.
**The seed admin password is printed to the startup log once** if `ADMIN_PASSWORD` is unset
— grab it from there. The frontend static folder is mounted at `/` **last**, so it must not
shadow the API routes above it (all API routes live under `/api/v1/...`).

Layering: `routers/` (HTTP + validation via `schemas/`) → `services/` (business logic:
paystack, payment, receipt, term, reminder, twilio_wa, auth) → `models/` (SQLAlchemy). Every
request gets its own DB session via the `get_db` dependency in `app/database.py`.

### Frontend

`frontend/` is a **single static folder, no build step** — `index.html` (Tailwind via CDN
+ Alpine.js) and `app.js`. It's served same-origin by the backend, so API calls use the
relative `/api/v1` base and the session cookie rides along automatically; no CORS in prod.
`app.js` hardcodes `CONFIG.SCHOOL_ID = 1` — the backend is multi-school but this UI drives
one school. All text/currency is UTF-8 (the `₦` sign appears literally); if you edit these
files, preserve UTF-8 encoding — a prior cp1252 mojibake corruption had to be repaired.

## Conventions

- Config is env-only via `app/config.py` (pydantic-settings, reads `.env`). Add new
  settings there; never hardcode secrets. `settings.is_production` (from `APP_ENV`) gates
  cookie `secure`, CORS, and SQL echo.
- Nigerian phone numbers are normalized to E.164 (`+234...`) by
  `formatting.normalize_phone` before use with Twilio.
- Default DB is SQLite (`jummikville.db`); switch to PostgreSQL by changing `DATABASE_URL`
  only (`app/database.py` conditionally applies the SQLite `check_same_thread` arg).
