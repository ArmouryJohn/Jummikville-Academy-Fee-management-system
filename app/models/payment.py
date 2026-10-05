"""Payment model for recording student fee payments across all channels."""

from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Which fee record this payment applies to
    fee_record_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("fee_records.id"), nullable=False
    )

    # Payment details
    amount_kobo: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="Amount of this specific payment in kobo"
    )
    method: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="'paystack', 'cash', 'pos', 'bank_transfer', 'other'"
    )

    # Paystack-specific (null for cash/POS payments)
    paystack_reference: Mapped[str | None] = mapped_column(
        String(200), unique=True, nullable=True,
        comment="Paystack transaction reference"
    )

    # Staff-recorded payments (null for Paystack payments)
    recorded_by: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Label of who recorded a manual payment"
    )

    # Admin user who recorded manual payment (null for automated Paystack payments)
    recorded_by_user_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id"), nullable=True,
        comment="Admin user id who recorded manual payment"
    )

    # Receipt PDF — generated once, then this URL is stable for re-download.
    # Points at the protected route /api/v1/payments/{id}/receipt, not a static file.
    receipt_url: Mapped[str | None] = mapped_column(
        String(300), nullable=True,
        comment="URL of the generated receipt PDF (set once after the payment)"
    )

    # Optional note
    note: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Optional note, e.g. 'Paid at school office'"
    )

    # When the payment was actually made (might differ from created_at
    # if a cash payment is recorded the next day)
    paid_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc)
    )

    # ---------- Relationships ----------
    fee_record: Mapped["FeeRecord"] = relationship(  # noqa: F821
        back_populates="payments"
    )
    recorded_by_user: Mapped["User | None"] = relationship()  # noqa: F821

    def __repr__(self) -> str:
        return (
            f"<Payment(id={self.id}, amount={self.amount_kobo}, "
            f"method='{self.method}', ref='{self.paystack_reference}')>"
        )
