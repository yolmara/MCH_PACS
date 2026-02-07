import os
import re
from pathlib import Path
from typing import Optional

# Default base upload directory relative to project root.
# You can override by passing base argument to functions or by setting env var UPLOAD_BASE.
DEFAULT_BASE = os.environ.get("UPLOAD_BASE", os.path.join("static", "uploads", "patients"))

# -------------------------
# Helpers
# -------------------------
def _sanitize_component(s: str) -> str:
    """
    Remove characters that are dangerous in file/path names.
    Keep letters, numbers, dash, underscore, dot.
    """
    if s is None:
        return "unknown"
    s = str(s)
    s = s.strip()
    # replace spaces with underscore, remove unwanted chars
    s = re.sub(r"\s+", "_", s)
    s = re.sub(r"[^A-Za-z0-9_.-]", "", s)
    if s == "":
        return "unknown"
    return s


def _abs_base(base: Optional[str]) -> str:
    """Return absolute base path to use for storage."""
    b = base if base else DEFAULT_BASE
    # If relative, interpret relative to project root (cwd).
    if not os.path.isabs(b):
        b = os.path.join(os.getcwd(), b)
    return os.path.abspath(b)


# -------------------------
# Path builders
# -------------------------
def get_patient_folder(patient_id: str, base: Optional[str] = None) -> str:
    """
    Return the folder path for a patient (does not create it).
    Example: /path/to/project/static/uploads/patients/12345
    """
    pid = _sanitize_component(patient_id)
    base_abs = _abs_base(base)
    return os.path.join(base_abs, pid)


def get_study_folder(patient_id: str, study_uid: str, base: Optional[str] = None) -> str:
    """
    Return path to a study folder for a patient.
    Example: .../patients/12345/1.2.840.113619.2.1
    """
    study = _sanitize_component(study_uid)
    return os.path.join(get_patient_folder(patient_id, base), study)


def get_series_folder(patient_id: str, study_uid: str, series_uid: str, base: Optional[str] = None) -> str:
    """
    Return path to a series folder.
    Example: .../patients/12345/<study_uid>/series_<series_uid>
    """
    series = _sanitize_component(series_uid)
    # keep series folder naming explicit to avoid collisions
    return os.path.join(get_study_folder(patient_id, study_uid, base), f"series_{series}")


def build_instance_path(patient_id: str, study_uid: str, series_uid: str, sop_uid: str,
                        base: Optional[str] = None, ext: str = ".dcm") -> str:
    """
    Return full filesystem path for an instance (file).
    Example:
      .../patients/12345/<study_uid>/series_<series_uid>/1.2.3.4.5.dcm
    """
    sop = _sanitize_component(sop_uid)
    series_folder = get_series_folder(patient_id, study_uid, series_uid, base)
    filename = f"{sop}{ext if ext.startswith('.') else '.' + ext}"
    return os.path.join(series_folder, filename)


def ensure_dirs_for_instance(patient_id: str, study_uid: str, series_uid: str, base: Optional[str] = None) -> str:
    """
    Create directories for patient/study/series and return the series folder path.
    """
    series_folder = get_series_folder(patient_id, study_uid, series_uid, base)
    os.makedirs(series_folder, exist_ok=True)
    return series_folder


def relpath_from_static(fs_path: str, static_folder: Optional[str] = None) -> Optional[str]:
    """
    Convert an absolute filesystem path to a path relative to Flask's static folder.

    Returns e.g. 'uploads/patients/123/1.2.3/series_xxx/1.2.3.4.dcm'
    or None if fs_path is not inside the static_folder.
    """
    if static_folder is None:
        # assume default static folder at <cwd>/static
        static_folder = os.path.join(os.getcwd(), "static")

    try:
        fs_abs = os.path.abspath(fs_path)
        static_abs = os.path.abspath(static_folder)
        if not fs_abs.startswith(static_abs):
            return None
        rel = os.path.relpath(fs_abs, static_abs)
        return rel.replace(os.path.sep, "/")
    except Exception:
        return None
