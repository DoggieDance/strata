#!/usr/bin/env bash
# Build every state in registry/states.json, skipping outputs that already
# exist (vintages accumulate; nothing is overwritten). Resumable: rerun after a
# failure and it picks up where it stopped. Logs per state to build/logs/.
#
#   etl/national.sh            # all stages
#   STAGES="cube geo" etl/national.sh
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
STAGES=${STAGES:-"fetch10 cube geo xwalk"}
OUT=${OUT:-build}   # build into a side folder, then swap, so the app never sees a half build
STATES=${STATES:-$($PY -c 'from etl.common import parse_states; print(" ".join(parse_states("all")))')}
mkdir -p "$OUT/logs"

have() { [ -e "$1" ]; }
for st in $STATES; do
  log=$OUT/logs/$st.log
  for stage in $STAGES; do
    case $stage in
      fetch10)
        $PY -m etl.fetch_summary_file --vintage 2006-2010 --levels tract,county,place --states "$st" >>"$log" 2>&1 \
          || { echo "$st fetch10 FAILED"; continue 2; } ;;
      cube)
        for v in 2016-2020 2006-2010; do for lv in tract county place zcta; do
          [ "$v" = 2006-2010 ] && [ "$lv" = zcta ] && continue
          have "$OUT/acs/$v/$lv/$st.parquet" && continue
          $PY -m etl.build_cube --states "$st" --vintages "$v" --levels "$lv" --out "$OUT" >>"$log" 2>&1 \
            || echo "$st cube $v $lv FAILED"
        done; done ;;
      geo)
        for v in 2016-2020 2006-2010; do for lv in tract county place zcta; do
          [ "$v" = 2006-2010 ] && [ "$lv" = zcta ] && continue
          have "$OUT/geo/$v/$lv/$st.geojson" && continue
          have "$OUT/acs/$v/$lv/$st.parquet" || continue
          $PY -m etl.build_geometry --states "$st" --vintages "$v" --levels "$lv" --out "$OUT" >>"$log" 2>&1 \
            || echo "$st geo $v $lv FAILED"
        done; done ;;
      xwalk)
        if ! have "$OUT/crosswalk/2010-2020/tract/$st.parquet"; then
          $PY -m etl.crosswalk --states "$st" --out "$OUT" >>"$log" 2>&1 || { echo "$st crosswalk FAILED"; continue 2; }
        fi
        if ! have "$OUT/harmonized/2006-2010/tract-2020/$st.parquet"; then
          $PY -m etl.harmonize --states "$st" --out "$OUT" >>"$log" 2>&1 || echo "$st harmonize FAILED"
        fi ;;
    esac
  done
  # Refresh the manifest so the app shows this state now (owner, 2026-11-12:
  # "im not seeing the other states yet"). The write is atomic.
  $PY -m etl.write_manifest --out "$OUT" >/dev/null 2>&1 || echo "$st manifest FAILED"
  echo "$st done"
done
