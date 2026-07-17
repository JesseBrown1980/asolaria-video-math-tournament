# LIRIS lane sealed summary (video-math tournament fan-in)

## Gate status

- Commit: `5059c89eb3e454c51325b05528c8fb7af91c4aba`
- Repository: `JesseBrown1980/asolaria-video-math-tournament`
- Workflow: `29606216946` (`video-math`)
- Conclusion: **success**

## Verified receipts collected

- `FANIN-OMEGA.hbp` present and references all 12 source run receipts.
- For each source and family, verify/nullspace/sector/tournament outputs were present.
- Artifact rows are expected to remain `fire=0`, `physical_claim=0`,
  `object_identity_claim=0`, `authenticity=UNRESOLVED`, `json=0`.

## Source-level outcome (MEASURED)

| source_id       | nullspace_rigid_body_supported | sector12_best_order | sector12_twelve_fold_supported | tournament_best_hypothesis | single_run_promotes_to_canon |
|-----------------|--------------------------------|---------------------|-------------------------------|----------------------------|-------------------------------|
| pyramid_lzu     | `1`                            | `4`                 | `0`                           | `C7`                      | `0`                           |
| star_oe9        | `1`                            | `4`                 | `0`                           | `C1`                      | `0`                           |
| official_pr038  | `0`                            | `4`                 | `0`                           | `C7`                      | `0`                           |

## Fan-out SHA digest rows (short form)

- nullspace: `71a74bf645c5...` / `4c988efbecc3...` / `d50d62d3f1f2...`
- sector12: `b0590b78c45c...` / `03cc66697585...` / `b15524209b94...`
- tournament: `2af7b91e51c0...` / `50861b238eb1...` / `265597c3b187...`
- verify: `e05f39c47963...` / `da876fc477f1...` / `db95f1c9262c...`

## Interpretation policy for handoff

- `MEASURED` = receipt verified in CI and present.
- `CANON` = not yet assigned; no family outcome is promoted yet.
- `UNVERIFIED` = full Moving-Flashlight run for this lane remains
  cross-seat-gated and not considered a terminal artifact in this phase.

## Note for next seat

Treat these outcomes as a scoped geometry measurement lane:
non-identity, non-physical claims only.
