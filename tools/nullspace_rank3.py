#!/usr/bin/env python3
"""Rank<=3 nullspace meter (Tomasi-Kanade rigid-body factorization test).

For a rigid body under an affine (weak-perspective) camera, the centered
2F x P measurement matrix W (F frames, P tracked points) has rank <= 3: each
row is a linear combination of at most 3 independent basis vectors (the
camera's rotation columns). Independently moving points (e.g. scattered
lights) generically break this — the SVD spectrum will not show a sharp
elbow after the 3rd singular value.

This tool:
  1. detects bright residual blobs per frame (background-subtracted),
  2. greedily tracks them,
  3. selects the point set alive across the longest common frame window,
  4. builds the centered measurement matrix and its SVD spectrum,
  5. reports the rank-3 energy ratio (top-3 / total) as the rigid-body score,
  6. runs three predeclared controls: temporal-shift null (should NOT score
     higher), synthetic rigid cloud (must score near 1.0), synthetic
     independent movers (must score well below the observed data).

No claim of object identity or physical mechanism. fire=0.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_track import (  # noqa: E402
    background_residual,
    blob_centroids,
    greedy_track,
    load_stream,
    saturation_bloom_mask,
)
from hbp import CLAIMS_GATE, hbp_row, sha256_file, write_hbp_hbi  # noqa: E402

SCHEMA = "ASOLARIA-VIDEO-MATH-NULLSPACE-V1"
RESIDUAL_THRESHOLD = 22.0
MIN_TRACK_LEN = 8
MAX_JUMP_PX = 14.0
RNG_SEED = 20260717


def build_measurement_matrix(
    tracks: dict[int, list[tuple[int, float, float]]],
    total_frames: int,
) -> tuple[np.ndarray | None, list[int], int]:
    """Pick the frame window + track subset maximizing (frames * tracks) with
    full coverage, then build the centered 2F x P matrix."""
    candidates = [tid for tid, pts in tracks.items() if len(pts) >= MIN_TRACK_LEN]
    if len(candidates) < 4:
        return None, [], 0
    presence = {tid: {f for f, _, _ in tracks[tid]} for tid in candidates}
    best_window = None
    best_score = -1
    for start in range(total_frames):
        for length in (total_frames - start, min(24, total_frames - start)):
            if length < MIN_TRACK_LEN:
                continue
            window = set(range(start, start + length))
            alive = [tid for tid in candidates if window <= presence[tid]]
            if len(alive) < 4:
                continue
            score = length * len(alive)
            if score > best_score:
                best_score = score
                best_window = (sorted(window), alive)
    if best_window is None:
        return None, [], 0
    frames, point_ids = best_window
    point_ids = point_ids[:40]
    lookup = {tid: {f: (x, y) for f, x, y in tracks[tid]} for tid in point_ids}
    rows_x = np.array([[lookup[tid][f][0] for tid in point_ids] for f in frames])
    rows_y = np.array([[lookup[tid][f][1] for tid in point_ids] for f in frames])
    rows_x -= rows_x.mean(axis=1, keepdims=True)
    rows_y -= rows_y.mean(axis=1, keepdims=True)
    matrix = np.vstack([rows_x, rows_y])
    return matrix, point_ids, len(frames)


def rank3_energy_ratio(matrix: np.ndarray) -> tuple[float, list[float]]:
    singular_values = np.linalg.svd(matrix, compute_uv=False)
    total = float((singular_values**2).sum())
    if total <= 0:
        return 0.0, singular_values.tolist()
    top3 = float((singular_values[:3] ** 2).sum())
    return top3 / total, singular_values.tolist()


def synthetic_rigid_cloud(num_frames: int, num_points: int, rng: np.random.Generator) -> np.ndarray:
    points_3d = rng.uniform(-1, 1, size=(num_points, 3))
    angles = np.linspace(0, 2 * np.pi, num_frames, endpoint=False)
    rows = []
    for angle in angles:
        c, s = np.cos(angle), np.sin(angle)
        rot = np.array([[c, 0, s], [0, 1, 0]])
        proj = points_3d @ rot.T
        rows.append(proj[:, 0])
        rows.append(proj[:, 1])
    matrix = np.array(rows)
    matrix -= matrix.mean(axis=1, keepdims=True)
    return matrix


def synthetic_independent_movers(num_frames: int, num_points: int, rng: np.random.Generator) -> np.ndarray:
    rows_x = rng.uniform(-1, 1, size=(num_frames, num_points))
    rows_y = rng.uniform(-1, 1, size=(num_frames, num_points))
    matrix = np.vstack([rows_x, rows_y])
    matrix -= matrix.mean(axis=1, keepdims=True)
    return matrix


def temporal_shift_null(matrix: np.ndarray, rng: np.random.Generator, shift_trials: int = 20) -> float:
    num_frame_rows = matrix.shape[0] // 2
    scores = []
    for _ in range(shift_trials):
        shift = int(rng.integers(1, max(2, num_frame_rows)))
        x_rows = np.roll(matrix[:num_frame_rows], shift, axis=0)
        y_rows = np.roll(matrix[num_frame_rows:], shift, axis=0)
        shifted = np.vstack([x_rows, y_rows])
        ratio, _ = rank3_energy_ratio(shifted)
        scores.append(ratio)
    return float(np.mean(scores))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stream = args.corpus / f"{args.source_id}.pgmstream"
    slices_hbp = args.corpus / f"{args.source_id}-SLICES.hbp"
    frames, meta = load_stream(stream, slices_hbp)
    rng = np.random.default_rng(RNG_SEED)

    residuals = background_residual(frames)
    per_frame_blobs = []
    for frame, residual in zip(frames, residuals):
        bloom = saturation_bloom_mask(frame)
        per_frame_blobs.append(blob_centroids(residual, bloom, RESIDUAL_THRESHOLD))

    tracks = greedy_track(per_frame_blobs, MAX_JUMP_PX)
    matrix, point_ids, window_frames = build_measurement_matrix(tracks, len(frames))

    rows = [
        hbp_row(
            "NULLSPACEHDR",
            schema=SCHEMA,
            source_id=args.source_id,
            total_slices=len(frames),
            residual_threshold=RESIDUAL_THRESHOLD,
            min_track_len=MIN_TRACK_LEN,
            max_jump_px=MAX_JUMP_PX,
            rng_seed=RNG_SEED,
            tracks_detected=len(tracks),
            **CLAIMS_GATE,
        )
    ]

    if matrix is None:
        rows.append(
            hbp_row(
                "NULLSPACERESULT",
                source_id=args.source_id,
                status="INSUFFICIENT_TRACKS",
                usable_points=0,
                window_frames=0,
                rank3_energy_ratio="NA",
            )
        )
    else:
        observed_ratio, singular_values = rank3_energy_ratio(matrix)
        null_ratio = temporal_shift_null(matrix, rng)
        rigid_synth = synthetic_rigid_cloud(max(window_frames, 12), len(point_ids), rng)
        rigid_ratio, _ = rank3_energy_ratio(rigid_synth)
        indep_synth = synthetic_independent_movers(max(window_frames, 12), len(point_ids), rng)
        indep_ratio, _ = rank3_energy_ratio(indep_synth)

        rows.append(
            hbp_row(
                "NULLSPACERESULT",
                source_id=args.source_id,
                status="MEASURED",
                usable_points=len(point_ids),
                window_frames=window_frames,
                rank3_energy_ratio=f"{observed_ratio:.6f}",
                singular_values=[f"{v:.4f}" for v in singular_values[:8]],
            )
        )
        rows.append(
            hbp_row(
                "NULLSPACECONTROL",
                name="temporal_shift_null",
                mean_ratio=f"{null_ratio:.6f}",
                observed_beats_null=observed_ratio > null_ratio,
            )
        )
        rows.append(
            hbp_row(
                "NULLSPACECONTROL",
                name="synthetic_rigid_cloud",
                mean_ratio=f"{rigid_ratio:.6f}",
                sanity_pass=rigid_ratio > 0.97,
            )
        )
        rows.append(
            hbp_row(
                "NULLSPACECONTROL",
                name="synthetic_independent_movers",
                mean_ratio=f"{indep_ratio:.6f}",
                sanity_pass=indep_ratio < rigid_ratio,
            )
        )
        rigid_supported = (
            observed_ratio > null_ratio
            and observed_ratio > 0.9 * rigid_ratio
            and observed_ratio > indep_ratio
        )
        rows.append(
            hbp_row(
                "NULLSPACEVERDICT",
                source_id=args.source_id,
                rigid_body_supported=rigid_supported,
                interpretation="geometry_measurement_only_not_identity_or_physical_claim",
            )
        )

    rows.append(hbp_row("NULLSPACEFTR", source_id=args.source_id, **CLAIMS_GATE))

    hbp, hbi = write_hbp_hbi(args.output, rows, SCHEMA)
    print(
        hbp_row(
            "NULLSPACEPASS",
            source_id=args.source_id,
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
