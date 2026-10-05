"""WebhookEvent model for logging incoming payment provider webhook deliveries."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    provider: Mapped[str] = mapped_column(
        String(30), nullable=False, default="paystack",
        comment="Which provider sent this — 'paystack' for now"
    )
    event_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True,
        comment="e.g. 'charge.success' — null if the body couldn't be parsed"
    )
    reference: Mapped[str | None] = mapped_column(
        String(200), index=True, nullable=True,
        comment="The transaction reference from the event (indexed for lookup)"
    )
    signature: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="The x-paystack-signature header we received"
    )
    raw_body: Mapped[str] = mapped_column(
        Text, nullable=False,
        comment="The exact raw request body bytes, decoded to text — the audit record"
    )

    verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True if the HMAC signature verified as genuinely from the provider"
    )
    processed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False,
        comment="True if this event resulted in a recorded/handled payment"
    )
    processing_error: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Why the event was skipped or failed (duplicate, bad amount, etc.)"
    )

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self) -> str:
        return (
            f"<WebhookEvent(id={self.id}, provider='{self.provider}', "
            f"event_type='{self.event_type}', reference='{self.reference}', "
            f"verified={self.verified}, processed={self.processed})>"
        )
