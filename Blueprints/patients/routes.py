import os
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from Blueprints.auth.routes import login_required, role_required
from dicom_utils.activity_logger import log_activity
from models import db, Patient, Study, Series


patients_bp = Blueprint("patients_bp", __name__)


@patients_bp.route("/", methods=["GET"])
@login_required
@role_required("clerk", "admin")
def patients_list():
    q = (request.args.get("q") or "").strip()
    page = request.args.get("page", 1, type=int)
    per_page = 25

    query = Patient.query.options(
        joinedload(Patient.ward),
        joinedload(Patient.studies),
    )

    if q:
        query = query.filter(
            or_(
                Patient.patient_id.ilike(f"%{q}%"),
                Patient.patient_name.ilike(f"%{q}%"),
            )
        )

    patients = query.order_by(Patient.id.desc()).paginate(
        page=page,
        per_page=per_page,
        error_out=False,
    )
    return render_template("patients_list.html", patients=patients, q=q)


@patients_bp.route("/<int:patient_id>", methods=["GET"])
@login_required
@role_required("clerk", "admin")
def patient_detail(patient_id):
    patient = Patient.query.options(
        joinedload(Patient.ward),
        joinedload(Patient.studies).joinedload(Study.series).joinedload(Series.instances),
    ).get_or_404(patient_id)
    return render_template("patient_detail.html", patient=patient)


def _resolve_path(path):
    if not path:
        return None
    if not os.path.isabs(path):
        return os.path.join(current_app.root_path, path)
    return path


def _delete_instance_files(instance):
    for stored_path in (instance.file_path, instance.preview_path):
        abs_path = _resolve_path(stored_path)
        if abs_path and os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                current_app.logger.warning("Failed to remove file: %s", abs_path)


def _delete_study_tree(study):
    series_count = 0
    instance_count = 0

    for series in list(study.series):
        series_count += 1
        for instance in list(series.instances):
            instance_count += 1
            _delete_instance_files(instance)
            db.session.delete(instance)
        db.session.delete(series)

    db.session.delete(study)
    return series_count, instance_count


@patients_bp.route("/studies/<int:study_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_study(study_id):
    study = Study.query.get_or_404(study_id)
    patient = study.patient

    try:
        series_count, instance_count = _delete_study_tree(study)
        db.session.commit()

        log_activity(
            "delete_study",
            resource=f"study_{study.study_instance_uid}",
            details=(
                f"Deleted study {study.study_instance_uid} for patient {patient.patient_id}. "
                f"Removed {series_count} series and {instance_count} instances."
            ),
        )
        flash("Study deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete study %s", study_id)
        flash(f"Failed to delete study: {exc}", "error")

    return redirect(url_for("patients_bp.patient_detail", patient_id=patient.id))


@patients_bp.route("/<int:patient_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_patient(patient_id):
    patient = Patient.query.options(
        joinedload(Patient.studies).joinedload(Study.series).joinedload(Series.instances)
    ).get_or_404(patient_id)

    patient_code = patient.patient_id or str(patient.id)
    deleted_studies = 0
    deleted_series = 0
    deleted_instances = 0

    try:
        for study in list(patient.studies):
            deleted_studies += 1
            series_count, instance_count = _delete_study_tree(study)
            deleted_series += series_count
            deleted_instances += instance_count

        db.session.delete(patient)
        db.session.commit()

        log_activity(
            "delete_patient",
            resource=f"patient_{patient_code}",
            details=(
                f"Deleted patient {patient_code}. Removed {deleted_studies} studies, "
                f"{deleted_series} series and {deleted_instances} instances."
            ),
        )
        flash("Patient deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete patient %s", patient_id)
        flash(f"Failed to delete patient: {exc}", "error")

    return redirect(url_for("patients_bp.patients_list"))
