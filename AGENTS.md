# AGENTS.md

This file helps collaborators (and Codex) quickly re-orient after a fresh session.

## Project Snapshot
- Project: MCH PACS (Flask + PostgreSQL + OHIF)
- Purpose: Store, index, and view DICOM studies with basic RIS and ward workflows.
- Runtime: Flask app with DICOMweb endpoints (QIDO/WADO/STOW) and OHIF viewer.
- Storage: DICOM files under `static/uploads/` with JPEG previews alongside.

## Core Structure
- App entry: `app.py` (factory, blueprint registration, DB init)
- Config: `config.py` (DB URI, upload folder)
- Models: `models/` (Patient, Study, Series, Instance, User, Ward, Department, RIS)
- DICOM utils: `dicom_utils/` (read, metadata, JPEG conversion, storage paths, upserts)
- DICOMweb: `Blueprints/dicomweb/` (QIDO, WADO, STOW)
- Uploads: `Blueprints/upload/`
- Viewer: `Blueprints/dicom/`, `Blueprints/ohif_viewer/`
- RIS: `Blueprints/ris/`
- Auth: `Blueprints/auth/`
- Wards: `Blueprints/wards/`
- UI: `templates/`, `static/style.css`

## Key Flows
- Upload: `Blueprints/upload/routes.py` -> `dicom_utils` -> DB upserts + previews
- DICOMweb QIDO: `Blueprints/dicomweb/routes.py`
- DICOMweb STOW: `Blueprints/dicomweb/stow.py`
- DICOMweb WADO: `Blueprints/dicomweb/wado.py`
- Viewer: OHIF via `docker/ohif/app-config.js` and nginx proxy

## Notes
- DICOM files are real data. Avoid scanning `static/uploads/` unless needed.
- `venv/` is present in repo; exclude it from scans.

See also:
- `ARCHITECTURE.md` for diagrams and flows
- `RUNBOOK.md` for local run instructions
- `NOTES.md` for current tasks and decisions
