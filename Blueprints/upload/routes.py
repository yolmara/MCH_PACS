from Blueprints.auth.routes import login_required
from flask import (Blueprint, request, jsonify, render_template, redirect)
from werkzeug.utils import secure_filename
from dicom_utils.activity_logger import log_activity
from models import db, Patient
import os
import pydicom
from datetime import datetime

from dicom_utils import (
    load_dicom,
    extract_metadata,
    dicom_to_jpeg,
    build_instance_path,
    get_patient_folder,
    ensure_patient_folder,
    upsert_study, 
    upsert_series, 
    upsert_instance
)

upload_bp = Blueprint("upload_bp", __name__)


class PatientIdentityConflictError(ValueError):
    """Raised when uploaded files conflict with an existing patient identity."""


class InvalidDICOMInstanceError(ValueError):
    """Raised when a file is not a storable DICOM instance for this workflow."""


def _norm(value):
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _assert_patient_identity_consistent(patient_id, name=None, sex=None, dob=None):
    existing = Patient.query.filter_by(patient_id=patient_id).first()
    if not existing:
        return

    conflicts = []
    existing_name, incoming_name = _norm(existing.patient_name), _norm(name)
    if existing_name and incoming_name and existing_name != incoming_name:
        conflicts.append(f"name existing='{existing.patient_name}' incoming='{name}'")

    existing_sex, incoming_sex = _norm(existing.patient_sex), _norm(sex)
    if existing_sex and incoming_sex and existing_sex != incoming_sex:
        conflicts.append(f"sex existing='{existing.patient_sex}' incoming='{sex}'")

    existing_dob, incoming_dob = _norm(existing.patient_dob), _norm(dob)
    if existing_dob and incoming_dob and existing_dob != incoming_dob:
        conflicts.append(f"dob existing='{existing.patient_dob}' incoming='{dob}'")

    if conflicts:
        raise PatientIdentityConflictError(
            f"PatientID '{patient_id}' already exists with different demographics: " + "; ".join(conflicts)
        )


def _assert_required_instance_uids(dcm):
    required = ("StudyInstanceUID", "SeriesInstanceUID", "SOPInstanceUID")
    missing = [field for field in required if not getattr(dcm, field, None)]
    if missing:
        missing_list = ", ".join(missing)
        raise InvalidDICOMInstanceError(
            f"Not a storable image instance (missing {missing_list}). "
            "Select the folder containing actual DICOM image slices, not viewer/support files."
        )


def _upsert_patient_local(patient_id, name=None, sex=None, dob=None):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        patient = Patient(
            patient_id=patient_id,
            patient_name=name,
            patient_sex=sex,
            patient_dob=dob,
        )
        db.session.add(patient)
        db.session.flush()
        return patient

    if name and not patient.patient_name:
        patient.patient_name = name
    if sex and not patient.patient_sex:
        patient.patient_sex = sex
    if dob and not patient.patient_dob:
        patient.patient_dob = dob
    return patient

@upload_bp.route("/folder", methods=["GET"])
@login_required
def upload_folder_page():
    return render_template("upload_folder.html")


@upload_bp.route("/folder", methods=["POST"])
@login_required
def upload_folder():
    """
    Handles uploading a folder of DICOM files.
    Each uploaded folder belongs to a patient.
    """

    if "files" not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist("files")
    patient_id = (request.form.get("patient_id") or "").strip()
    ward_id = request.form.get("ward_id")

    if not patient_id:
        return jsonify({"error": "patient_id is required"}), 400
    
    if not ward_id:
        return jsonify({"error": "ward_id is required"}), 400

    # Ensure patient directory exists
    patient_dir = ensure_patient_folder(patient_id)

    created_files = []
    errors = []
    source_dicom_patient_id = None

    for file in files:
        # FIX: Ensure .dcm extension
        filename = secure_filename(file.filename)
        if not filename.lower().endswith('.dcm'):
            filename = f"{filename}.dcm"
        
        temp_path = os.path.join(patient_dir, filename)
        file.save(temp_path)

        try:
            dcm = load_dicom(temp_path)
            _assert_required_instance_uids(dcm)
            meta = extract_metadata(dcm)

            dicom_patient_id = str(getattr(dcm, "PatientID", "")).strip()
            if dicom_patient_id:
                if source_dicom_patient_id and dicom_patient_id != source_dicom_patient_id:
                    raise PatientIdentityConflictError(
                        f"Mixed DICOM PatientID values in one folder: "
                        f"'{source_dicom_patient_id}' and '{dicom_patient_id}'. "
                        "Upload one patient per folder."
                    )
                source_dicom_patient_id = dicom_patient_id

            # Safe conversion
            patient_name = str(meta.get("PatientName")) if meta.get("PatientName") else None
            patient_sex = str(meta.get("PatientSex")) if meta.get("PatientSex") else None
            patient_dob = str(meta.get("PatientBirthDate")) if meta.get("PatientBirthDate") else None
            study_desc = str(meta.get("StudyDescription")) if meta.get("StudyDescription") else None

            _assert_patient_identity_consistent(
                patient_id=patient_id,
                name=patient_name,
                sex=patient_sex,
                dob=patient_dob,
            )

            # Upsert patient
            patient = _upsert_patient_local(
                patient_id=patient_id,
                name=patient_name,
                sex=patient_sex,
                dob=patient_dob
            )
            
            # Assign ward to patient
            patient.ward_id = int(ward_id)

            # Upsert study
            study = upsert_study(
                patient=patient,
                study_uid=meta["StudyInstanceUID"],
                study_date=meta.get("StudyDate"),
                description=study_desc
            )

            # Upsert series
            series = upsert_series(
                study=study,
                series_uid=meta["SeriesInstanceUID"],
                modality=meta.get("Modality")
            )

            # Generate preview
            preview_path = None
            try:
                preview_path = dicom_to_jpeg(
                    dcm=dcm,
                    output_dir=os.path.join(patient_dir, "previews"),
                    instance_uid=meta["SOPInstanceUID"]
                )
            except Exception:
                # Keep storing valid instances even if preview conversion fails.
                preview_path = None

            # Upsert instance
            instance = upsert_instance(
                series=series,
                sop_uid=meta["SOPInstanceUID"],
                file_path=temp_path,
                preview_path=preview_path
            )

            created_files.append({
                "file": filename,
                "study_uid": study.study_instance_uid,
                "series_uid": series.series_instance_uid,
                "instance_uid": instance.sop_instance_uid,
                "preview": preview_path
            })

        except PatientIdentityConflictError as e:
            db.session.rollback()
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            errors.append({
                "file": filename,
                "error": str(e),
                "type": "patient_identity_conflict"
            })
        except InvalidDICOMInstanceError as e:
            db.session.rollback()
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            errors.append({
                "file": filename,
                "error": str(e),
                "type": "invalid_dicom_instance"
            })
        except Exception as e:
            db.session.rollback()
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except OSError:
                pass
            errors.append({
                "file": filename,
                "error": str(e),
                "type": "upload_processing_error"
            })

    db.session.commit()
    
    # Log activity
    log_activity(
        'upload_folder', 
        resource=f'patient_{patient_id}',
        details=(
            f'Uploaded {len(created_files)} files to ward {ward_id}. '
            f'Errors: {len(errors)}. Source DICOM PatientID: {source_dicom_patient_id or "unknown"}'
        )
    )

    return jsonify({
        "message": "Folder processed",
        "created": created_files,
        "errors": errors,
        "patient_id": patient_id,
        "ward_id": ward_id
    })
