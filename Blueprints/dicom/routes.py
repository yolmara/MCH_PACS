from flask import Blueprint, render_template, request, redirect, jsonify, url_for, current_app
import os
from models import Study, Series, Instance, db

dicom_bp = Blueprint("dicom_bp", __name__)


########## Viewer Route ##########
##################################
@dicom_bp.route("/mch-ohif-viewer")
def ohif_viewer():
    """
    Launches the OHIF viewer with a given StudyInstanceUID.
    Frontend calls like:
    /viewer?StudyInstanceUID=1.2.840...
    """
    study_uid = request.args.get("StudyInstanceUID")

    if not study_uid:
        return "StudyInstanceUID required", 400

    # Redirect to the built OHIF viewer with the study UID
    return redirect(f"/ohif-viewer/viewer/mch_pacs?StudyInstanceUID={study_uid}")


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

