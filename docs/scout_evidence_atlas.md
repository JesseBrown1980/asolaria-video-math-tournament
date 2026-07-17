# Scout evidence atlas (40-scout synthesis packet)

This lane keeps scout conclusions traceable to explicit evidence anchors.
No scout is allowed to reason from a “narrative only” view.

## Shared anchors

- External hardware result context (paper):
  - arXiv:2602.10695v1, SHA-256 `95febbd44ed31c9072acedee156c928f27ce38fffcc159696f3c864d6dafa755`
- Physical-law lane anchors:
  - Metatagging PR#6 (law + formula route context)
  - Algorithms PR#20 (formula-index lane context)
- SGRAM route anchor:
  - `JesseBrown1980/asolaria-cube-cloud@45cc3b3/hutter/sgram/sgram_mix.rs`

## 40-scout structure

Scouts are grouped into five independent evidence groups, 8 scouts each:

1. Contract/language correctness and row semantics
2. Slice extraction and PTS cadence integrity
3. Tracking and nullspace behavior
4. Sector-12 re-detection behavior under perturbation
5. C0–C8 tournament scoring and MDL/BIC comparison

## Expected output schema per scout

Each scout must provide:

- status: `MEASURED` / `CANON` / `UNVERIFIED` / `DISPROVED`
- one-line conclusion
- evidence rows read (hbp/hbi file names)
- failure witness if not supported

## Current local state

- No scout-result payloads are yet checked into this repo.
- A bootstrap packet is available in `tools/scout_bootstrap.py` and
  `artifacts/scout-bootstrap.json` should be emitted before the next run.
- This is required so the subsequent design-seat memo can cite peer conclusions
  without “off-line inference.”
