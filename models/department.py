from models import db

class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    department_code = db.Column(db.String(20), unique=True, nullable=False)
    department_name = db.Column(db.String(100), unique=True, nullable=False)
    description = db.Column(db.Text)
    
    wards = db.relationship('Ward', backref='department', lazy=True)
    