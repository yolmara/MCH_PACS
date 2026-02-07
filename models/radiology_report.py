from models import db
from datetime import datetime

class RadiologyReport(db.Model):
    __tablename__ = 'radiology_reports'
    
    id = db.Column(db.Integer, primary_key=True)
    
    # Link to study
    study_id_fk = db.Column(db.Integer, db.ForeignKey('studies.id'))
    exam_order_id_fk = db.Column(db.Integer, db.ForeignKey('exam_orders.id'))
    
    # Radiologist info
    radiologist_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    radiologist_name = db.Column(db.String(200))
    
    # Report content
    findings = db.Column(db.Text)
    impression = db.Column(db.Text)
    recommendations = db.Column(db.Text)
    
    # Status
    status = db.Column(db.String(50), default='draft')  # draft, final, signed
    
    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finalized_at = db.Column(db.DateTime)
    signed_at = db.Column(db.DateTime)
    
    # Relationships
    study = db.relationship('Study', backref='reports')
    exam_order = db.relationship('ExamOrder', backref='report')
    radiologist = db.relationship('User', backref='written_reports')
    
    def __repr__(self):
        return f'<RadiologyReport for Study {self.study_id_fk}>'