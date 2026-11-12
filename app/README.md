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

- Geographies: census tracts, counties & independent cities, towns & places
  (incorporated + CDPs), and ZIP code areas (ZCTAs, 2016–20 only: Census
  published none for 2006–10). Each is Census's own published estimate for that
  geography, not a sum of tracts.
- Measures: the cube's means, percents and counts, per vintage (2006–10, 2016–20).
- Dollars are shown as published in each vintage's own dollars. No deflation yet.
- Quintile breaks over tracts that are not low-reliability.
- Reliability per spec 05: CV = (MOE / 1.645) / estimate. Above 40% the tract is
  hatched, not colored; 12–40% is flagged in the inspector.
- Light/dark themes per spec 07, following the system setting until toggled.

Libraries from CDNs, pinned: MapLibre GL 5.24.1, hyparquet 1.31.5,
hyparquet-compressors 1.1.2 (the cube is zstd).

## Accessibility (WCAG 2.2 AA)

- Every map value is also in the **table view**: search by county, city or
  GEOID, sort by any column, and "Show on map" zooms to and selects the tract.
  A skip link (first Tab stop) goes straight to the table's search box.
- Keyboard: everything is reachable by Tab. Vintage and view are native radio
  groups (arrow keys). The map pans with arrow keys and zooms with + and −.
- Color is never the only channel: the inspector and table give each tract's
  value, margin, CV, reliability and fifth in words. Low reliability is a hatch
  pattern. The ramp is one hue stepping in lightness, safe for color-blind readers.
- Text clears 4.5:1 and control borders 3:1 in both themes (token changes are
  recorded in spec 07). `prefers-reduced-motion` turns off recolor fades and
  map fly-to animation. Targets are at least 24 px.
- Checked with axe-core 4.10 (WCAG 2.0/2.1/2.2 A and AA plus best practice) in
  both themes, in map and table views, with no violations, and with a scripted
  keyboard-only run. Automated checks catch only part of WCAG; a screen-reader
  pass (NVDA or VoiceOver) by a person is still due.
