# Jummikville Academy — Fee Management System

Automated school fee tracking, Paystack payment integration, and WhatsApp notifications for Jummikville Academy, Uyo. Powered by **CAR Hub**.

## What This System Does

- **Tracks fees per student** — Total owed, amount paid, and balance (always computed correctly)
- **Accepts online payments via Paystack** — Parents pay through a link sent to their WhatsApp
- **Records cash/POS payments** — Staff can record offline payments in one action
- **Sends WhatsApp confirmations** — Automatic thank-you message with updated balance after every payment
- **Sends WhatsApp reminders** — Warm, respectful reminders to parents with outstanding balances
- **Designed for multi-school** — Built to support multiple schools (one school for now)

## Tech Stack

| Technology          | Purpose             |
| ------------------- | ------------------- |
| Python 3.11+        | Language            |
| FastAPI             | Web framework & API |
| SQLAlchemy          | Database ORM        |
| SQLite / PostgreSQL | Database            |
| Paystack            | Online payments     |
| Twilio              | WhatsApp messaging  |

## Quick Start

### 1. Clone and set up

```bash
git clone <your-repo-url>
cd Jummikville-Management-System

# Create a virtual environment
python -m venv venv

# Activate it
# Windows:
venv\Scripts\activate
# Mac/Linux:
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure environment

```bash
# Copy the template
copy .env.example .env    # Windows
# cp .env.example .env    # Mac/Linux

# Edit .env and fill in your real values:
# - PAYSTACK_SECRET_KEY (from Paystack dashboard)
# - TWILIO_ACCOUNT_SID (from Twilio console)
# - TWILIO_AUTH_TOKEN (from Twilio console)
```

### 3. Seed the database

```bash
python seed.py
```

### 4. Run the server

```bash
uvicorn app.main:app --reload --port 8000
```

### 5. Explore the API

Open http://localhost:8000/docs in your browser — FastAPI generates interactive API documentation automatically.

## API Endpoints

### Students

| Method | Endpoint                  | Description      |
| ------ | ------------------------- | ---------------- |
| POST   | `/api/v1/students/`     | Create a student |
| GET    | `/api/v1/students/`     | List students    |
| GET    | `/api/v1/students/{id}` | Get a student    |
| PATCH  | `/api/v1/students/{id}` | Update a student |

### Fees

| Method | Endpoint                      | Description                     |
| ------ | ----------------------------- | ------------------------------- |
| POST   | `/api/v1/fees/types`        | Create a fee type               |
| GET    | `/api/v1/fees/types`        | List fee types                  |
| POST   | `/api/v1/fees/records`      | Assign fee to a student         |
| POST   | `/api/v1/fees/records/bulk` | Assign fee to multiple students |
| GET    | `/api/v1/fees/records`      | List fee records                |
| GET    | `/api/v1/fees/records/{id}` | Get a fee record                |

### Payments

| Method | Endpoint                        | Description                    |
| ------ | ------------------------------- | ------------------------------ |
| POST   | `/api/v1/payments/cash`       | Record cash/POS payment        |
| POST   | `/api/v1/payments/initialize` | Generate Paystack payment link |

### Webhooks

| Method | Endpoint                      | Description                  |
| ------ | ----------------------------- | ---------------------------- |
| POST   | `/api/v1/webhooks/paystack` | Paystack webhook (automated) |

### Reminders

| Method | Endpoint                   | Description        |
| ------ | -------------------------- | ------------------ |
| POST   | `/api/v1/reminders/send` | Send fee reminders |

## Testing Paystack Webhooks Locally

Paystack needs to reach your webhook endpoint over the internet. For local development, use [ngrok](https://ngrok.com/):

```bash
# Terminal 1: Run your app
uvicorn app.main:app --reload --port 8000

# Terminal 2: Expose to internet
ngrok http 8000
```

Copy the `https://xxxxx.ngrok.io` URL and set it as your webhook URL in the Paystack dashboard:

- URL: `https://xxxxx.ngrok.io/api/v1/webhooks/paystack`
- Events: `charge.success`

## Project Structure

```
├── app/
│   ├── main.py          # FastAPI app entry point
│   ├── config.py        # Environment-based configuration
│   ├── database.py      # SQLAlchemy engine & session
│   ├── models/          # Database table definitions
│   ├── schemas/         # Pydantic request/response validation
│   ├── routers/         # API endpoints
│   ├── services/        # Business logic (Paystack, Twilio, etc.)
│   └── utils/           # Helper functions
├── seed.py              # Initial data population
├── .env.example         # Environment variable template
├── requirements.txt     # Python dependencies
└── README.md            # You are here
```

## Security

- **No exposed API keys** — All secrets loaded from environment variables
- **Paystack webhook verification** — HMAC-SHA512 signature checking with timing-safe comparison
- **Idempotent webhooks** — Duplicate Paystack events are detected and ignored
- **Input validation** — All API inputs validated by Pydantic before reaching the database

## License

Built by CAR Hub for Jummikville Academy.
