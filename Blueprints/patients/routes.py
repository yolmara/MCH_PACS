import os
import shutil
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from sqlalchemy import or_
from sqlalchemy.orm import joinedload

from Blueprints.auth.routes import login_required, role_required
from dicom_utils.activity_logger import log_activity
from models import db, Patient, Study, Series, Appointment, RadiologyReport


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


def _is_within_directory(path, base_dir):
    try:
        path_abs = os.path.abspath(path)
        base_abs = os.path.abspath(base_dir)
        return os.path.commonpath([path_abs, base_abs]) == base_abs
    except (TypeError, ValueError):
        return False


def _delete_instance_files(instance):
    for stored_path in (instance.file_path, instance.preview_path):
        abs_path = _resolve_path(stored_path)
        if abs_path and os.path.exists(abs_path):
            try:
                os.remove(abs_path)
            except OSError:
                current_app.logger.warning("Failed to remove file: %s", abs_path)


def _delete_patient_upload_folders(patient_code):
    if not patient_code:
        return 0

    upload_root = current_app.config.get("UPLOAD_FOLDER")
    if not upload_root:
        return 0

    upload_root = os.path.abspath(upload_root)
    folder_names = [str(patient_code).strip()]
    deleted = 0

    for folder_name in folder_names:
        if not folder_name:
            continue
        for candidate in (
            os.path.join(upload_root, folder_name),
            os.path.join(upload_root, "patients", folder_name),
        ):
            if not os.path.isdir(candidate):
                continue
            if not _is_within_directory(candidate, upload_root):
                current_app.logger.warning("Skipping unsafe delete path: %s", candidate)
                continue
            try:
                shutil.rmtree(candidate)
                deleted += 1
            except OSError:
                current_app.logger.warning("Failed to remove patient folder: %s", candidate)

    # Best-effort cleanup for now-empty legacy container.
    legacy_root = os.path.join(upload_root, "patients")
    if os.path.isdir(legacy_root):
        try:
            os.rmdir(legacy_root)
        except OSError:
            pass

    return deleted


def _delete_study_tree(study):
    series_count = 0
    instance_count = 0
    report_count = 0

    for report in list(study.reports):
        report_count += 1
        db.session.delete(report)

    for series in list(study.series):
        series_count += 1
        for instance in list(series.instances):
            instance_count += 1
            _delete_instance_files(instance)
            db.session.delete(instance)
        db.session.delete(series)

    db.session.delete(study)
    return series_count, instance_count, report_count


@patients_bp.route("/studies/<int:study_id>/delete", methods=["POST"])
@login_required
@role_required("admin")
def delete_study(study_id):
    study = Study.query.get_or_404(study_id)
    patient = study.patient

    try:
        series_count, instance_count, report_count = _delete_study_tree(study)
        db.session.commit()

        log_activity(
            "delete_study",
            resource=f"study_{study.study_instance_uid}",
            details=(
                f"Deleted study {study.study_instance_uid} for patient {patient.patient_id}. "
                f"Removed {report_count} reports, {series_count} series and {instance_count} instances."
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
        joinedload(Patient.studies).joinedload(Study.series).joinedload(Series.instances),
        joinedload(Patient.studies).joinedload(Study.reports),
        joinedload(Patient.exam_orders),
        joinedload(Patient.appointments),
    ).get_or_404(patient_id)

    patient_code = patient.patient_id or str(patient.id)
    deleted_studies = 0
    deleted_series = 0
    deleted_instances = 0
    deleted_reports = 0
    deleted_orders = 0
    deleted_appointments = 0
    deleted_upload_dirs = 0

    try:
        # Appointments hold a NOT NULL FK to patient, so remove them first.
        for appt in list(patient.appointments):
            deleted_appointments += 1
            db.session.delete(appt)

        for study in list(patient.studies):
            deleted_studies += 1
            series_count, instance_count, report_count = _delete_study_tree(study)
            deleted_series += series_count
            deleted_instances += instance_count
            deleted_reports += report_count

        # Also remove reports linked to this patient's orders but not tied to studies.
        order_ids = [order.id for order in patient.exam_orders]
        if order_ids:
            orphan_order_reports = RadiologyReport.query.filter(
                RadiologyReport.exam_order_id_fk.in_(order_ids),
                RadiologyReport.study_id_fk.is_(None),
            ).all()
            for report in orphan_order_reports:
                deleted_reports += 1
                db.session.delete(report)

        for order in list(patient.exam_orders):
            deleted_orders += 1
            db.session.delete(order)

        db.session.delete(patient)
        db.session.commit()
        deleted_upload_dirs = _delete_patient_upload_folders(patient_code)

        log_activity(
            "delete_patient",
            resource=f"patient_{patient_code}",
            details=(
                f"Deleted patient {patient_code}. Removed {deleted_studies} studies, "
                f"{deleted_series} series, {deleted_instances} instances, "
                f"{deleted_reports} reports, {deleted_orders} orders, {deleted_appointments} appointments "
                f"and {deleted_upload_dirs} upload folders."
            ),
        )
        flash("Patient deleted successfully.", "success")
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to delete patient %s", patient_id)
        flash(f"Failed to delete patient: {exc}", "error")

    return redirect(url_for("patients_bp.patients_list"))
