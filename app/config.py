"""
Application configuration — loads all settings from environment variables.

HOW THIS WORKS:
- Pydantic's BaseSettings reads from a .env file automatically
- Every setting has a type annotation, so you get errors early if something's missing
- To change any config (Twilio number, database, etc.), edit .env — not code

WHY THIS PATTERN:
- No secrets in source code
- One place to see every configurable value
- Different .env files for dev vs production
"""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """
    All application settings. Values come from environment variables or .env file.
    """

    # ---- Database ----
    database_url: str = Field(
        default="sqlite:///./jummikville.db",
        description="SQLAlchemy database connection string"
    )

    # ---- Paystack ----
    paystack_secret_key: str = Field(
        default="sk_test_placeholder",
        description="Paystack secret key (starts with sk_test_ for test mode)"
    )
    paystack_public_key: str = Field(
        default="pk_test_placeholder",
        description="Paystack public key (starts with pk_test_ for test mode)"
    )

    # ---- Twilio ----
    twilio_account_sid: str = Field(
        default="AC_placeholder",
        description="Twilio Account SID from the console dashboard"
    )
    twilio_auth_token: str = Field(
        default="placeholder",
        description="Twilio Auth Token from the console dashboard"
    )
    twilio_whatsapp_number: str = Field(
        default="+14155238886",
        description=(
            "The Twilio WhatsApp-enabled phone number (without 'whatsapp:' prefix). "
            "Currently the sandbox number. Change this ONE value when you get a "
            "verified WhatsApp Business number."
        )
    )

    # ---- Auth / sessions ----
    jwt_secret: str = Field(
        default="dev-only-insecure-secret-change-me",
        description=(
            "Secret key used to sign login session tokens (JWTs). "
            "MUST be set to a long random value in production via the JWT_SECRET "
            "env var — anyone who knows it can forge a login."
        ),
    )
    session_timeout_minutes: int = Field(
        default=30,
        description=(
            "How long a session stays valid without activity. Each authenticated "
            "request refreshes it, so this is an IDLE timeout, not a hard cap."
        ),
    )
    # First/seed admin account (Director) — created on startup only if absent.
    admin_email: str = Field(
        default="admin@jummikville.sch",
        description="Email for the seeded Director/admin account.",
    )
    admin_password: str | None = Field(
        default=None,
        description=(
            "Password for the seeded admin. If left unset, a random one is "
            "generated and printed to the startup log ONCE. Set ADMIN_PASSWORD "
            "in .env (or Render env vars) to choose your own."
        ),
    )

    # Optional second seed account (Bursar / staff_admin).
    # Set BURSAR_EMAIL + BURSAR_PASSWORD in Render or .env to auto-create it.
    bursar_email: str | None = Field(
        default=None,
        description=(
            "Email for an optional second seeded account (staff_admin role). "
            "Leave unset to skip seeding. Example: bursar@jummikville.sch"
        ),
    )
    bursar_password: str | None = Field(
        default=None,
        description=(
            "Password for the seeded bursar. If BURSAR_EMAIL is set but this is "
            "blank, a random password is generated and printed to the log once."
        ),
    )

    # ---- App ----
    app_env: str = Field(
        default="development",
        description="'development' or 'production'"
    )

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"

    @property
    def twilio_whatsapp_from(self) -> str:
        """
        Returns the full 'whatsapp:+xxxxx' sender ID that Twilio expects.
        """
        return f"whatsapp:{self.twilio_whatsapp_number}"

    model_config = {
        # Tell Pydantic to load from .env file
        "env_file": ".env",
        # Environment variable names are case-insensitive
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }


# Create a single settings instance that the whole app imports
# Usage: from app.config import settings
settings = Settings()
