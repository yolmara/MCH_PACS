# Runbook

## Local Development (Docker)
1. Ensure Docker is running
2. Start stack:
   - `docker-compose up --build`
3. Services
   - Flask: `http://localhost:5000`
   - OHIF: `http://localhost:8080`
   - Nginx (proxy + dicomweb): `http://localhost:8081`

## Environment
- Database URL defaults to:
  `postgresql+psycopg2://coder911:coder.03@db:5432/pacsdb`
- Override with `DATABASE_URL`

## Data Paths
- DICOM uploads: `static/uploads/<patient_id>/`
- JPEG previews: `static/uploads/<patient_id>/previews/`

## Common Tasks
- Initialize database: handled in `app.py` on startup
- Migrations: `migrations/` (Alembic)
- Fix missing .dcm extensions: `fix_existing_files.py`

## Common Issues
- OHIF cannot find studies:
  - Check `docker/ohif/app-config.js` points to `http://localhost:8081/dicomweb`
  - Ensure nginx container is running
- WADO / QIDO CORS errors:
  - Check `docker/nginx/nginx.conf`
- Missing previews:
  - Ensure `dicom_utils/dicom/convert.py` can read pixel data
  - Verify write permissions to `static/uploads/`
