import os

BASE_UPLOAD_DIR = "static/uploads"

def ensure_patient_folder(patient_id):
    path = os.path.join(BASE_UPLOAD_DIR, patient_id)
    os.makedirs(path, exist_ok=True)
    os.makedirs(os.path.join(path, "previews"), exist_ok=True)
    return path
