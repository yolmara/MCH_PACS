from models import db
from datetime import datetime


class ReportAddendum(db.Model):
    __tablename__ = 'report_addenda'

    id = db.Column(db.Integer, primary_key=True)

    # Link to original report — addendum never modifies the original
    report_id = db.Column(
        db.Integer,
        db.ForeignKey('radiology_reports.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )

    # Author (the radiologist or admin adding the addendum)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    author_name = db.Column(db.String(200))

    # Addendum content
    content = db.Column(db.Text, nullable=False)

    # Timestamp
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    # Relationships
    report = db.relationship(
        'RadiologyReport',
        backref=db.backref('addenda', lazy='dynamic', order_by='ReportAddendum.created_at'),
    )
    author = db.relationship('User', backref='addenda')

    def __repr__(self):
        return f'<ReportAddendum {self.id} for Report {self.report_id}>'