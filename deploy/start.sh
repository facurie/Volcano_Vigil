#!/usr/bin/env bash
# The Space container's entry point (docs/DEPLOY.md): restore the state, start the dashboard, catch up on the frames
# missed while the Space was down, then run the live services next to the state saver.
set -uo pipefail

BUCKET=facurie/vigil-state

# The disk is empty at every start. If a restore fails, stop: the Hub restarts the Space, and no service ever runs
# on an empty database that the next save would put over the bucket's good copy, forgetting the day's spend.
vigil-persist restore --bucket "$BUCKET" || exit 1
vigil-mirror pull --episode 55 --repo facurie/volcano-vigil-ep55 || exit 1

vigil-web --host 0.0.0.0 --port 7860 &
web_pid=$!

# Frames from the last 24 h that AshCam still has, so the first hours the pipeline tracks are complete.
vigil-ingest --once --lookback-hours 24 || echo "catch-up failed; the ingest service below retries" >&2

# Run a service again whenever it exits (for example, the pipeline before MODEL_API_KEY is set). A TERM to the
# supervisor stops the service too.
supervise() {
  child=""
  trap 'kill "$child" 2>/dev/null; wait "$child"; exit 0' TERM
  while true; do
    "$@" &
    child=$!
    wait "$child"
    echo "$1 exited with status $?; restarting in 10 s" >&2
    sleep 10 &
    child=$!
    wait "$child"
  done
}
supervise vigil-ingest --lookback-hours 24 &
ingest_pid=$!
supervise vigil-pipeline --volcano kilauea &
pipeline_pid=$!
vigil-persist run --bucket "$BUCKET" --interval 300 &
persist_pid=$!

# On a stop, first stop the services that write, so the saver's last save (on SIGTERM) sees the database and the
# files agree; then the dashboard.
stop() {
  trap '' TERM INT
  kill "$ingest_pid" "$pipeline_pid" 2>/dev/null
  wait "$ingest_pid" "$pipeline_pid"
  kill "$persist_pid" 2>/dev/null && wait "$persist_pid"
  kill "$web_pid" 2>/dev/null
  exit "${1:-0}"
}
trap stop TERM INT

wait "$web_pid"
echo "the dashboard exited with status $?; stopping the Space" >&2
stop 1
