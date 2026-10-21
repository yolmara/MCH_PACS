"""
One-time migration: push every DICOM under static/uploads into Orthanc.
 
Run inside the flask-app container (static/uploads is bind-mounted there):
 
  # test on one patient folder first
  docker compose exec -T flask-app python - /app/static/uploads/MCH000213 <orthanc-password> < migrate_to_orthanc.py
 
  # then everything
  docker compose exec -T flask-app python - /app/static/uploads <orthanc-password> < migrate_to_orthanc.py
 
Safe to re-run: Orthanc recognises instances it already has.
"""
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
 
root = sys.argv[1] if len(sys.argv) > 1 else "/app/static/uploads"
password = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("ORTHANC_ADMIN_PASSWORD", "")
user = os.environ.get("ORTHANC_ADMIN_USERNAME", "admin")
base = os.environ.get("ORTHANC_API_URL", "http://orthanc:8042").rstrip("/")
auth = "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()
 
 
def collect(folder_root):
    paths = []
    for folder, dirs, files in os.walk(folder_root):
        # Skip generated JPEG previews and report screenshots
        dirs[:] = [d for d in dirs if d not in ("previews", "reports")]
        paths += [
            os.path.join(folder, f) for f in files if f.lower().endswith(".dcm")
        ]
    return paths
 
 
def push(path):
    try:
        with open(path, "rb") as fh:
            body = fh.read()
        req = urllib.request.Request(f"{base}/instances", data=body, method="POST")
        req.add_header("Authorization", auth)
        req.add_header("Content-Type", "application/dicom")
        with urllib.request.urlopen(req, timeout=120) as resp:
            status = json.loads(resp.read()).get("Status", "Unknown")
        return path, status
    except urllib.error.HTTPError as e:
        return path, f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001
        return path, f"Error: {e}"
 
 
files = collect(root)
print(f"Found {len(files)} DICOM files under {root}")
 
counts = {}
failed = []
with ThreadPoolExecutor(max_workers=4) as pool:
    for i, (path, status) in enumerate(pool.map(push, files), 1):
        counts[status] = counts.get(status, 0) + 1
        if status not in ("Success", "AlreadyStored"):
            failed.append((path, status))
        if i % 200 == 0 or i == len(files):
            print(f"{i}/{len(files)}  {counts}")
 
print("Done.", counts)
for path, status in failed[:20]:
    print("FAILED:", status, path)
 