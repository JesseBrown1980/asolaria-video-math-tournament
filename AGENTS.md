# Agent guidance — asolaria-video-math-tournament

## Claims gate (non-negotiable)

- Every emitted artifact carries `fire=0`, `physical_claim=0`,
  `object_identity_claim=0`, `authenticity=UNRESOLVED`, `E=0`. Outputs are
  geometry/coupling measurements only.
- Tag every claim `MEASURED` / `CANON` / `UNVERIFIED`. A single green run is
  `MEASURED` for that run only; promotion needs the cross-seat gate
  (`PROMOTIONRULE` in `contract/PROJECT-CONTRACT.hbp`).
- The owning gate for CI state is GitHub required checks (`gh run view`),
  never a local run. The owning gate for corpus integrity is
  `tools/verify_slices.py` over published bytes.
- Never let a forward renderer "verify" a preselected shape: reconstruction
  evidence must consume the measured pixel data (the `pixel_nodes` defect
  family is banned). Negative controls are predeclared in the contract —
  run them, report them, never trim them.
- Prior measured results (12-sector DISCONFIRMED on `star_oe9`; rigid
  object-locked grid NOT SUPPORTED on PR-038) are re-testable inputs, not
  conclusions to defend or to quietly contradict.

## Format law

- Receipts are HBP tuple rows `KIND|k=v|...|json=0` (hot path; JSON is cold
  debug only). Parse by splitting on `|` then `=` — never bare substring.
  Use `tools/hbp.py`; do not re-implement.
- Raw media never enters this repository (`raw_media_in_repo=0`). Only the
  derived slice corpus and receipts are public.

## Toolchain law

- On Windows seats, use the real Linux/WSL lane for extraction and codec
  builds (`MSYS_NO_PATHCONV=1 wsl.exe`, inline `/mnt/...` paths). Cloud jobs
  run on ubuntu runners; `rustc -O tools/sgram/sgram_mix.rs` builds the codec.
- SGRAM is the pinned vendored file — commit
  `45cc3b36179b547a3f3c3b23084f30c1cbf3aec0`; do not "improve" it here.
- Floating-point results (SVD spectra, R², BIC) are recorded with explicit
  tolerances in receipts; conclusions must be tolerance-stable, not
  bit-exact-dependent.
