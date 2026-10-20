#!/usr/bin/env bash
# Publish the read-only serving snapshot, start the hourly refresher, then serve the dashboard.
set -u
python -m bijlicast.serving || echo "snapshot not published yet"
python -m bijlicast.space_runner &
exec uvicorn bijlicast.api:app --host 0.0.0.0 --port 7860 --proxy-headers
