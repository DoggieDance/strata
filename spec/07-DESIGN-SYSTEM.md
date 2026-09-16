# 07 — Design System

Sepia ground, editorial structure, a dark mode that is a second world rather than
an inversion. Warm paper and brown ink read as archival and unhurried, which is
the correct register for demographic data most people have never been invited to
look at.

Reference points: *In These Times* for editorial structure — kicker, headline,
deck, hairline rules, strong section labeling — and the Clean Sepia palette for
the ground.

## Tokens

```css
:root {                        /* Paper */
  --paper:#EFE4CE;  --surface:#F8F1E0;  --surface-2:#E7D9BE;
  --ink:#2E241C;    --ink-2:#6B5844;    --ink-3:#8C7A63;
  --rule:#CDB894;   --rule-soft:#DCCCAE;
  --accent:#9E2B25;                     /* oxblood */
  --cool:#2C5A5E;                       /* verdigris */
  --warn:#996515;
}

[data-theme="dark"] {          /* Vellum */
  --paper:#16110C;  --surface:#1F1812;  --surface-2:#2A2118;
  --ink:#EADCC0;    --ink-2:#B5A182;    --ink-3:#8A7962;
  --rule:#3B2E22;   --rule-soft:#2C2219;
  --accent:#DB6A57;
  --cool:#7FB3AC;
  --warn:#C79A47;
}
```

> **Open item.** These are derived from sepia conventions, not lifted from the
> Clean Sepia theme JSON — the VS Code marketplace would not surrender its
> values. Replace with the real palette when available; the token names do not
> change.

## Type

| Role | Face | Use |
|---|---|---|
| Display | **Fraunces** (SOFT / WONK engaged) | Headlines, phase numbers. Bookish, not antique. |
| Reading | **Newsreader** | Body, methodology prose. Built for screens at news sizes. |
| Data | **IBM Plex Mono** | GEOIDs, variable codes, figures, eyebrows. Tabular numerals everywhere digits align. |

No sans-serif. Serif plus mono is the academic register, and it keeps the
interface from reading like a dashboard.

## Map color

**Diverging, anchored at zero**, warm-to-cool. Red–green is never used.

```
#8C4A16  #C08A3E  #E3D3AE  #7FA9A4  #25585F
decline  ——————   mean     ——————   intensification
```

Sequential ramps for single-measure level maps use the warm half alone.
Categorical typology classes use hue, never ramp position.

**Unreliable tracts are hatched** with a 45° line pattern in `--ink-3` at low
opacity, over the tract's own color. The color still reads; the hatching says
do not trust it.

## Motion

Dynamic but stable. Transitions belong to state changes only — a recolor, a theme
switch, a panel opening. Nothing moves ambiently, nothing animates on scroll, and
the map never eases a color change longer than 180 ms because that reads as lag,
not polish.

`prefers-reduced-motion` disables all of it.

## Copy

Terse and confident. A control says exactly what happens. No poetic taglines, no
explanatory paragraphs where a label works. The interface is not the place to
teach statistics — that is what the reading room is for.

The one place prose is allowed to expand: the plain-language reading of an index,
which should sound like a person explaining a map to a friend.
