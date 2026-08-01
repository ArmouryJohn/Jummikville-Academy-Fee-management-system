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
from app.models.fee import FeeType, FeeRecord
from app.models.payment import Payment
from app.models.activity import ActivityLog
from app.models.user import User

__all__ = ["School", "Student", "FeeCategory", "FeeType", "FeeRecord", "Payment", "ActivityLog", "User"]
