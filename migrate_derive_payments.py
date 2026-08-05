"""
One-time migration for the "derive amount_paid_kobo from payments" change.

RUN ONCE, with the server stopped, after pulling this code:
    python migrate_derive_payments.py

BACKGROUND — WHAT CHANGED IN THE CODE:
  Before: fee_records.amount_paid_kobo was a STORED column, hand-incremented on
          every payment. It could drift from the actual Payment rows.
  After:  FeeRecord.amount_paid_kobo is a COMPUTED property = SUM(payments.amount_kobo)
          for that record. The column is gone.

WHAT THIS SCRIPT DOES:
  1. create_all() — creates the new webhook_events table. NOTE: create_all only
     creates MISSING TABLES; it never alters an existing table, so the new nullable
     columns on the already-existing payments table (recorded_by_user_id,
     receipt_url) must be added explicitly with ALTER TABLE — this script does that
     via _ensure_payment_columns().
  2. RECONCILE existing data: for every fee record, compare the OLD stored
     amount_paid_kobo against the SUM of its real Payment rows. If the stored
     value is HIGHER (money was recorded by bumping the column without a matching
     Payment row — e.g. the old seed script, or a pre-fix cash payment), insert a
     single back-fill Payment for the difference so the derived sum matches what
     the record used to show. No money is invented and none is lost.
  3. Recompute and store the denormalised `status` from the reconciled amounts.

IDEMPOTENT: a second run finds no drift (every record's payments already sum to
its old value) and inserts nothing.

SAFETY: reads the OLD column via raw SQL (the ORM no longer maps it). If the
column is already gone (fresh DB created after the change), there's nothing to
reconcile and the script simply ensures the schema and exits.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import text, inspect

from app.database import SessionLocal, engine, Base
from app.models import FeeRecord, Payment
from app.models.fee import _status_for

logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")
logger = logging.getLogger("migrate_derive_payments")


def _old_paid_column_exists() -> bool:
    """True if fee_records still has the legacy amount_paid_kobo COLUMN."""
    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("fee_records")}
    return "amount_paid_kobo" in cols


def _ensure_payment_columns() -> None:
    """
    Add the new nullable columns to the EXISTING payments table.

    create_all() will not do this — it only creates missing tables, never alters
    an existing one. Without these, any query that touches the payments table
    (including the derived FeeRecord.amount_paid_kobo) fails with
    'no such column: payments.recorded_by_user_id'. Idempotent: skips columns that
    already exist. ADD COLUMN is a cheap metadata-only change on SQLite.
    """
    inspector = inspect(engine)
    existing = {c["name"] for c in inspector.get_columns("payments")}
    wanted = {
        "recorded_by_user_id": "INTEGER REFERENCES users(id)",
        "receipt_url": "VARCHAR(300)",
    }
    added = []
    with engine.begin() as conn:
        for name, ddl in wanted.items():
            if name not in existing:
                conn.execute(text(f"ALTER TABLE payments ADD COLUMN {name} {ddl}"))
                added.append(name)
    if added:
        logger.info(f"Added missing payments columns: {', '.join(added)}")
    else:
        logger.info("payments table already has recorded_by_user_id + receipt_url.")


def _drop_legacy_paid_column() -> None:
    """
    Physically remove the dead fee_records.amount_paid_kobo column.

    It was NOT NULL with no default. Now that the code never supplies a value
    (amount_paid_kobo is a computed property = SUM of payments), every INSERT
    into fee_records — e.g. assigning a fee to a student — fails with
    'NOT NULL constraint failed: fee_records.amount_paid_kobo' while the column
    exists. SQLite >= 3.35 supports ALTER TABLE ... DROP COLUMN. Idempotent:
    does nothing if the column is already gone.
    """
    if not _old_paid_column_exists():
        logger.info("fee_records.amount_paid_kobo already dropped — nothing to do.")
        return
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE fee_records DROP COLUMN amount_paid_kobo"))
    logger.info("Dropped dead column fee_records.amount_paid_kobo.")


def migrate():
    # ---- 1. Ensure new tables/columns exist ----
    logger.info("Ensuring schema (new webhook_events table + payment columns)...")
    Base.metadata.create_all(bind=engine)
    _ensure_payment_columns()

    if not _old_paid_column_exists():
        logger.info(
            "No legacy amount_paid_kobo column found — schema is already on the "
            "derived model. Nothing to reconcile."
        )
        return

    db = SessionLocal()
    try:
        # ---- 2. Read the OLD stored paid values via raw SQL ----
        # The ORM no longer maps this column, so query it directly.
        rows = db.execute(
            text("SELECT id, total_fees_kobo, amount_paid_kobo FROM fee_records")
        ).fetchall()

        reconciled = 0
        backfilled_kobo = 0
        for row in rows:
            record_id, total_kobo, old_paid_kobo = row
            old_paid_kobo = old_paid_kobo or 0

            # What the real Payment rows currently sum to for this record.
            payments_sum = (
                db.query(Payment)
                .filter(Payment.fee_record_id == record_id)
                .with_entities(Payment.amount_kobo)
                .all()
            )
            current_sum = sum(a for (a,) in payments_sum)

            drift = old_paid_kobo - current_sum
            if drift > 0:
                # The stored column claimed more paid than the Payment rows show.
                # Insert ONE reconciling payment so the derived sum matches history.
                db.add(
                    Payment(
                        fee_record_id=record_id,
                        amount_kobo=drift,
                        method="other",
                        recorded_by="Migration reconcile",
                        note=(
                            "Back-filled during migrate_derive_payments to match the "
                            "pre-migration stored balance."
                        ),
                        paid_at=datetime.now(timezone.utc),
                    )
                )
                reconciled += 1
                backfilled_kobo += drift
                logger.info(
                    f"  fee_record {record_id}: stored={old_paid_kobo}, "
                    f"payments={current_sum} → back-filled {drift} kobo"
                )
            elif drift < 0:
                # Payments already exceed the old stored value — unusual, but the
                # payments are the source of truth, so we leave them and just warn.
                logger.warning(
                    f"  fee_record {record_id}: payments ({current_sum}) exceed old "
                    f"stored value ({old_paid_kobo}) — keeping payments, no change."
                )

        db.commit()

        # ---- 3. Recompute the stored status from reconciled amounts ----
        # Re-read paid as the (now-correct) sum of payments per record.
        records = db.query(FeeRecord).all()
        status_fixed = 0
        for r in records:
            new_status = _status_for(r.amount_paid_kobo, r.total_fees_kobo)
            if r.status != new_status:
                r.status = new_status
                status_fixed += 1
        db.commit()

        logger.info("")
        logger.info("Reconciliation complete:")
        logger.info(f"  Records back-filled:   {reconciled}")
        logger.info(f"  Total back-filled:     {backfilled_kobo} kobo")
        logger.info(f"  Statuses corrected:    {status_fixed}")

        # ---- 4. Drop the now-dead legacy column ----
        # This MUST happen, not just be "left in place": the column is NOT NULL
        # with no default, and the new code no longer supplies a value for it, so
        # every INSERT into fee_records (e.g. assigning a fee) would fail with
        # 'NOT NULL constraint failed: fee_records.amount_paid_kobo' while it
        # exists. amount_paid_kobo is now a computed property (sum of payments).
        _drop_legacy_paid_column()

    except Exception as e:
        db.rollback()
        logger.error(f"Migration failed: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    migrate()
