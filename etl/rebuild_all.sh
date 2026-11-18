#!/usr/bin/env bash
# Rebuild every period, state and level into a side folder, in parallel, then
# leave it for tests before it is swapped in for build/. Resumable: each step
# skips outputs that already exist (vintages accumulate; nothing is overwritten).
#
#   OUT=build-v8 JOBS=4 etl/rebuild_all.sh
#
# Steps: fetch -> crosswalks -> cubes -> harmonized cubes -> geometry ->
# national layers -> manifest -> data dictionary.
set -uo pipefail
cd "$(dirname "$0")/.."
PY=.venv/bin/python
OUT=${OUT:-build-v8}
JOBS=${JOBS:-4}
STATES=$($PY -c 'from etl.common import parse_states; print(" ".join(parse_states("all")))')
VINTAGES=$($PY -c 'from etl.common import load_summary_files; print(" ".join(sorted(load_summary_files()["vintages"])))')
mkdir -p "$OUT/logs"
log() { echo "$(date +%H:%M:%S) $*"; }

# Geometry of 2016-2020 does not depend on the measures: reuse it if present.
[ -d "$OUT/geo" ] || { [ -d build/geo ] && cp -al build/geo "$OUT/geo"; }

levels_for() {  # vintage -> levels Census published for it
  $PY - "$1" <<'EOF'
import sys
from etl.common import LevelUnavailable, level_cfg
out = []
for lv in ("tract", "county", "place", "zcta"):
    try:
        level_cfg(sys.argv[1], lv); out.append(lv)
    except LevelUnavailable:
        pass
print(",".join(out))
EOF
}

log "fetch"
for v in $VINTAGES; do
  lv=$(levels_for "$v")
  if [ "$($PY -c "from etl.common import vintage_format; print(vintage_format('$v'))")" = sequence ]; then
    printf '%s\n' $STATES | xargs -P "$JOBS" -I{} sh -c "$PY -m etl.fetch_summary_file --vintage $v --levels $lv --states {} >> $OUT/logs/fetch-$v-{}.log 2>&1 || echo 'FAIL fetch $v {}'"
  else
    $PY -m etl.fetch_summary_file --vintage "$v" --levels "$lv" --states 51 >> "$OUT/logs/fetch-$v.log" 2>&1 || echo "FAIL fetch $v"
  fi
done

log "crosswalks"
printf '%s\n' $STATES | xargs -P "$JOBS" -I{} sh -c "[ -e $OUT/crosswalk/2010-2020/tract/{}.parquet ] || $PY -m etl.crosswalk --states {} --out $OUT >> $OUT/logs/xwalk-{}.log 2>&1 || echo 'FAIL crosswalk {}'"

log "cubes"
for v in $VINTAGES; do
  lv=$(levels_for "$v")
  printf '%s\n' $STATES | xargs -P "$JOBS" -I{} sh -c "
    for l in \$(echo $lv | tr ',' ' '); do
      [ -e $OUT/acs/$v/\$l/{}.parquet ] || $PY -m etl.build_cube --states {} --vintages $v --levels \$l --out $OUT >> $OUT/logs/cube-$v-{}.log 2>&1 || echo \"FAIL cube $v \$l {}\"
    done"
done

log "harmonize"
for v in $($PY -c 'from etl.harmonize import on_2010_tracts; print(" ".join(on_2010_tracts()))'); do
  printf '%s\n' $STATES | xargs -P "$JOBS" -I{} sh -c "[ -e $OUT/harmonized/$v/tract-2020/{}.parquet ] || $PY -m etl.harmonize --states {} --vintages $v --out $OUT >> $OUT/logs/harm-$v-{}.log 2>&1 || echo 'FAIL harmonize $v {}'"
done

log "geometry"
for v in $VINTAGES; do
  lv=$(levels_for "$v")
  printf '%s\n' $STATES | xargs -P "$JOBS" -I{} sh -c "
    for l in \$(echo $lv | tr ',' ' '); do
      [ -e $OUT/geo/$v/\$l/{}.geojson ] || [ ! -e $OUT/acs/$v/\$l/{}.parquet ] || $PY -m etl.build_geometry --states {} --vintages $v --levels \$l --out $OUT >> $OUT/logs/geo-$v-{}.log 2>&1 || echo \"FAIL geo $v \$l {}\"
    done"
done

log "connecticut 2020-24 tract codes"
[ -e "$OUT/harmonized/2020-2024/tract-2020/09.parquet" ] || [ ! -e "$OUT/geo/2020-2024/tract/09.geojson" ] || $PY -m etl.ct_tracts --out "$OUT" >> "$OUT/logs/ct.log" 2>&1 || echo "FAIL ct_tracts"

log "national layers"
$PY -m etl.national --out "$OUT" >> "$OUT/logs/national.log" 2>&1 || echo "FAIL national"
log "manifest"
$PY -m etl.write_manifest --out "$OUT" >> "$OUT/logs/manifest.log" 2>&1 || echo "FAIL manifest"
log "done"
