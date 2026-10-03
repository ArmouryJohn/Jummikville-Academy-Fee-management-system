import pytest
from unittest.mock import AsyncMock, patch

from app.schemas.payment import PaymentInitialize
from app.routers.payments import initialize_payment


@pytest.mark.asyncio
async def test_initialize_payment_without_parent_email(db, student, fee_record):
    """Staff can generate Paystack payment link even if parent has no email."""
    # Ensure student has no parent email
    student.parent_email = None
    db.commit()

    init_data = PaymentInitialize(fee_record_id=fee_record.id)

    mock_paystack_response = {
        "authorization_url": "https://checkout.paystack.com/test-ref",
        "access_code": "code123",
        "reference": "ref123",
    }

    with patch("app.routers.payments.initialize_transaction", new_callable=AsyncMock) as mock_init:
        mock_init.return_value = mock_paystack_response

        res = await initialize_payment(data=init_data, db=db)

        assert res.authorization_url == "https://checkout.paystack.com/test-ref"
        mock_init.assert_called_once()
        called_kwargs = mock_init.call_args.kwargs
        # Verify an automatic valid .com email was generated
        assert called_kwargs["email"] == f"parent.{student.id}@jummikville.com"
        assert "@" in called_kwargs["email"]
        assert called_kwargs["amount_kobo"] == fee_record.balance_kobo


@pytest.mark.asyncio
async def test_initialize_payment_with_existing_parent_email(db, student, fee_record):
    """When parent email is provided, that email is used."""
    student.parent_email = "realparent@example.com"
    db.commit()

    init_data = PaymentInitialize(fee_record_id=fee_record.id)

    mock_paystack_response = {
        "authorization_url": "https://checkout.paystack.com/test-ref",
        "access_code": "code123",
        "reference": "ref123",
    }

    with patch("app.routers.payments.initialize_transaction", new_callable=AsyncMock) as mock_init:
        mock_init.return_value = mock_paystack_response

        res = await initialize_payment(data=init_data, db=db)

        assert res.authorization_url == "https://checkout.paystack.com/test-ref"
        called_kwargs = mock_init.call_args.kwargs
        assert called_kwargs["email"] == "realparent@example.com"
