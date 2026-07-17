# Commutative-protocol frame for quanted-omega bridging

This document replaces the informal “omnibook” intuition with explicit, testable
operators. It is a **typed-lattice model** for software/measurement experiments only.

## 1) Lattice declaration

- **Floor axis**: `F = [64, 256, 1024, 4096]`
- **Family axis**: `A = {8_pole, 12_sector, 20_lens, path_7}`
- **Transfer axis**: `Q_{f→f'}` for deterministic quanted transitions across families

Every sample carries an annotation:

- `x = (f, level, family, seat)`
- `f ∈ F`, `family ∈ A`, `seat ∈ {ACER, LIRIS, ...}`

## 2) Deterministic transition maps

For any operator `T_{g→h}` (alignment/pose model) and quant transition
`Q_{f→f'}`, define two compositions:

- `A = T_{g→h}(Q_{f→f'}(x))`
- `B = Q_{f→f'}(T_{g→h}(x))`

The bridge claim is **not accepted** until commutator residual is within bound:

`err = d(A, B) / (|A| + |B| + ε)`

with `d` a deterministic L1/L2 metric over fixed lattice support and
`err ≤ τ` as pre-registered in contract.

## 3) Canonical acceptance conditions

- `Q_{f→f'}` must be:
  - deterministic,
  - bounded by explicit range checks,
  - side-carred in receipts via HBP/HBI rows.
- The commutative residual must be measured and reported with:
  - `commute_abs_mean`
  - `commute_abs_p95`
  - `commute_counted_pairs`
  - `commute_held_rows`
- The map is `MEASURED` until it satisfies the residual bound.

## 4) Boundary matrix (what this is *not*)

- Not a physical hardware protocol.
- Not a proof of literal quantum cloning implementation.
- Not equivalent to replacing family members by one merged ontology.
- Not a compression replacement claim.

## 5) Required claim tags per run artifact

All run artifacts in this lane must carry:

- `fire=0`
- `physical_claim=0`
- `object_identity_claim=0`
- `authenticity=UNRESOLVED`
- `json=0`

For any promoted claim, require:

- two-seat agreement (if available),
- one shared contract,
- and explicit cross-seat commutative evidence.

## 6) Integration with existing contract language

The `PROJECT-CONTRACT` should continue to carry:

- `PROMOTIONRULE: cross-seat_gate_required`
- `condition=consensus_across_two_materializations_and_one_contract`
- deterministic `sgram_route = hutter/sgram/sgram_mix.rs@45cc3b3`

This makes bridge claims falsifiable instead of narrative.
