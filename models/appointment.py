from datetime import datetime
from models import db


class Appointment(db.Model):
    __tablename__ = "appointments"

    id = db.Column(db.Integer, primary_key=True)

    patient_id_fk = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=False, index=True)
    order_id_fk = db.Column(db.Integer, db.ForeignKey("exam_orders.id"), nullable=True, index=True)

    modality = db.Column(db.String(20), nullable=False, index=True)
    resource_name = db.Column(db.String(120), nullable=False, index=True)  # scanner/room

    scheduled_start = db.Column(db.DateTime, nullable=False, index=True)
    scheduled_end = db.Column(db.DateTime, nullable=False, index=True)

    status = db.Column(db.String(30), nullable=False, default="scheduled", index=True)
    notes = db.Column(db.Text)

    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    patient = db.relationship("Patient", backref="appointments")
    order = db.relationship("ExamOrder", backref="appointments")
    created_by = db.relationship("User", backref="created_appointments")

    def __repr__(self):
        return f"<Appointment {self.id} {self.modality} {self.status}>"
