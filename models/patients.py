from models import db

class Patient(db.Model):
    __tablename__ = 'patients'
    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.String, unique=True, index=True)
    patient_name = db.Column(db.String)
    patient_sex = db.Column(db.String(10))
    patient_dob = db.Column(db.String(20))
    
    ward_id = db.Column(db.Integer, db.ForeignKey('wards.id'))
    
    studies = db.relationship("Study", backref="patient", lazy=True)