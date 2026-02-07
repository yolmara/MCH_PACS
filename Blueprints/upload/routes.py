from Blueprints.auth.routes import login_required
from flask import (Blueprint, request, jsonify, render_template, redirect)
from werkzeug.utils import secure_filename
from dicom_utils.activity_logger import log_activity
from models import db
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
    upsert_patient, 
    upsert_study, 
    upsert_series, 
    upsert_instance
)

upload_bp = Blueprint("upload_bp", __name__)

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
    patient_id = request.form.get("patient_id")
    ward_id = request.form.get("ward_id")

    if not patient_id:
        return jsonify({"error": "patient_id is required"}), 400
    
    if not ward_id:
        return jsonify({"error": "ward_id is required"}), 400

    # Ensure patient directory exists
    patient_dir = ensure_patient_folder(patient_id)

    created_files = []
    errors = []

    for file in files:
        # FIX: Ensure .dcm extension
        filename = secure_filename(file.filename)
        if not filename.lower().endswith('.dcm'):
            filename = f"{filename}.dcm"
        
        temp_path = os.path.join(patient_dir, filename)
        file.save(temp_path)

        try:
            dcm = load_dicom(temp_path)
            meta = extract_metadata(dcm)

            # Safe conversion
            patient_name = str(meta.get("PatientName")) if meta.get("PatientName") else None
            patient_sex = str(meta.get("PatientSex")) if meta.get("PatientSex") else None
            patient_dob = str(meta.get("PatientBirthDate")) if meta.get("PatientBirthDate") else None
            study_desc = str(meta.get("StudyDescription")) if meta.get("StudyDescription") else None

            # Upsert patient
            patient = upsert_patient(
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
            preview_path = dicom_to_jpeg(
                dcm=dcm,
                output_dir=os.path.join(patient_dir, "previews"),
                instance_uid=meta["SOPInstanceUID"]
            )

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

        except Exception as e:
            errors.append({
                "file": filename,
                "error": str(e)
            })

    db.session.commit()
    
    # Log activity
    log_activity(
        'upload_folder', 
        resource=f'patient_{patient_id}',
        details=f'Uploaded {len(created_files)} files to ward {ward_id}'
    )

    return jsonify({
        "message": "Folder processed",
        "created": created_files,
        "errors": errors,
        "patient_id": patient_id,
        "ward_id": ward_id
    })