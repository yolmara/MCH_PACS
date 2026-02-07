from models import db
from datetime import datetime

class ExamOrder(db.Model):
    __tablename__ = 'exam_orders'
    
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # Patient info
    patient_id_fk = db.Column(db.Integer, db.ForeignKey('patients.id'))
    
    # Ordering doctor
    ordering_doctor_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    ordering_doctor_name = db.Column(db.String(200))
    
    # Exam details
    exam_type = db.Column(db.String(100))  # CT, MRI, X-Ray, etc.
    body_part = db.Column(db.String(100))
    clinical_indication = db.Column(db.Text)  # Why the exam is needed
    priority = db.Column(db.String(20), default='routine')  # routine, urgent, stat
    
    # Workflow
    status = db.Column(db.String(50), default='pending')  # pending, scheduled, in_progress, completed, cancelled
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'))
    
    # Timestamps
    order_date = db.Column(db.DateTime, default=datetime.utcnow)
    scheduled_date = db.Column(db.DateTime)
    completed_date = db.Column(db.DateTime)
    
    # Relationships
    patient = db.relationship('Patient', backref='exam_orders')
    ordering_doctor = db.relationship('User', backref='ordered_exams')
    ward = db.relationship('Ward', backref='exam_orders')
    
    def __repr__(self):
        return f'<ExamOrder {self.order_number}>'