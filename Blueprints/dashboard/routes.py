from collections import Counter
from datetime import datetime, timedelta
from flask import Blueprint, render_template
from sqlalchemy import func
from Blueprints.auth.routes import login_required
from models import db, Patient, Study, Ward, Series, Instance, RadiologyReport

home_bp = Blueprint('home_bp', __name__)

@home_bp.route("/")
@login_required
def home_page():
    stats = {
        "patients": Patient.query.count(),
        "studies": Study.query.count(),
        "wards": Ward.query.count(),
    }
    return render_template('home.html', stats=stats)


def _parse_study_date(study_date):
    if not study_date:
        return None
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(study_date, fmt).date()
        except ValueError:
            continue
    return None


@home_bp.route("/stats")
@login_required
def stats_dashboard():
    total_patients = Patient.query.count()
    total_studies = Study.query.count()
    total_series = Series.query.count()
    total_instances = Instance.query.count()

    modality_rows = (
        db.session.query(Series.modality, func.count(Series.id))
        .group_by(Series.modality)
        .all()
    )
    modality_counts = []
    for modality, count in modality_rows:
        label = modality or "Unknown"
        modality_counts.append({"label": label, "count": count})
    modality_counts.sort(key=lambda item: item["count"], reverse=True)

    wards_rows = (
        db.session.query(Ward.ward_name, func.count(Study.id))
        .join(Patient, Patient.ward_id == Ward.id)
        .join(Study, Study.patient_id_fk == Patient.id)
        .group_by(Ward.ward_name)
        .all()
    )
    ward_counts = [{"label": ward_name or "Unknown", "count": count} for ward_name, count in wards_rows]
    ward_counts.sort(key=lambda item: item["count"], reverse=True)

    today = datetime.utcnow().date()
    window_days = 14
    days = [today - timedelta(days=idx) for idx in range(window_days - 1, -1, -1)]
    by_day = Counter()

    for study in Study.query.with_entities(Study.study_date).all():
        parsed = _parse_study_date(study.study_date)
        if parsed:
            by_day[parsed] += 1

    studies_trend = [{"date": day.strftime("%d %b"), "count": by_day.get(day, 0)} for day in days]

    report_rows = db.session.query(RadiologyReport.status, func.count(RadiologyReport.id)).group_by(RadiologyReport.status).all()
    report_status_counts = []
    for status, count in report_rows:
        label = (status or "unknown").capitalize()
        report_status_counts.append({"label": label, "count": count})
    report_status_counts.sort(key=lambda item: item["count"], reverse=True)

    reported_study_ids = {
        study_id
        for (study_id,) in db.session.query(RadiologyReport.study_id_fk).distinct().all()
        if study_id is not None
    }
    pending_reports = max(total_studies - len(reported_study_ids), 0)

    kpis = {
        "patients": total_patients,
        "studies": total_studies,
        "series": total_series,
        "instances": total_instances,
        "pending_reports": pending_reports,
        "avg_instances_per_study": round(total_instances / total_studies, 2) if total_studies else 0,
    }

    return render_template(
        "stats_dashboard.html",
        kpis=kpis,
        modality_counts=modality_counts,
        ward_counts=ward_counts,
        studies_trend=studies_trend,
        report_status_counts=report_status_counts,
    )
