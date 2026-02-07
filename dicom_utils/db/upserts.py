from models import Patient, Study, Series, Instance, db


def upsert_patient(patient_id, name=None, sex=None, dob=None):
    patient = Patient.query.filter_by(patient_id=patient_id).first()
    if not patient:
        patient = Patient(
            patient_id=patient_id, 
            patient_name=name, 
            patient_sex=sex, 
            patient_dob=dob)
        
        db.session.add(patient)
    else:
        if name:
            patient.patient_name = name
        if sex:
            patient.patient_sex = sex
        if dob:
            patient.patient_dob = dob
            
        db.session.commit()
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