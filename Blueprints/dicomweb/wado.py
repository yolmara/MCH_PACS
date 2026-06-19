# blueprints/dicomweb/wado.py
import os
from flask import Blueprint, request, jsonify, current_app, send_file, abort, make_response
from sqlalchemy.orm.exc import NoResultFound
from models import db, Study, Series, Instance
from dicom_utils import load_dicom, dicom_to_jpeg, ensure_patient_folder
from pydicom.encaps import _generate_pixel_data_frame
from pydicom.uid import UID
from Blueprints.auth.routes import login_required


wado_bp = Blueprint("wado_bp", __name__)

def safe_send_file(path, mimetype, as_attachment=False, download_name=None):
    """
    Wrapper around Flask send_file with existence check.
    """
    if not path or not os.path.exists(path):
        abort(404, description="File not found")
    return send_file(path, mimetype=mimetype, as_attachment=as_attachment, download_name=download_name)

# -----------------------
# WADO-RS style (retrieve instance metadata / bulk)
# GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>
# Returns the original DICOM file (application/dicom)
# -----------------------
@wado_bp.route("/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>", methods=["GET"])
@login_required
def wado_get_instance(study_uid, series_uid, instance_uid):
    """
    Return the raw DICOM file for the given instance.
    """
    # Find instance record
    series = Series.query.join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid
    ).first()

    if not series:
        return jsonify({"error": "Series not found"}), 404

    instance = Instance.query.filter_by(series_id_fk=series.id, sop_instance_uid=instance_uid).first()
    if not instance:
        return jsonify({"error": "Instance not found"}), 404

    dicom_path = instance.file_path
    # If file_path is relative to static, resolve absolute
    if dicom_path and not os.path.isabs(dicom_path):
        dicom_path = os.path.join(current_app.root_path, dicom_path)

    # Return original DICOM file bytes
    return safe_send_file(dicom_path, mimetype="application/dicom", as_attachment=False)

# -----------------------
# WADO-RS rendered (return rendered JPEG)
# GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/rendered
# Returns a rendered JPEG (image/jpeg). Generates preview if missing.
# -----------------------
@wado_bp.route("/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/rendered", methods=["GET"])
@login_required
def wado_get_instance_rendered(study_uid, series_uid, instance_uid):
    """
    Return rendered JPEG for client consumption (OHIF can use this for thumbnails or rendered frame).
    """
    series = Series.query.join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid
    ).first()

    if not series:
        return jsonify({"error": "Series not found"}), 404

    instance = Instance.query.filter_by(series_id_fk=series.id, sop_instance_uid=instance_uid).first()
    if not instance:
        return jsonify({"error": "Instance not found"}), 404

    # Preview path may be absolute or relative to app root
    preview_path = instance.preview_path
    if preview_path and not os.path.isabs(preview_path):
        preview_path = os.path.join(current_app.root_path, preview_path)

    # If preview exists, return it
    if preview_path and os.path.exists(preview_path):
        return safe_send_file(preview_path, mimetype="image/jpeg")

    # Otherwise, generate preview from DICOM and return it
    dicom_path = instance.file_path
    if not dicom_path:
        return jsonify({"error": "No dicom file path stored for instance"}), 404

    if not os.path.isabs(dicom_path):
        dicom_path = os.path.join(current_app.root_path, dicom_path)

    try:
        ds = load_dicom(dicom_path)         # returns pydicom.Dataset
    except Exception as e:
        current_app.logger.exception("Failed to load DICOM for rendering")
        return jsonify({"error": f"Failed to load DICOM: {str(e)}"}), 500

    # Decide output directory for previews: place beside original under previews/
    # Attempt to infer patient folder if using ensure_patient_folder helper
    # Fallback: use instance folder
    preview_dir = os.path.join(os.path.dirname(dicom_path), "previews")
    os.makedirs(preview_dir, exist_ok=True)
    try:
        out_path = dicom_to_jpeg(ds, preview_dir, instance_uid)
    except Exception as e:
        current_app.logger.exception("Failed to render JPEG from DICOM")
        return jsonify({"error": f"Failed to render JPEG: {str(e)}"}), 500

    # Update instance.preview_path (store relative path from app root if desired)
    rel_preview = os.path.relpath(out_path, current_app.root_path)
    instance.preview_path = os.path.join("static", rel_preview) if not rel_preview.startswith("static") else rel_preview
    db.session.add(instance)
    db.session.commit()

    return safe_send_file(out_path, mimetype="image/jpeg")

# -----------------------
# WADO-URI compatibility endpoint (legacy clients)
# Example: /dicomweb/wado?requestType=WADO&studyUID=...&seriesUID=...&objectUID=...&contentType=image/jpeg
# -----------------------
@wado_bp.route("/wado", methods=["GET"])
@login_required
def wado_uri():
    """
    Support WADO-URI style requests with query parameters:
    - requestType=WADO
    - studyUID, seriesUID, objectUID
    - contentType (optional) -> 'application/dicom' or 'image/jpeg'
    """
    request_type = request.args.get("requestType")
    if not request_type or request_type.upper() != "WADO":
        return jsonify({"error": "Only requestType=WADO supported"}), 400

    study_uid = request.args.get("studyUID") or request.args.get("studyUID".lower())
    series_uid = request.args.get("seriesUID") or request.args.get("seriesUID".lower())
    object_uid = request.args.get("objectUID") or request.args.get("objectUID".lower())
    content_type = request.args.get("contentType", "application/dicom")

    if not (study_uid and series_uid and object_uid):
        return jsonify({"error": "studyUID, seriesUID and objectUID are required"}), 400

    # If contentType contains 'jpeg' return rendered JPEG, else DICOM
    if "jpeg" in content_type.lower():
        return wado_get_instance_rendered(study_uid, series_uid, object_uid)
    else:
        return wado_get_instance(study_uid, series_uid, object_uid)

# -----------------------
# Optional small helper: stream raw DICOM bytes from Dataset object
# If you store only file path you do not need this, but included for completeness.
# -----------------------
def dataset_to_response(ds, filename=None):
    """
    Convert a pydicom Dataset (in memory) to a Flask response that sends raw DICOM bytes.
    """
    from io import BytesIO
    bio = BytesIO()
    try:
        ds.save_as(bio, write_like_original=True)
    except Exception:
        # fallback: write with pydicom.filewriter
        from pydicom.filewriter import write_file
        bio.seek(0)
        write_file(bio, ds)
    bio.seek(0)
    response = make_response(bio.read())
    response.headers["Content-Type"] = "application/dicom"
    if filename:
        response.headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response

@wado_bp.route("/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/frames/<frame_number>", methods=["GET"])
@login_required
def wado_get_frame(study_uid, series_uid, instance_uid, frame_number):
    series = Series.query.join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid
    ).first()
    if not series:
        return jsonify({"error": "Series not found"}), 404

    instance = Instance.query.filter_by(series_id_fk=series.id, sop_instance_uid=instance_uid).first()
    if not instance:
        return jsonify({"error": "Instance not found"}), 404

    dicom_path = instance.file_path
    if dicom_path and not os.path.isabs(dicom_path):
        dicom_path = os.path.join(current_app.root_path, dicom_path)
    if not os.path.exists(dicom_path):
        return jsonify({"error": "DICOM file not found"}), 404

    try:
        ds = load_dicom(dicom_path)
        ts = UID(ds.file_meta.TransferSyntaxUID)

        # Frame index is 1-based in URL, 0-based in code
        frame_index = int(frame_number) - 1

        # Determine number of frames
        num_frames = int(getattr(ds, "NumberOfFrames", 1))

        if frame_index < 0 or frame_index >= num_frames:
            return jsonify({"error": "Frame out of range"}), 400

        if ts.is_encapsulated:
            # Compressed pixel data: return encapsulated frame bytes directly
            frame_bytes = _generate_pixel_data_frame(ds.PixelData, frame_index)
            transfer_syntax = str(ts)
        else:
            # Uncompressed pixel data: slice from PixelData
            rows = int(ds.Rows)
            cols = int(ds.Columns)
            spp = int(getattr(ds, "SamplesPerPixel", 1))
            bits = int(ds.BitsAllocated)
            bytes_per_sample = bits // 8
            frame_length = rows * cols * spp * bytes_per_sample

            start = frame_index * frame_length
            end = start + frame_length
            frame_bytes = ds.PixelData[start:end]
            transfer_syntax = str(ts)

        resp = make_response(frame_bytes)
        resp.headers["Content-Type"] = f"application/octet-stream; transfer-syntax={transfer_syntax}"
        return resp

    except Exception as e:
        current_app.logger.exception("Failed to return frame")
        return jsonify({"error": f"Failed to return frame: {str(e)}"}), 500
