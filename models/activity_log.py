from models import db
from datetime import datetime

class ActivityLog(db.Model):
    __tablename__ = 'activity_logs'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    username = db.Column(db.String(200))
    action = db.Column(db.String(100))  # e.g., "login", "upload", "view_study"
    resource = db.Column(db.String(200))  # e.g., "patient_123", "study_xyz"
    details = db.Column(db.Text)  # Additional JSON or text details
    ip_address = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    
    user = db.relationship('User', backref='activity_logs')
    
    def __repr__(self):
        return f'<ActivityLog {self.username} - {self.action}>'