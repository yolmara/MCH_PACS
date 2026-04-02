from flask import Blueprint, render_template, request, redirect, jsonify, url_for, current_app
from datetime import datetime
import json
import os
from models import Study, Series, Instance, db
from dicom_utils.activity_logger import log_activity

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

    incoming_dir = os.path.join(current_app.root_path, "incoming")
    os.makedirs(incoming_dir, exist_ok=True)
    log_path = os.path.join(incoming_dir, "orthanc_notifications.log")

    record = {
        "received_at": datetime.utcnow().isoformat() + "Z",
        "instance_id": instance_id,
        "remote_addr": request.remote_addr,
        "payload": payload,
    }

    try:
        with open(log_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")
    except OSError:
        current_app.logger.exception("Failed to persist Orthanc notification")

    current_app.logger.info("Orthanc notification received for instance %s", instance_id)
    log_activity(
        "orthanc_notify",
        resource=f"orthanc_instance_{instance_id}",
        details=f"Received Orthanc callback from {request.remote_addr}",
    )
    return jsonify({"status": "accepted", "instance_id": instance_id}), 202


########## Viewer Route ##########
##################################
@dicom_bp.route("/mch-ohif-viewer")
def ohif_viewer():
    """
    Launches the OHIF viewer with a given StudyInstanceUID.
    Frontend calls like:
    /viewer?StudyInstanceUID=1.2.840...
    """
    study_uid = request.args.get("StudyInstanceUID") or request.args.get("StudyInstanceUIDs")
    ohif_base_url = current_app.config.get("OHIF_VIEWER_URL", "http://localhost:8080").rstrip("/")

    # Dashboard access (no study selected yet): open OHIF landing page.
    if not study_uid:
        return redirect(f"{ohif_base_url}/")

    # Study-specific launch (OHIF uses /viewer route)
    return redirect(f"{ohif_base_url}/viewer?StudyInstanceUIDs={study_uid}")


######### Studies Route ##########
##################################
@dicom_bp.route("/dicom/studies/<study_uid>")
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
def serve_instance_file(instance_id):
    inst = Instance.query.get(instance_id)
    if not inst:
        return "Not found", 404
    # Optionally check current_user permissions here
    return current_app.send_static_file(os.path.relpath(inst.file_path, current_app.static_folder))
