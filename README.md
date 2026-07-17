# asolaria-video-math-tournament

Mathematical experiments on video-recorded objects, run as an inverse-geometry
**tournament** in GitHub Actions containers. This repository is public; the
raw videos are **not** in it â€” only a derived, deterministic slice corpus.

## What this is

Three pinned video sources (two YouTube materializations + one official
DVIDS/DOD release) are reduced, on the seat that holds the pinned bytes, to a
public **derived-slice corpus**: 320-wide 8-bit gray P5 slices at exactly
`n * 0.100 s` cadence (nearest decoded best-effort PTS, deterministic
tie-breaking), concatenated per source into one `pgmstream` with per-slice
byte-range + SHA-256 receipts.

The stream is compressed with **SGRAM** (Streaming GitRAM) â€” the owning
implementation is vendored at a pinned commit from
`JesseBrown1980/asolaria-cube-cloud` `hutter/sgram/sgram_mix.rs @ 45cc3b3`:
block-streaming I/O, bounded RAM, archive byte-identical to the non-streaming
`mix` codec, roundtrip verified by streaming SHA-256.

Cloud jobs then run the math:

| job | question |
|---|---|
| `verify-corpus` | does the published corpus verify byte-for-byte (SGRAM roundtrip + per-slice SHA + PTS arithmetic)? |
| `nullspace` | do tracked bright-node trajectories form a rank â‰¤ 3 centered measurement matrix (Tomasiâ€“Kanade rigid-body test)? |
| `tournament` | which hypothesis C0â€“C8 survives forward-render / reverse-readback against held-out frames after MDL/BIC charge? |
| `sector12` | independent re-detection: is any N-fold angular symmetry supported, and does detection track brightness (artifact) or angle (structure)? |

Every job emits HBP/HBI tuple receipts (`KIND|k=v|...|json=0`) and a fan-in
job seals a combined omega over all receipt hashes.

## Hard scope (claims gate)

`fire=0`, `physical_claim=0`, `object_identity_claim=0`,
`authenticity=UNRESOLVED` on every artifact. Outputs are geometry and
coupling **measurements**, never identity, provenance, or authenticity
verdicts. Prior measured results on this footage (12-sector model
DISCONFIRMED on `star_oe9`; rigid object-locked grid NOT SUPPORTED on
PR-038) are inputs to be independently re-tested, not conclusions to defend.

## Cross-seat verification

Seats hold **different byte-materializations** of the same content (different
encodings). Raw bytes are pinned per seat in `contract/PROJECT-CONTRACT.hbp`;
cross-seat agreement is checked at the **derived-slice commitment level**, per
the shared-anchor doctrine: one canonical derived object, many physical
materializations.

## Layout

```
contract/            PROJECT-CONTRACT.hbp/.hbi  (predeclared, deterministic)
corpus/              <source>.sgram + <source>-SLICES.hbp/.hbi + sha sidecars
tools/               slice_extract.py (local-only), verify_slices.py,
                     nullspace_rank3.py, tournament.py, sector12_redetect.py,
                     hbp.py, sgram/sgram_mix.rs (vendored @ 45cc3b3)
.github/workflows/   video-math.yml (the Actions matrix)
results/             harvested receipts from completed runs
```

## Reproduce

```bash
python3 tools/build_contract.py                 # deterministic contract bytes
rustc -O tools/sgram/sgram_mix.rs -o sgram_mix  # the SGRAM codec
./sgram_mix decompress corpus/<id>.sgram <id>.pgmstream
sha256sum -c corpus/<id>.pgmstream.sha256
python3 tools/verify_slices.py --corpus corpus --source-id <id>
```

Raw-media extraction (`tools/slice_extract.py`) runs only on a seat holding a
pinned materialization; the ffmpeg build is recorded in the slice receipts.
Cloud jobs verify published bytes â€” they never re-derive from raw.
## Sealed lane handoff docs

- [LIRIS fan-in summary](docs/liris_fanin_sealed_summary.md): CI-run outcomes, SHA row references, and MEASURED/CANON/UNVERIFIED interpretation.
- [Quanted-omega commutative protocol](docs/omegabridge_commutative_protocol.md): typed-lattice framing and acceptance conditions with deterministic transition maps.
- [40-scout evidence atlas](docs/scout_evidence_atlas.md): metadata structure for multi-scout synthesis and required evidence provenance.
