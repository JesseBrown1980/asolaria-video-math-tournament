# MEASURED Report: Native-resolution background patch tracking (relic seat)

## Scope and provenance

- `MEASURED` source clip (local): `C:\\tmp\\relic-uap-2559449011145341.mp4`
- `SHA256`: `CF0F161BBAE03926BFC852C2E675295E544A0B5D57EF8F86DAC3D51DB0C99CD4`
- `MEASURED` frame count: `72`
- `MEASURED` clip duration: `72.0 s` (1 fps extraction)
- `MEASURED` geometry: `1920x1080` (native resolution)
- `MEASURED` method: baseline-difference patch tracking in full-resolution ROI, star centroid track, framewise centroids + distance
- `MEASURED` ROI used for patch tracking: `x[0,520), y[80,420)`

This is a full-resolution run only. It is explicitly **not** the full ~106.4s public seat clip that was discussed earlier.

## Gate tags

- `MEASURED`
- `fire=0`
- `physical_claim=0`
- `object_identity_claim=0`
- `authenticity=UNRESOLVED`

## Core measured outputs

- `star_patch_dist` (patch centroid to star centroid, px):
  - finite samples: `71`
  - min: `62.0554`
  - max: `1411.4752`
  - mean: `656.9527`
  - stddev: `317.1032`
- Patch total motion (centroid displacement from frame 0 to frame 71): `102.007 px`
- Star total motion (centroid displacement from frame 0 to frame 71): `151.672 px`
- `patch_area` observed range: `64` to `2118`
- `patch_area` top frame in 20–60s windows: around frame 39 (`t≈39s`, area `2118`, `cx=132.8`, `cy=341.3`)

### Top tracked area snapshots (`native_patch_top20_by_area.csv`)

Included in this folder:

- `native_patch_track_v3.csv` (full 72-frame framewise trace)
- `native_patch_top20_by_area.csv` (top 20 by `patch_area`)
- `native_patch_summary.txt` (full numeric summary)

## Constant-distance test (pendulum-style hypothesis)

The centroid distance between tracked patch and tracked star is **not constant** on this run.

- Distance varies over a wide range (`62.0554` to `1411.4752`) with high spread (`317.1032`).
- This measured spread is inconsistent with strict constant-length separation.
- No single-frame tracking identity check here was interpreted as a geometric identity claim; this is geometry/measurement output only.

## Notes

- This is a diagnostic, high-resolution tracking pass intended for inspection and follow-up, with no causal interpretation attached.
- If you want a full 106+ second native pass, the clip used in this run must be replaced with the longer pinned 106s source and this script rerun.
