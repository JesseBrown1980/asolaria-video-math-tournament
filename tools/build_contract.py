#!/usr/bin/env python3
"""Build the deterministic PROJECT-CONTRACT for the video-math tournament.

Predeclared BEFORE any cloud run: sources with per-seat materialization pins,
the cadence contract, hypothesis families C0-C8, negative controls, promotion
rules, the resolved SGRAM route, and the claims gate. Same bytes every build.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hbp import CLAIMS_GATE, hbp_row, sha256_file, write_hbp_hbi  # noqa: E402

SCHEMA = "ASOLARIA-VIDEO-MATH-TOURNAMENT-CONTRACT-V1"

# Per-seat materializations of the same content: encodings differ, so raw
# bytes differ; cross-seat verification happens at the derived-slice
# commitment level (shared-anchor doctrine).
SOURCES = (
    dict(
        source_id="pyramid_lzu",
        content="YouTube LzuUlMN4oBI (operator-hosted raw repost)",
        acer_sha256="2c893d7185c31bf6bd8f6bdb9ef2d62c30642fd47d70e9176b08c9c8f7a0c5cb",
        liris_sha256="d2611eb3d493d06548abbe0234bfb3461d179dd9abacbcd39020856c16163840",
        provenance="UNTRUSTED_INPUT",
        raw_public=0,
    ),
    dict(
        source_id="star_oe9",
        content="YouTube OE9_mAcvCT8",
        acer_sha256="0269f279b833758f89ba55666148979a827fcfcd78e15c0d0ebc13985801f07a",
        liris_sha256="0ce31c39a8dc298a9a512f0f98f73cd1cc33d0265c895ece3a8d36cc810b35b8",
        provenance="UNTRUSTED_INPUT",
        raw_public=0,
    ),
    dict(
        source_id="official_pr038",
        content="DVIDS/DOD PR-038 official release",
        acer_sha256="bd3f5269c3f123b90db76c9496f8ddbb145184c66b0c11cd3cfd9e54f5b683b6",
        liris_sha256="UNKNOWN",
        provenance="OFFICIAL_RELEASE",
        raw_public=0,
    ),
)

HYPOTHESES = (
    ("C0", "artifact", "no coherent 3D object; residuals track brightness/codec/sensor"),
    ("C1", "planar", "planar rigid patch under fitted camera"),
    ("C2", "rigid_tetra", "rigid tetrahedron (regular tested exactly; edges sqrt(8/3))"),
    ("C3", "cylinder_core", "rigid cylinder core"),
    ("C4", "torus_core", "rigid torus core (inner/outer contour dynamics must beat circle/cylinder)"),
    ("C5", "square_pyramid", "rigid square pyramid"),
    ("C6", "prism", "rigid triangular prism"),
    ("C7", "free_rigid_lattice", "free rigid point lattice (MDL-charged for extra params)"),
    ("C8", "twelve_sector_solid", "rigid 12-sector solid, 2/3 occluded; new sector every 30 deg"),
)

NEGATIVE_CONTROLS = (
    ("wrong_pose_circular_shift", "apply another frame's pose; background SAD must worsen"),
    ("temporal_shift_null", "PLV/coupling statistics must not survive temporal-shift nulls"),
    ("bloom_only_point", "saturated point plus dilation must not become geometry evidence"),
    ("histogram_preserving_pixel_permutation", "preserve intensity histogram while destroying geometry"),
    ("temporal_duplicate", "repeat one frame; must not create directional persistence"),
    ("synthetic_rigid_cloud", "synthetic rank-3 rigid trajectories must be recovered as rank<=3"),
    ("synthetic_independent_lights", "synthetic independent movers must NOT pass the rank<=3 gate"),
    ("brightness_covariate", "detected structure count must not correlate with frame brightness"),
)


def rows() -> list[str]:
    out = [
        hbp_row(
            "TOURNAMENTCONTRACTHDR",
            schema=SCHEMA,
            date="2026-07-17",
            cadence="0.100",
            target_rule="n*0.100s",
            selection_rule="nearest_decoded_best_effort_pts",
            tie_rule="absolute_error_then_lower_pts_then_lower_source_frame",
            analysis_width=320,
            slice_format="P5_GRAY_8BIT",
            cross_seat_verification="derived_slice_commitment_level",
            raw_media_in_repo=0,
            **CLAIMS_GATE,
        ),
        hbp_row(
            "SGRAMROUTE",
            status="RESOLVED_OWNING_IMPLEMENTATION",
            repo="JesseBrown1980/asolaria-cube-cloud",
            path="hutter/sgram/sgram_mix.rs",
            commit="45cc3b36179b547a3f3c3b23084f30c1cbf3aec0",
            vendored_sha256="268ac9ef06895d4eeaa26e5fc5c22e38ac0f99f9633f87340b4d759b5434cda2",
            contract="block_streaming_io_bounded_ram_archive_identical_to_mix_streaming_sha_roundtrip",
        ),
    ]
    for source in SOURCES:
        out.append(hbp_row("SOURCEPIN", **source))
    out.append(
        hbp_row(
            "SOURCEOBSERVATION",
            note="star_oe9 and official_pr038 share identical native dimensions (1920x1080) and identical duration to the microsecond (106.433333s) despite distinct raw SHA-256 values and distinct decoded stream SHA-256 values after slicing",
            interpretation="MEASURED_COINCIDENCE_OR_SHARED_UPSTREAM_TRIM_UNRESOLVED",
            same_content_claim=0,
        )
    )
    for code, name, rule in HYPOTHESES:
        out.append(
            hbp_row(
                "HYPOTHESIS",
                code=code,
                name=name,
                rule=rule,
                admission="low_reprojection+stable_rigid_distances+held_out_prediction+mdl_bic_charge+no_systematic_residual",
            )
        )
    out.append(
        hbp_row(
            "NULLSPACEMETER",
            rule="centered_measurement_matrix_rank_le_3_for_rigid_body_under_affine_camera",
            reference="Tomasi-Kanade",
            gauge="svd_spectrum",
            rigid_prediction="rank_le_3",
            independent_lights_prediction="rank_gt_3",
        )
    )
    for name, expectation in NEGATIVE_CONTROLS:
        out.append(hbp_row("NEGCONTROL", name=name, expectation=expectation, predeclared=1))
    out.append(
        hbp_row(
            "PROMOTIONRULE",
            hypothesis_admission="held_out_reprojection_beats_all_simpler_models_after_mdl_charge",
            persistence_min_ratio="0.600000",
            single_run_promotes=0,
            cross_seat_required_for_canon=1,
        )
    )
    out.append(
        hbp_row(
            "TOURNAMENTCONTRACTFTR",
            sources=len(SOURCES),
            hypotheses=len(HYPOTHESES),
            negative_controls=len(NEGATIVE_CONTROLS),
            status="PREDECLARED",
            **CLAIMS_GATE,
        )
    )
    return out


def main() -> int:
    root = Path(__file__).resolve().parents[1] / "contract"
    hbp, hbi = write_hbp_hbi(root / "PROJECT-CONTRACT", rows(), SCHEMA)
    print(
        hbp_row(
            "CONTRACTBUILDPASS",
            rows=len(rows()),
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
