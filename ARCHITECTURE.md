# Architecture

## High-Level Overview
- Flask application exposes UI pages and DICOMweb endpoints.
- PostgreSQL stores patients, studies, series, instances, RIS orders, reports, users, wards.
- Filesystem stores DICOMs and generated JPEG previews under `static/uploads/`.
- OHIF viewer consumes DICOMweb endpoints through nginx proxy.

## Main Components
1. Web App
- Entry: `app.py` (factory, blueprint registration, caching headers)
- Config: `config.py`

2. Data Models
- `models/Patient` -> `models/Study` -> `models/Series` -> `models/Instance`
- RIS: `models/ExamOrder`, `models/RadiologyReport`
- Admin: `models/User`, `models/Ward`, `models/Department`, `models/ActivityLog`

3. DICOM Utilities
- Read: `dicom_utils/dicom/read.py`
- Metadata: `dicom_utils/dicom/metadata.py`
- Convert: `dicom_utils/dicom/convert.py`
- Storage helpers: `dicom_utils/storage/*`
- Upserts: `dicom_utils/db/upserts.py`

4. Blueprints
- DICOMweb: `Blueprints/dicomweb/` (QIDO, WADO, STOW)
- Upload: `Blueprints/upload/` (folder upload)
- Viewer: `Blueprints/dicom/`, `Blueprints/ohif_viewer/`
- Auth: `Blueprints/auth/`
- Wards: `Blueprints/wards/`
- RIS: `Blueprints/ris/`

## Key Flows

### Upload Flow (Folder Upload)
1. `POST /upload/folder` -> `Blueprints/upload/routes.py`
2. Files saved to `static/uploads/<patient_id>/`
3. DICOM parsed, metadata extracted, preview JPEG created
4. `upsert_*` writes Patient/Study/Series/Instance

### DICOMweb QIDO (Study/Series/Instance Search)
- `GET /dicomweb/studies`
- `GET /dicomweb/studies/<study_uid>/series`
- `GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances`

### DICOMweb WADO (Retrieve)
- `GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>`
- `GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/rendered`
- `GET /dicomweb/studies/<study_uid>/series/<series_uid>/instances/<instance_uid>/frames/<frame_number>`

### DICOMweb STOW (Store)
- `POST /dicomweb/studies` -> `Blueprints/dicomweb/stow.py`

## Deployment
- `docker-compose.yml` runs Postgres, Flask, OHIF, and nginx.
- `docker/nginx/nginx.conf` proxies `/dicomweb` with CORS.
- `docker/ohif/app-config.js` points OHIF to nginx `/dicomweb`.
