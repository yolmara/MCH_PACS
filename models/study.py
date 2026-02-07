from models import db

class Study(db.Model):
    __tablename__ = 'studies'
    id = db.Column(db.Integer, primary_key=True)
    study_instance_uid = db.Column(db.String, unique=True, index=True)
    patient_id_fk = db.Column(db.Integer, db.ForeignKey('patients.id'))
    study_date = db.Column(db.String)
    description = db.Column(db.String)
    
    series = db.relationship("Series", backref="study", lazy=True)  