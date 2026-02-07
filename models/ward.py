from models import db

class Ward(db.Model):
    __tablename__ = "wards"
    id = db.Column(db.Integer, primary_key=True)
    ward_code = db.Column(db.String(10), nullable=False)
    ward_name = db.Column(db.String(100), unique=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'))
    
    patients = db.relationship("Patient", backref="ward", lazy=True)
