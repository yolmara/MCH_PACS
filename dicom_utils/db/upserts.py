from models import Patient, Study, Series, Instance, db


class PatientIdentityConflictError(ValueError):
    """Raised when a patient_id maps to conflicting patient demographics."""


def _norm(value):
    if value is None:
        return None
    text = str(value).strip()
    return text.lower() if text else None


def _raise_if_patient_conflict(patient, name=None, sex=None, dob=None):
    conflicts = []

    existing_name = _norm(patient.patient_name)
    incoming_name = _norm(name)
    if existing_name and incoming_name and existing_name != incoming_name:
        conflicts.append(f"name existing='{patient.patient_name}' incoming='{name}'")

    existing_sex = _norm(patient.patient_sex)
    incoming_sex = _norm(sex)
    if existing_sex and incoming_sex and existing_sex != incoming_sex:
        conflicts.append(f"sex existing='{patient.patient_sex}' incoming='{sex}'")

    existing_dob = _norm(patient.patient_dob)
    incoming_dob = _norm(dob)
    if existing_dob and incoming_dob and existing_dob != incoming_dob:
        conflicts.append(f"dob existing='{patient.patient_dob}' incoming='{dob}'")

    if conflicts:
        raise PatientIdentityConflictError(
            f"PatientID '{patient.patient_id}' already exists with different demographics: "
            + "; ".join(conflicts)
        )


def upsert_patient(patient_id, name=None, sex=None, dob=None):
    patient_id = str(patient_id).strip() if patient_id is not None else ""
    if not patient_id:
        raise ValueError("patient_id is required")

    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        patient = Patient(
            patient_id=patient_id, 
            patient_name=name, 
            patient_sex=sex, 
            patient_dob=dob)
        
        db.session.add(patient)
        return patient

    _raise_if_patient_conflict(patient, name=name, sex=sex, dob=dob)

    # Fill missing demographics without overwriting existing values.
    if name and not patient.patient_name:
        patient.patient_name = name
    if sex and not patient.patient_sex:
        patient.patient_sex = sex
    if dob and not patient.patient_dob:
        patient.patient_dob = dob

    return patient
    
def upsert_study(patient, study_uid, study_date=None, description=None):
    study = Study.query.filter_by(study_instance_uid=study_uid).first()
    if study:
        return study


    study = Study(
    study_instance_uid=study_uid,
    patient=patient,
    study_date=study_date,
    description=description
    )
    db.session.add(study)
    db.session.commit()
    return study

def upsert_series(study, series_uid, modality=None, body_part=None):
    series = Series.query.filter_by(series_instance_uid=series_uid, study=study).first()
    if series:
        return series


    series = Series(
        series_instance_uid=series_uid,
        study=study,
        modality=modality,
        body_part=body_part
    )
    db.session.add(series)
    db.session.commit()
    return series



def upsert_instance(series, sop_uid, file_path, preview_path, instance_number=None):
    inst = Instance.query.filter_by(sop_instance_uid=sop_uid).first()
    if inst:
        return inst


    inst = Instance(
        sop_instance_uid=sop_uid,
        file_path=file_path,
        preview_path=preview_path,
        series=series,
        instance_number=instance_number
    )
    db.session.add(inst)
    db.session.commit()
    return inst
