#!/bin/bash
set -e

BACKUP_DIR="/home/qlserver/backups"
BACKBLAZE_BUCKET="b2:qlove-db-backups"
MAX_GB=10
FILENAME="qlove_$(date +%Y%m%d_%H%M%S).dump"

mkdir -p "$BACKUP_DIR"

# Dump
docker exec qlove-qpg-1 pg_dump -U qlove_user -Fc qlove_production > "$BACKUP_DIR/$FILENAME"

# Upload to Backblaze B2
rclone copy "$BACKUP_DIR/$FILENAME" "$BACKBLAZE_BUCKET"

# Remove local file after upload
rm "$BACKUP_DIR/$FILENAME"

# Rotate: delete oldest when over MAX_GB
while true; do
  USED=$(rclone size "$BACKBLAZE_BUCKET" --json | python3 -c "import sys,json; print(json.load(sys.stdin)['bytes'])")
  LIMIT=$((MAX_GB * 1024 * 1024 * 1024))
  if [ "$USED" -le "$LIMIT" ]; then break; fi
  OLDEST=$(rclone lsf "$BACKBLAZE_BUCKET" --format "tp" | sort | head -1 | cut -d';' -f2)
  if [ -z "$OLDEST" ]; then break; fi
  rclone delete "$BACKBLAZE_BUCKET/$OLDEST"
done
