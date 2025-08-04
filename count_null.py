# count_nulls.py
import os
import sys

from config import Config

# Adjust these imports to match your project structure.
# If you use an app factory, import and call it; otherwise import the app instance directly.
try:
    from app import create_app, db
    app = create_app()
except ImportError:
    # Fallback if you have a global app instance instead of factory:
    from app import app, db  # adjust if your Flask instance is named differently

from sqlalchemy import func, text

from app import app, db
from app.models import Patient  # adjust if the Patient model lives elsewhere

with app.app_context():
    uri = app.config.get("SQLALCHEMY_DATABASE_URI")
    print("Using DB URI:", uri)

    # ORM count
    orm_count = db.session.query(func.count()).filter(Patient.mch_number == None).scalar()
    print("NULL mch_number count (ORM):", orm_count)

    # Raw SQL count
    raw_count = db.session.execute(text("SELECT COUNT(*) FROM patient WHERE mch_number IS NULL;")).scalar()
    print("NULL mch_number count (raw):", raw_count)

    if orm_count != raw_count:
        print("Warning: counts differ; investigate consistency.")
