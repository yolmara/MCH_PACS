from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy



db = SQLAlchemy()

try:
    # example: db.session.add(new_scan)
    db.session.commit()
except Exception as e:
    db.session.rollback()
    print("DB Error:", e)
finally:
    db.session.close()
class Patient(db.Model):
    __tablename__ = 'patient'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(280), nullable=False)
    dob = db.Column(db.Date, nullable=True)
    national_id = db.Column(db.String, nullable=True, unique=True)
    sex = db.Column(db.String(20), nullable=True)
    external_id = db.Column(db.String(40), unique=True, nullable=True)  # renamed from patient_id
    records = db.relationship('Scan', backref='patient', lazy=True)

class Scan(db.Model):
    __tablename__ = 'scan'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey('patient.id'), nullable=True)
    file_name = db.Column(db.String(255), nullable=False)
    file_path = db.Column(db.String(255), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)
    description = db.Column(db.String(255), nullable=True)
    modality = db.Column(db.String(50))
    study_date = db.Column(db.String(20))
    patient_name = db.Column(db.String(100))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

class ActivityLog(db.Model):
    __tablename__ = 'activity'
    id = db.Column(db.Integer, primary_key=True)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(255))
    user = db.Column(db.String(100), default='Admin')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(200), nullable=False, unique=True)
    password = db.Column(db.String(255), nullable=False)  # hash this in practice
