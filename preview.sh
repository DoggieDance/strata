#!/usr/bin/env bash
# Run the STRATA local preview: builds whatever is missing, then serves the repo
# at http://127.0.0.1:${PORT:-8000}/app/  (add HOST=0.0.0.0 to reach it from a phone on your Wi-Fi)
set -euo pipefail
cd "$(dirname "$0")"
PY=.venv/bin/python
[ -x "$PY" ] || { echo "No .venv. See etl/README.md (Local run)."; exit 1; }
for v in 2016-2020 2006-2010; do
  if [ ! -f "build/acs/$v/tract/51.parquet" ]; then
    $PY -m etl.fetch_summary_file --vintage "$v"
    $PY -m etl.build_cube --states 51 --vintages "$v" --out build/
  fi
  [ -f "build/geo/$v/tract/51.geojson" ] || $PY -m etl.build_geometry --states 51 --vintages "$v"
done
HOST=${HOST:-127.0.0.1}; PORT=${PORT:-8000}
URL="http://127.0.0.1:$PORT/app/"
echo "STRATA preview: $URL   (Ctrl+C to stop)"
( sleep 1; command -v xdg-open >/dev/null && xdg-open "$URL" >/dev/null 2>&1 || true ) &
exec python3 -m http.server "$PORT" --bind "$HOST"
