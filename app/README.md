# Local preview

A no-build static page that maps the Virginia tract cubes on this machine.
Not the Phase 03 app: geometry is GeoJSON (not PMTiles), files are served
locally (not R2), and Parquet is read whole rather than by byte range.
The runtime model is the planned one — GEOID-only geometry, attributes joined
in the browser via feature state, hyparquet for the cube, no Census API calls.

```bash
./preview.sh                 # builds anything missing, opens http://127.0.0.1:8000/app/
HOST=0.0.0.0 ./preview.sh    # also reachable from a phone on the same network
```

- Measures: the cube's means, percents and counts, per vintage (2006–10, 2016–20).
- Dollars are shown as published in each vintage's own dollars. No deflation yet.
- Quintile breaks over tracts that are not low-reliability.
- Reliability per spec 05: CV = (MOE / 1.645) / estimate. Above 40% the tract is
  hatched, not colored; 12–40% is flagged in the inspector.
- Light/dark themes per spec 07, following the system setting until toggled.

Libraries from CDNs, pinned: MapLibre GL 5.24.1, hyparquet 1.31.5,
hyparquet-compressors 1.1.2 (the cube is zstd).
