#!/bin/bash
cd "$(dirname "$0")"

PID=$(lsof -ti tcp:5002)

if [ -z "$PID" ]; then
  echo "No server running on port 5002."
  exit 0
fi

# Clean up converter temp dirs before freeing the port (non-interactive).
./clean_temp.sh -y || true

kill "$PID"
echo "Server stopped (PID $PID)."
