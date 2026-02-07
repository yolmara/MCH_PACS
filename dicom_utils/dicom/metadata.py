def extract_metadata(dcm):
    return {
        "PatientName": getattr(dcm, "PatientName", None),
        "PatientSex": getattr(dcm, "PatientSex", None),
        "PatientBirthDate": getattr(dcm, "PatientBirthDate", None),

        "StudyInstanceUID": dcm.StudyInstanceUID,
        "StudyDate": getattr(dcm, "StudyDate", None),
        "StudyDescription": getattr(dcm, "StudyDescription", None),

        "SeriesInstanceUID": dcm.SeriesInstanceUID,
        "Modality": getattr(dcm, "Modality", None),

        "SOPInstanceUID": dcm.SOPInstanceUID,
    }
