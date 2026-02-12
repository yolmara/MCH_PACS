
import os
import pydicom
from flask import Blueprint, request, jsonify, current_app, make_response
from models import db, Patient, Study, Series, Instance

dicomweb_bp = Blueprint("dicomweb_bp", __name__, url_prefix='/dicomweb')

# Small helper to build a minimal DICOM JSON element
def dicom_element(tag_hex, value, vr):
    # tag_hex e.g. "0020000D" (StudyInstanceUID)
    if value is None:
        values = []
    elif isinstance(value, (list, tuple, set)):
        values = list(value)
    else:
        values = [value]
    return {tag_hex: {"Value": values, "vr": vr}}

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
    modalities = sorted(set(s.modality for s in study.series if s.modality))
    if modalities:
        obj.update(dicom_element("00080061", modalities, "CS"))
    
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
    # Include parent identifiers
    if getattr(instance, "series", None) and getattr(instance.series, "study", None):
        obj.update(dicom_element("0020000D", instance.series.study.study_instance_uid, "UI"))
        obj.update(dicom_element("0020000E", instance.series.series_instance_uid, "UI"))
    return obj


def _resolve_instance_file_path(instance):
    file_path = instance.file_path
    if not file_path:
        return None
    if not os.path.isabs(file_path):
        file_path = os.path.join(current_app.root_path, file_path)
    return file_path


def _instance_metadata_json(instance):
    file_path = _resolve_instance_file_path(instance)
    if not file_path or not os.path.exists(file_path):
        return None

    # OHIF metadata loading does not require PixelData; omitting it avoids huge responses.
    ds = pydicom.dcmread(file_path, stop_before_pixels=True, force=True)
    return ds.to_json_dict()

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
    study = Study.query.filter_by(study_instance_uid=study_uid).first()
    if not study:
        return jsonify({"error": "Study not found"}), 404
    
    result = []
    for series in study.series:
        for instance in series.instances:
            try:
                dcm_json = _instance_metadata_json(instance)
                if dcm_json:
                    result.append(dcm_json)
            except Exception as e:
                current_app.logger.warning("Error loading metadata for SOP %s: %s", instance.sop_instance_uid, e)
    
    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp


@dicomweb_bp.route("/studies/<study_uid>/series/<series_uid>/metadata", methods=["GET"])
def get_series_metadata(study_uid, series_uid):
    series = Series.query.join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid
    ).first()
    if not series:
        return jsonify([]), 404

    result = []
    for instance in series.instances:
        try:
            dcm_json = _instance_metadata_json(instance)
            if dcm_json:
                result.append(dcm_json)
        except Exception as e:
            current_app.logger.warning("Error loading metadata for SOP %s: %s", instance.sop_instance_uid, e)

    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp


@dicomweb_bp.route("/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/metadata", methods=["GET"])
def get_instance_metadata(study_uid, series_uid, instance_uid):
    instance = Instance.query.join(Series).join(Study).filter(
        Study.study_instance_uid == study_uid,
        Series.series_instance_uid == series_uid,
        Instance.sop_instance_uid == instance_uid
    ).first()
    if not instance:
        return jsonify([]), 404

    try:
        dcm_json = _instance_metadata_json(instance)
    except Exception as e:
        current_app.logger.warning("Error loading metadata for SOP %s: %s", instance_uid, e)
        return jsonify([]), 500

    result = [dcm_json] if dcm_json else []
    resp = make_response(jsonify(result), 200)
    resp.headers["Content-Type"] = "application/dicom+json"
    return resp
