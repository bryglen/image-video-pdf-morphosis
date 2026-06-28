#!/bin/bash
cd "$(dirname "$0")"

PORT=5002

pids_on_port() {
  lsof -ti tcp:$PORT 2>/dev/null
}

PIDS=$(pids_on_port)

if [ -z "$PIDS" ]; then
  echo "No server running on port $PORT."
  exit 0
fi

# Clean up converter temp dirs before freeing the port (non-interactive).
./clean_temp.sh -y || true

# Graceful first: SIGTERM every PID bound to the port (server + any child
# ffmpeg processes). Unquoted on purpose so multiple PIDs word-split.
echo "Stopping PID(s) on port $PORT: $(echo "$PIDS" | tr '\n' ' ')"
kill $PIDS 2>/dev/null || true

# Wait up to ~3s for the port to free, then force-kill any stragglers.
for _ in $(seq 1 15); do
  PIDS=$(pids_on_port)
  [ -z "$PIDS" ] && break
  sleep 0.2
done

PIDS=$(pids_on_port)
if [ -n "$PIDS" ]; then
  echo "Still alive — force killing: $(echo "$PIDS" | tr '\n' ' ')"
  kill -9 $PIDS 2>/dev/null || true
  sleep 0.3
fi

if [ -n "$(pids_on_port)" ]; then
  echo "Failed to free port $PORT."
  exit 1
fi

echo "Server stopped; port $PORT is free."
