from models import db

class Instance(db.Model):
    __tablename__ = 'instances'
    id = db.Column(db.Integer, primary_key=True)
    sop_instance_uid = db.Column(db.String, unique=True, index=True)
    file_path = db.Column(db.String)
    preview_path = db.Column(db.String)
    series_id_fk = db.Column(db.Integer, db.ForeignKey('series.id'))
    instance_number = db.Column(db.Integer)
    
    