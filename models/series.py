from models import db

class Series(db.Model):
    __tablename__ = 'series'
    id = db.Column(db.Integer, primary_key=True)
    series_instance_uid = db.Column(db.String, index=True)
    study_key_fk = db.Column(db.Integer, db.ForeignKey('studies.id'))
    modality = db.Column(db.String)
    body_part = db.Column(db.String)
    
    instances = db.relationship('Instance', backref='series', lazy=True)