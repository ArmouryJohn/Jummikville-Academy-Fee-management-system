"""
Models package — imports all models so SQLAlchemy can discover them.

WHY THIS FILE:
SQLAlchemy needs to "see" all your model classes before it can create
tables or run migrations. Importing them all here means you can just do:
    from app.models import School, Student, FeeType, FeeRecord, Payment
"""

from app.models.school import School
from app.models.student import Student
from app.models.fee_category import FeeCategory
from app.models.term import Term
from app.models.fee import FeeType, FeeRecord
from app.models.payment import Payment
from app.models.activity import ActivityLog
from app.models.user import User
from app.models.webhook_event import WebhookEvent
from app.models.expense import Expense
from app.models.payroll import Payroll
from app.models.staff import Staff
from app.models.staff_payroll import StaffPayrollRecord, StaffPayment

__all__ = [
    "School", "Student", "FeeCategory", "Term", "FeeType", "FeeRecord",
    "Payment", "ActivityLog", "User", "WebhookEvent", "Expense", "Payroll",
    "Staff", "StaffPayrollRecord", "StaffPayment"
]
