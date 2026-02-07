
from flask import Blueprint, request, jsonify, url_for, current_app, make_response
from models import db, Patient, Study, Series, Instance

dicomweb_bp = Blueprint("dicomweb_bp", __name__, url_prefix='/dicomweb')

# Small helper to build a minimal DICOM JSON element
def dicom_element(tag_hex, value, vr):
    # tag_hex e.g. "0020000D" (StudyInstanceUID)
    return { tag_hex: { "Value": [value] if value is not None else [], "vr": vr } }

# Map a Study model -> DICOMweb JSON object
def study_to_qido_json(study):
    obj = {}
    obj.update(dicom_element("0020000D", study.study_instance_uid, "UI"))
    
    if study.study_date:
        obj.update(dicom_element("00080020", study.study_date, "DA"))
    
    if study.patient:
        obj.update(dicom_element("00100020", study.patient.patient_id, "LO"))
        obj.update(dicom_element("00100010", study.patient.patient_name or "Unknown", "PN"))
    
    # Add description
    if study.description:
        obj.update(dicom_element("00081030", study.description, "LO"))
    
    # Count instances
    total_instances = sum(len(series.instances) for series in study.series)
    obj.update(dicom_element("00201208", str(total_instances), "IS"))
    
    # Get modalities from series
    modalities = list(set(s.modality for s in study.series if s.modality))
    if modalities:
        obj.update(dicom_element("00080061", ",".join(modalities), "CS"))
    
    return obj

# Map a Series model -> DICOMweb JSON object
def series_to_qido_json(series):
    obj = {}
    # Series Instance UID (0020,000E)
    obj.update(dicom_element("0020000E", series.series_instance_uid, "UI"))
    # Modality (0008,0060)
    if getattr(series, "modality", None):
        obj.update(dicom_element("00080060", series.modality, "CS"))
    # Series Description (0008,103E) if present
    if getattr(series, "body_part", None):
        obj.update(dicom_element("0008103E", series.body_part, "LO"))
    # Study Instance UID (0020,000D) - include parent study UID for convenience
    if getattr(series, "study", None):
        obj.update(dicom_element("0020000D", series.study.study_instance_uid, "UI"))
    return obj

# Map an Instance model -> DICOMweb JSON object
def instance_to_qido_json(instance):
    obj = {}
    # SOP Instance UID (0008,0018)
    obj.update(dicom_element("00080018", instance.sop_instance_uid, "UI"))
    # Instance Number (0020,0013)
    if getattr(instance, "instance_number", None) is not None:
        obj.update(dicom_element("00200013", instance.instance_number, "IS"))
    # Retrieve URL (non-standard convenience element) - OHIF expects WADO endpoints separately,
    # but adding a link here is helpful for debugging / clients.
    # Not DICOM tag — use private tag or a custom key; I'll add "00081190" as a placeholder.
    # Remove if you prefer strict DICOMweb.
    if getattr(instance, "preview_path", None):
        # Build absolute URL to preview JPEG (optional)
        preview_url = url_for("static", filename=instance.preview_path.replace("static/", ""), _external=True)
        obj.update({"00081190": {"Value": [preview_url], "vr": "UR"}})

    # Include parent identifiers
    if getattr(instance, "series", None) and getattr(instance.series, "study", None):
        obj.update(dicom_element("0020000D", instance.series.study.study_instance_uid, "UI"))
        obj.update(dicom_element("0020000E", instance.series.series_instance_uid, "UI"))
    return obj

# --- QIDO: list studies ---
@dicomweb_bp.route("/studies", methods=["GET"])
def qido_studies():
    # Simple filters: PatientID=..., limit, offset
    patient_id_filter = request.args.get("PatientID")
    limit = int(request.args.get("limit", 50))
    offset = int(request.args.get("offset", 0))

    query = Study.query
    if patient_id_filter:
        query = query.join(Patient).filter(Patient.patient_id == patient_id_filter)

    query = query.order_by(Study.study_date.desc().nullslast()).limit(limit).offset(offset)
    studies = query.all()

    result = [study_to_qido_json(s) for s in studies]
    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp

# --- QIDO: list series for a study ---
@dicomweb_bp.route("/studies/<study_uid>/series", methods=["GET"])
def qido_series_for_study(study_uid):
    limit = int(request.args.get("limit", 200))
    offset = int(request.args.get("offset", 0))

    study = Study.query.filter_by(study_instance_uid=study_uid).first()
    if not study:
        return jsonify([]), 404

    # Use relationship series (ensure relationship exists on Study model)
    series_q = Series.query.filter_by(study_key_fk=study.id).order_by(Series.id).limit(limit).offset(offset)
    series_list = series_q.all()
    result = [series_to_qido_json(s) for s in series_list]

    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp

# --- QIDO: list instances for a series in a study ---
@dicomweb_bp.route("/studies/<study_uid>/series/<series_uid>/instances", methods=["GET"])
def qido_instances_for_series(study_uid, series_uid):
    limit = int(request.args.get("limit", 500))
    offset = int(request.args.get("offset", 0))

    series = Series.query.join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid
    ).first()

    if not series:
        return jsonify([]), 404

    instances_q = Instance.query.filter_by(series_id_fk=series.id).order_by(Instance.id).limit(limit).offset(offset)
    instances = instances_q.all()
    result = [instance_to_qido_json(i) for i in instances]

    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp

@dicomweb_bp.route("/studies/<study_uid>/metadata", methods=["GET"])
def get_study_metadata(study_uid):
    """
    Return full DICOM metadata for all instances in a study
    """
    import pydicom
    import os
    from flask import current_app
    
    study = Study.query.filter_by(study_instance_uid=study_uid).first()
    if not study:
        return jsonify({"error": "Study not found"}), 404
    
    result = []
    for series in study.series:
        for instance in series.instances:
            # Resolve file path relative to Flask app root
            file_path = instance.file_path
            if not os.path.isabs(file_path):
                file_path = os.path.join(current_app.root_path, file_path)
            
            try:
                dcm = pydicom.dcmread(file_path, force=True)
                dcm_json = dcm.to_json_dict()
                result.append(dcm_json)
            except Exception as e:
                print(f"Error loading DICOM {file_path}: {e}")
    
    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp