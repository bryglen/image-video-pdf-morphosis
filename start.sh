#!/bin/bash
set -e

cd "$(dirname "$0")"

# Clear orphaned converter temp dirs before starting (non-interactive).
./clean_temp.sh -y || true

# Use local venv if present, otherwise fall back to image_convert's venv
if [ -d ".venv" ]; then
  source ".venv/bin/activate"
elif [ -d "image_convert/.venv" ]; then
  source "image_convert/.venv/bin/activate"
fi

python3 server.py &
SERVER_PID=$!

for i in $(seq 1 20); do
  if curl -s http://localhost:5002/ > /dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

open http://localhost:5002

echo "Media Converter running at http://localhost:5002 (PID $SERVER_PID)"
echo "Press Ctrl+C to stop."

wait $SERVER_PID
