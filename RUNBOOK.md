# Runbook

## 1) Secrets And Environment
1. Copy example variables:
   - `cp .env.example .env`
2. Replace all `change-me-*` values in `.env`.
3. Set `OHIF_VIEWER_URL` to the URL clients should use for OHIF.
   - Example for LAN deployment: `http://192.168.1.50:8080`
4. Generate strong values:
   - `openssl rand -hex 32` for `SECRET_KEY`
   - `openssl rand -hex 32` for `ORTHANC_NOTIFY_TOKEN`
   - use a strong random password for `POSTGRES_PASSWORD` and `ORTHANC_ADMIN_PASSWORD`

## 2) Local Development (Docker)
1. Ensure Docker is running.
2. Start stack:
   - `docker compose up --build`
3. Services:
   - Flask (host local): `http://127.0.0.1:5000`
   - OHIF: `http://localhost:8080`
   - Nginx (LAN-facing app + `/dicomweb`): `http://localhost:8081`
   - Orthanc REST (host local): `http://127.0.0.1:8042`
   - DICOM C-STORE receiver: `tcp://<server-ip>:4242`

## 3) Production Runtime (Gunicorn)
- Flask container now runs with Gunicorn (not Flask dev server).
- Default Gunicorn runtime values:
  - `GUNICORN_WORKERS=4`
  - `GUNICORN_TIMEOUT=180`
- Adjust in `.env` based on CPU/RAM.

## 4) Linux Server LAN Deployment
1. Set static IP on server NIC (example Ubuntu Netplan):
   - `/etc/netplan/01-pacs.yaml`
   - Use your real interface name (`ip a`) and LAN values.
2. Apply network:
   - `sudo netplan try`
   - `sudo netplan apply`
3. Firewall (UFW):
   - `sudo ufw default deny incoming`
   - `sudo ufw default allow outgoing`
   - `sudo ufw allow 22/tcp`
   - `sudo ufw allow 4242/tcp`
   - `sudo ufw allow 8080/tcp`
   - `sudo ufw allow 8081/tcp`
   - `sudo ufw allow from <lan-cidr> to any port 8042 proto tcp`
   - `sudo ufw enable`
   - `sudo ufw status numbered`

## 5) Siemens Syngo Target Settings
Configure PACS destination on the modality:
- AE Title: value of `ORTHANC_AET` (default `MCH_PACS`)
- Host/IP: PACS Linux server static IP
- Port: `4242`
- Protocol: DICOM C-STORE

## 6) Bring Up And Verify
1. Build and start:
   - `docker compose up -d --build`
2. Check service status:
   - `docker compose ps`
3. Check logs:
   - `docker compose logs -f flask-app orthanc nginx`
4. Verify ports from another LAN host:
   - `nc -zv <pacs-server-ip> 4242`
   - `nc -zv <pacs-server-ip> 8080`
   - `nc -zv <pacs-server-ip> 8081`

## Data Paths
- DICOM uploads: `static/uploads/<patient_id>/`
- JPEG previews: `static/uploads/<patient_id>/previews/`

## Common Tasks
- DB init runs in `app.py` startup.
- Migrations live in `migrations/`.
- Fix legacy missing `.dcm` extensions: `fix_existing_files.py`.

## Common Issues
- OHIF cannot find studies:
  - Ensure nginx is up and reachable on `8081`.
  - Ensure OHIF can reach `http://<server-ip>:8081/dicomweb`.
- WADO/QIDO CORS errors:
  - Check `docker/nginx/nginx.conf`.
- Missing previews:
  - Verify `dicom_utils/dicom/convert.py` can read pixel data.
  - Verify write permissions under `static/uploads/`.
