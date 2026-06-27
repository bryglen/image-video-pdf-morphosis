#!/bin/bash
# Clean up Media Converter temp dirs.
#
# Video jobs write to per-job folders under the project-local tmp/ folder, each
# holding the uploaded original + the converted output. They are normally
# removed 60s after download, and the server also sweeps tmp/ on startup. This
# script forces a sweep now (e.g. while the server is stopped).
#
# It targets two things:
#   1. Everything under <project>/tmp/  (the current layout)
#   2. Legacy orphans: $TMPDIR/tmp* dirs containing a *_converted.* file
#      (jobs created before temp files moved into the project folder)
#
# Usage:
#   ./clean_temp.sh            # show what would be deleted, then delete
#   ./clean_temp.sh --dry-run  # show only, delete nothing
#   ./clean_temp.sh -y         # delete without the confirmation prompt

set -euo pipefail

DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    -y|--yes)     ASSUME_YES=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "Unknown option: $arg" >&2; exit 1 ;;
  esac
done

DIR="$(cd "$(dirname "$0")" && pwd)"
BASE="$DIR/tmp"

SYS_TMP="${TMPDIR:-/tmp}"
SYS_TMP="${SYS_TMP%/}"   # strip trailing slash

dirs=()

# 1. Current project-local job dirs.
if [ -d "$BASE" ]; then
  for d in "$BASE"/*; do
    [ -d "$d" ] && dirs+=("$d")
  done
fi

# 2. Legacy orphans in the system temp dir: tmp* dirs holding a converter output.
for d in "$SYS_TMP"/tmp*; do
  [ -d "$d" ] || continue
  if compgen -G "$d/*_converted.*" > /dev/null 2>&1; then
    dirs+=("$d")
  fi
done

if [ ${#dirs[@]} -eq 0 ]; then
  echo "No converter temp dirs found."
  exit 0
fi

echo "Found ${#dirs[@]} converter temp dir(s):"
for d in "${dirs[@]}"; do
  printf '  %-12s %s\n' "$(du -sh "$d" 2>/dev/null | cut -f1)" "$d"
done
total=$(du -sch "${dirs[@]}" 2>/dev/null | tail -1 | cut -f1)
echo "Total: $total"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "(dry run — nothing deleted)"
  exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  read -r -p "Delete these ${#dirs[@]} folder(s)? [y/N] " ans
  case "$ans" in
    y|Y|yes|YES) ;;
    *) echo "Aborted."; exit 0 ;;
  esac
fi

for d in "${dirs[@]}"; do
  rm -rf "$d" && echo "Deleted $d"
done
echo "Freed $total."
