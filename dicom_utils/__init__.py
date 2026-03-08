# Expose DICOM reading utilities
from .dicom.read import load_dicom
from .dicom.metadata import extract_metadata
from .dicom.convert import dicom_to_jpeg

# Expose DB logic (patient, study, series upserts)
from .db.upserts import (
    PatientIdentityConflictError,
    upsert_patient,
    upsert_study,
    upsert_series,
    upsert_instance,
)

# Expose storage utilities (folders, pathing)
from .storage.pathing import (
    get_patient_folder,
    get_study_folder,
    get_series_folder,
    build_instance_path,
)

from .storage.patient_folder import ensure_patient_folder

__all__ = [
    # dicom
    "load_dicom",
    "extract_metadata",
    "convert_to_jpeg",

    # db upserts
    "PatientIdentityConflictError",
    "upsert_patient",
    "upsert_study",
    "upsert_series",
    "upsert_instance",

    # storage pathing
    "get_patient_folder",
    "get_study_folder",
    "get_series_folder",
    "build_instance_path",
    "ensure_patient_folder",
]
