from flask import Blueprint, render_template, request, redirect, jsonify, url_for, current_app
from datetime import datetime
import json
import os
from io import BytesIO
import httpx
import pydicom
from models import Study, Series, Instance, db
from dicom_utils.activity_logger import log_activity
from Blueprints.auth.routes import VIEWER_ROLES, login_required, role_required
from dicom_utils import (
    extract_metadata,
    dicom_to_jpeg,
    ensure_patient_folder,
    upsert_patient,
    upsert_study,
    upsert_series,
    upsert_instance,
    PatientIdentityConflictError,
)

dicom_bp = Blueprint("dicom_bp", __name__)


@dicom_bp.route("/notify", methods=["POST"])
def orthanc_notify():
    expected_token = (os.environ.get("ORTHANC_NOTIFY_TOKEN") or "").strip()
    if expected_token:
        received_token = (request.headers.get("X-Orthanc-Token") or "").strip()
        if received_token != expected_token:
            return jsonify({"error": "Unauthorized notification"}), 401

    payload = request.get_json(silent=True) or {}
    instance_id = str(payload.get("instance_id") or payload.get("ID") or "").strip()
    if not instance_id:
        return jsonify({"error": "instance_id is required"}), 400

    # Orthanc sends one notification per stored instance (500+ for a single CT).
    # Writing a log-file line and an activity-log row for each one buries real user
    # actions, so only failures are reported (in the container log) and ingest logs
    # one activity entry per NEW study instead.
    current_app.logger.debug("Orthanc notification received for instance %s", instance_id)

    ingest_result = _ingest_orthanc_instance(instance_id)
    if ingest_result.get("status") == "error":
        current_app.logger.warning(
            "Orthanc ingest failed for instance %s: %s", instance_id, ingest_result.get("error")
        )
    return jsonify({"status": "accepted", "instance_id": instance_id, "ingest": ingest_result}), 202


def _resolve_instance_file_path(path):
    if not path:
        return None
    return path if os.path.isabs(path) else os.path.join(current_app.root_path, path)


def _orthanc_client():
    base_url = current_app.config.get("ORTHANC_API_URL", "http://orthanc:8042").rstrip("/")
    username = (current_app.config.get("ORTHANC_ADMIN_USERNAME") or "").strip()
    password = (current_app.config.get("ORTHANC_ADMIN_PASSWORD") or "").strip()
    auth = (username, password) if username and password else None
    return httpx.Client(base_url=base_url, auth=auth, timeout=30.0)


def _ingest_orthanc_instance(instance_id):
    if not current_app.config.get("ORTHANC_INGEST_ENABLED", True):
        return {"status": "skipped", "reason": "ingest_disabled"}

    try:
        with _orthanc_client() as client:
            resp = client.get(f"/instances/{instance_id}/file")
            resp.raise_for_status()
            content = resp.content
    except Exception as exc:
        current_app.logger.exception("Failed to fetch Orthanc instance %s", instance_id)
        return {"status": "error", "error": str(exc)}

    if not content:
        return {"status": "error", "error": "empty_instance_file"}

    try:
        ds = pydicom.dcmread(BytesIO(content), force=True)
    except Exception as exc:
        current_app.logger.exception("Failed to parse DICOM for Orthanc instance %s", instance_id)
        return {"status": "error", "error": f"parse_failed: {exc}"}

    meta = extract_metadata(ds)
    missing = [key for key in ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID") if not meta.get(key)]
    if missing:
        return {"status": "error", "error": f"missing_uids: {', '.join(missing)}"}

    existing = Instance.query.filter_by(sop_instance_uid=meta["SOPInstanceUID"]).first()
    if existing:
        existing_path = _resolve_instance_file_path(existing.file_path)
        if existing_path and os.path.exists(existing_path):
            return {"status": "skipped", "reason": "already_ingested"}

    patient_id = str(getattr(ds, "PatientID", "") or "").strip()
    if not patient_id:
        seed = meta.get("StudyInstanceUID") or instance_id
        patient_id = f"UNKNOWN_{seed[:12]}"

    patient_name = str(meta.get("PatientName")) if meta.get("PatientName") else None
    patient_sex = str(meta.get("PatientSex")) if meta.get("PatientSex") else None
    patient_dob = str(meta.get("PatientBirthDate")) if meta.get("PatientBirthDate") else None

    patient_dir = ensure_patient_folder(patient_id)
    filename = f"{meta['SOPInstanceUID']}.dcm"
    file_path = os.path.join(patient_dir, filename)
    if not os.path.exists(file_path):
        try:
            with open(file_path, "wb") as handle:
                handle.write(content)
        except OSError as exc:
            current_app.logger.exception("Failed to write Orthanc instance to disk")
            return {"status": "error", "error": f"write_failed: {exc}"}

    try:
        patient = upsert_patient(
            patient_id=patient_id,
            name=patient_name,
            sex=patient_sex,
            dob=patient_dob,
        )
    except PatientIdentityConflictError as exc:
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return {"status": "error", "error": f"patient_conflict: {exc}"}

    try:
        # Remember whether this study is new, so we log once per study, not per slice.
        is_new_study = (
            Study.query.filter_by(study_instance_uid=meta["StudyInstanceUID"]).first() is None
        )

        study = upsert_study(
            patient=patient,
            study_uid=meta["StudyInstanceUID"],
            study_date=meta.get("StudyDate"),
            description=meta.get("StudyDescription"),
        )
        series = upsert_series(
            study=study,
            series_uid=meta["SeriesInstanceUID"],
            modality=meta.get("Modality"),
        )

        preview_path = None
        try:
            preview_path = dicom_to_jpeg(
                dcm=ds,
                output_dir=os.path.join(patient_dir, "previews"),
                instance_uid=meta["SOPInstanceUID"],
            )
        except Exception:
            preview_path = None

        instance = upsert_instance(
            series=series,
            sop_uid=meta["SOPInstanceUID"],
            file_path=file_path,
            preview_path=preview_path,
        )
    except Exception as exc:
        db.session.rollback()
        current_app.logger.exception("Failed to persist Orthanc instance %s", instance_id)
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except OSError:
                pass
        return {"status": "error", "error": f"db_failed: {exc}"}

    if is_new_study:
        log_activity(
            "orthanc_ingest",
            resource=f"study_{study.study_instance_uid}",
            details=f"New study received from Orthanc (patient {patient_id})",
        )

    return {
        "status": "ingested",
        "study_uid": study.study_instance_uid,
        "series_uid": series.series_instance_uid,
        "instance_uid": instance.sop_instance_uid,
    }


########## Viewer Route ##########
##################################
@dicom_bp.route("/mch-ohif-viewer")
@login_required
@role_required(*VIEWER_ROLES)
def ohif_viewer():
    """
    Launches the OHIF viewer with a given StudyInstanceUID.
    Frontend calls like:
    /viewer?StudyInstanceUID=1.2.840...
    """
    study_uid = request.args.get("StudyInstanceUID") or request.args.get("StudyInstanceUIDs")
    ohif_base_url = current_app.config.get("OHIF_VIEWER_URL", "http://localhost:8081/ohif").rstrip("/")

    # Dashboard access (no study selected yet): open OHIF landing page.
    if not study_uid:
        return redirect(f"{ohif_base_url}/")

    # Study-specific launch (OHIF uses /viewer route)
    return redirect(f"{ohif_base_url}/viewer?StudyInstanceUIDs={study_uid}")


######### Studies Route ##########
##################################
@dicom_bp.route("/dicom/studies/<study_uid>")
@login_required
@role_required(*VIEWER_ROLES)
def ohif_study_json(study_uid):

    study = Study.query.filter_by(study_instance_uid=study_uid).first()

    if not study:
        return jsonify({"error": "Study not found"}), 404

    series_list = []

    for series in study.series:
        instance_list = []

        for instance in series.instances:
            instance_list.append({
                "SOPInstanceUID": instance.sop_instance_uid,
                "url": instance.file_path  # OHIF fetches raw DICOM here
            })

        series_list.append({
            "SeriesInstanceUID": series.series_instance_uid,
            "Instances": instance_list
        })

    response = {
        "StudyInstanceUID": study.study_instance_uid,
        "Series": series_list
    }

    return jsonify(response)


def filesystem_path_to_url(fs_path):
    """
    If your DICOMs are saved under: static/uploads/...
    and inst.file_path stores the absolute or relative filesystem path,
    convert it to a URL that the browser can request.
    """
    # If stored absolute path, make it relative to your Flask static folder
    # Example: /app/static/uploads/patients/123/.. -> uploads/patients/123/..
    static_folder = current_app.static_folder  # typically "<repo>/static"
    fs_path = os.path.abspath(fs_path)

    # If file is inside static folder, build url_for('static', filename=...)
    if fs_path.startswith(os.path.abspath(static_folder)):
        rel_path = os.path.relpath(fs_path, static_folder).replace(os.path.sep, "/")
        return url_for('static', filename=rel_path, _external=False)

    # If file is outside static, consider creating a view to serve it (not recommended)
    # For now return None so upstream can handle it
    return None

@dicom_bp.route("/instances/<int:instance_id>/file")
@login_required
@role_required(*VIEWER_ROLES)
def serve_instance_file(instance_id):
    inst = Instance.query.get(instance_id)
    if not inst:
        return "Not found", 404
    return current_app.send_static_file(os.path.relpath(inst.file_path, current_app.static_folder))