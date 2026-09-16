# Scheduled task — STRATA research

Cadence: weekly. Keeps `spec/RESEARCH-LOG.md` from going stale underneath the
architecture.

## Watch list

Everything under "Flagged — not verified" in `RESEARCH-LOG.md`, plus:

- **ACS release calendar.** Has a new 5-year vintage landed? Note the date; do
  not schedule against assumed ones.
- **Census API and Summary File policy.** Format changes, endpoint deprecations,
  new key requirements.
- **Free-tier movement.** Cloudflare R2, GitHub Pages and Actions allowances.
  These change without announcement and the whole cost argument rests on them.
- **Federal data availability.** EJScreen and CEJST both went offline in 2025.
  If an upstream source disappears, the response is to note which build artifacts
  became the archive — not to panic.
- **Upstream libraries.** MapLibre `setFeatureState` at scale, PMTiles spec,
  hyparquet, tippecanoe.

## Output

Amend `RESEARCH-LOG.md` in place. Move items between "verified" and "flagged"
with the date. **Never delete a rejected option** — the reasons are the value.

If a finding invalidates an architectural decision, do not act on it. Write it
under a new heading, flag it in `worklog.md`, and stop. Architecture changes are
a human decision.
