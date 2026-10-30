#!/usr/bin/env bash
# Explicit deployment recovery; no login, model probes, or transcript replay.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$HERE/env.sh"
echo '== [1/3] verify pixi environment and pinned DSH =='
bash "$HERE/bootstrap.sh"
echo '== [2/3] restart services recorded in the autostart manifest =='
AUTO="$DANUS_RUNTIME/run/autostart"
if [ -s "$AUTO" ]; then
  while read -r service argument extra; do
    [ -n "$service" ] || continue
    case "$service" in
      verify) bash "$HERE/services.sh" up verify ;;
      dashboard) [ -n "$argument" ] && [ -z "$extra" ] || { echo 'invalid dashboard autostart row' >&2; exit 1; }
        bash "$HERE/services.sh" up dashboard "$argument" ;;
      *) echo "unknown autostart service: $service" >&2; exit 1 ;;
    esac
  done < "$AUTO"
else
  echo 'No autostart manifest; nothing started.'
fi
echo '== [3/3] read-only health =='
bash "$HERE/doctor.sh"
echo 'Recovery checks complete. Resume mathematical projects from their saved facts/checkpoints with a fresh main task.'
