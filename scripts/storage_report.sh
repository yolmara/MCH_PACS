#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VOLUME_NAME="${1:-mch_pacs_orthanc-storage}"

echo "== Orthanc Volume =="
if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  MOUNTPOINT=$(docker volume inspect -f '{{ .Mountpoint }}' "$VOLUME_NAME")
  echo "Volume: $VOLUME_NAME"
  echo "Mount:  $MOUNTPOINT"
  du -sh "$MOUNTPOINT" 2>/dev/null || echo "du failed (check permissions)"
  df -h "$MOUNTPOINT" | sed -n '1,2p'
else
  echo "Volume not found: $VOLUME_NAME"
fi

echo ""
echo "== PACS Uploads =="
PACS_DIR="${PACS_UPLOAD_DIR:-$ROOT_DIR/static/uploads}"
if [ -d "$PACS_DIR" ]; then
  echo "Path:   $PACS_DIR"
  du -sh "$PACS_DIR" 2>/dev/null || echo "du failed (check permissions)"
  df -h "$PACS_DIR" | sed -n '1,2p'
else
  echo "Upload directory not found: $PACS_DIR"
fi
