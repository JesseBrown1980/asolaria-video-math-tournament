#!/usr/bin/env python3
"""Hypothesis tournament C0-C8: forward-render / reverse-readback against
strictly held-out frames, with an MDL/BIC complexity charge.

Every hypothesis is fit ONLY on the training window and scored ONLY on its
predictive error on the held-out window it never saw — this is what makes it
reconstruction, not a forward renderer that "verifies" a preselected shape
independent of the tracked pixel data (the banned `pixel_nodes`-unused defect
family). All hypotheses consume the SAME tracked 2D points.

Camera model: orthographic/weak-perspective only (explicit, stated
limitation — real cameras need full conic + intrinsics + distortion; this is
a first-order geometry test, not a calibrated 3D reconstruction).

C0 artifact       - per-point independent constant-velocity extrapolation.
C1 planar         - shared rigid IN-PLANE (Z-axis) rotation + scale + translate.
C2 rigid_tetra    - regular tetrahedron template, Y-axis (out-of-plane) spin.
C3 cylinder_core  - 8-point cylinder-rim template, Y-axis spin.
C4 torus_core     - 12-point torus-ring template, Y-axis spin.
C5 square_pyramid - 5-vertex square pyramid template, Y-axis spin.
C6 prism          - 6-vertex triangular prism template, Y-axis spin.
C7 free_rigid_lattice - Tomasi-Kanade rank<=3 factorization (free 3D shape,
                    heavily MDL-charged: 3 params per point).
C8 twelve_sector_solid - 12-point ring template (2/3 visible framing), Y-axis spin.

Admission (per PROJECT-CONTRACT.hbp PROMOTIONRULE): a hypothesis is reported
as held-out-favored only if it beats C0 AND every simpler hypothesis after
the MDL/BIC charge. A single run never promotes to canon.
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

SCHEMA = "ASOLARIA-VIDEO-MATH-TOURNAMENT-V1"
RESIDUAL_THRESHOLD = 22.0
MIN_TRACK_LEN = 10
MAX_JUMP_PX = 14.0
TRAIN_FRACTION = 0.70
OMEGA_STEPS = 37
THETA_STEPS = 24
OMEGA_RANGE = (-0.6, 0.6)


def regular_tetra() -> np.ndarray:
    return np.array(
        [
            [0.0, 0.0, 1.0],
            [2 * np.sqrt(2) / 3, 0.0, -1.0 / 3],
            [-np.sqrt(2) / 3, np.sqrt(2.0 / 3.0), -1.0 / 3],
            [-np.sqrt(2) / 3, -np.sqrt(2.0 / 3.0), -1.0 / 3],
        ]
    )


def cylinder_rim(n_per_ring: int = 4) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, n_per_ring, endpoint=False)
    top = np.array([[np.cos(a), 1.0, np.sin(a)] for a in angles])
    bottom = np.array([[np.cos(a), -1.0, np.sin(a)] for a in angles])
    return np.vstack([top, bottom])


def torus_ring(n: int = 12, major: float = 1.0, minor: float = 0.35) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.array([[(major + minor) * np.cos(a), 0.0, (major + minor) * np.sin(a)] for a in angles])


def square_pyramid() -> np.ndarray:
    base = np.array([[1, -0.5, 1], [1, -0.5, -1], [-1, -0.5, -1], [-1, -0.5, 1]], dtype=np.float64)
    apex = np.array([[0.0, 1.0, 0.0]])
    return np.vstack([base, apex])


def triangular_prism() -> np.ndarray:
    tri = np.array([[0, 0, 1], [np.sqrt(3) / 2, 0, -0.5], [-np.sqrt(3) / 2, 0, -0.5]], dtype=np.float64)
    return np.vstack([tri + np.array([0, 1, 0]), tri + np.array([0, -1, 0])])


def twelve_sector_ring(n: int = 12) -> np.ndarray:
    angles = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.array([[np.cos(a), 0.0, np.sin(a)] for a in angles])


TEMPLATES = {
    "C2": ("rigid_tetra", regular_tetra(), "y"),
    "C3": ("cylinder_core", cylinder_rim(), "y"),
    "C4": ("torus_core", torus_ring(), "y"),
    "C5": ("square_pyramid", square_pyramid(), "y"),
    "C6": ("prism", triangular_prism(), "y"),
    "C8": ("twelve_sector_solid", twelve_sector_ring(), "y"),
}


def build_window(
    tracks: dict, total_frames: int, max_points: int, target_length: int = 40
) -> tuple[list[int], list[int]] | tuple[None, None]:
    """Slide a BOUNDED window (target_length frames, capped at the sequence
    end) across the sequence; keep the placement maximizing length*alive-
    tracks among placements with >=4 simultaneously-alive tracks. A window
    spanning to the literal end of the whole sequence is not required — that
    would make nearly every real (noisy, drifting) track disqualify itself."""
    candidates = [tid for tid, pts in tracks.items() if len(pts) >= MIN_TRACK_LEN]
    if len(candidates) < 4:
        return None, None
    presence = {tid: {f for f, _, _ in tracks[tid]} for tid in candidates}
    best_window, best_score = None, -1
    for start in range(total_frames):
        length = min(target_length, total_frames - start)
        if length < MIN_TRACK_LEN:
            continue
        window = set(range(start, start + length))
        alive = [tid for tid in candidates if window <= presence[tid]]
        if len(alive) < 4:
            continue
        score = length * len(alive)
        if score > best_score:
            best_score, best_window = score, (sorted(window), alive)
    if best_window is None:
        return None, None
    frames, point_ids = best_window
    return frames, point_ids[:max_points]


def angular_sort(points_2d: np.ndarray) -> np.ndarray:
    center = points_2d.mean(axis=0)
    angles = np.arctan2(points_2d[:, 1] - center[1], points_2d[:, 0] - center[0])
    return np.argsort(angles)


def project_template(template: np.ndarray, axis: str, theta: float) -> np.ndarray:
    c, s = np.cos(theta), np.sin(theta)
    if axis == "z":
        x, y = template[:, 0], template[:, 1]
        return np.column_stack([x * c - y * s, x * s + y * c])
    x, z = template[:, 0], template[:, 2]
    y = template[:, 1]
    rotated_x = x * c + z * s
    return np.column_stack([rotated_x, y])


def fit_rotation_hypothesis(
    template: np.ndarray,
    axis: str,
    order: np.ndarray,
    obs_train: np.ndarray,
    obs_heldout: np.ndarray,
) -> dict:
    """Grid search (omega, theta0); for each, projected template per frame is
    fixed, so scale+translation solve in closed form (linear least squares).
    obs_train/obs_heldout: (T, P, 2) observed positions, point order already
    matched to `order` (template indices sorted to match observation angular order)."""
    template_ordered = template[order]
    num_train = obs_train.shape[0]
    num_points = obs_train.shape[1]
    omegas = np.linspace(OMEGA_RANGE[0], OMEGA_RANGE[1], OMEGA_STEPS)
    thetas0 = np.linspace(0, 2 * np.pi, THETA_STEPS, endpoint=False)

    best = None
    for omega in omegas:
        for theta0 in thetas0:
            proj_frames = np.stack(
                [project_template(template_ordered, axis, theta0 + omega * t) for t in range(num_train)]
            )  # (T, P, 2)
            design = proj_frames.reshape(-1, 2)  # (T*P, 2) -> [px, py] per obs
            targets = obs_train.reshape(-1, 2)
            # model: obs = s * proj + [tx, ty]  =>  [proj_x, proj_y, 1] @ [s_x; s_y; ...]
            # isotropic scale: obs = s*proj + T  (2 outputs share s, share T per-coord)
            A = np.zeros((design.shape[0] * 2, 3))
            b = np.zeros(design.shape[0] * 2)
            A[0::2, 0] = design[:, 0]
            A[0::2, 1] = 1.0
            A[1::2, 0] = design[:, 1]
            A[1::2, 2] = 1.0
            b[0::2] = targets[:, 0]
            b[1::2] = targets[:, 1]
            coeffs, *_ = np.linalg.lstsq(A, b, rcond=None)
            scale, tx, ty = coeffs
            pred_train = scale * design + np.array([tx, ty])
            sse_train = float(((pred_train - targets) ** 2).sum())
            if best is None or sse_train < best["sse_train"]:
                best = dict(omega=omega, theta0=theta0, scale=scale, tx=tx, ty=ty, sse_train=sse_train)

    num_heldout = obs_heldout.shape[0]
    proj_heldout = np.stack(
        [
            project_template(template_ordered, axis, best["theta0"] + best["omega"] * (num_train + t))
            for t in range(num_heldout)
        ]
    )
    pred_heldout = best["scale"] * proj_heldout + np.array([best["tx"], best["ty"]])
    sse_heldout = float(((pred_heldout - obs_heldout) ** 2).sum())
    n_obs = num_heldout * num_points * 2
    params = 5  # omega, theta0, scale, tx, ty
    bic = n_obs * np.log(max(sse_heldout / max(n_obs, 1), 1e-9)) + params * np.log(max(n_obs, 2))
    return dict(
        params=params,
        sse_train=best["sse_train"],
        sse_heldout=sse_heldout,
        rmse_heldout=float(np.sqrt(sse_heldout / max(n_obs, 1))),
        bic_heldout=float(bic),
        fit=dict(omega=float(best["omega"]), theta0=float(best["theta0"]), scale=float(best["scale"])),
    )


def fit_c0_artifact(obs_train: np.ndarray, obs_heldout: np.ndarray) -> dict:
    num_train, num_points, _ = obs_train.shape
    t = np.arange(num_train)
    design = np.column_stack([t, np.ones(num_train)])
    coeffs_x, *_ = np.linalg.lstsq(design, obs_train[:, :, 0], rcond=None)
    coeffs_y, *_ = np.linalg.lstsq(design, obs_train[:, :, 1], rcond=None)
    pred_train_x = design @ coeffs_x
    pred_train_y = design @ coeffs_y
    sse_train = float(((pred_train_x - obs_train[:, :, 0]) ** 2).sum() + ((pred_train_y - obs_train[:, :, 1]) ** 2).sum())

    num_heldout = obs_heldout.shape[0]
    t_out = np.arange(num_train, num_train + num_heldout)
    design_out = np.column_stack([t_out, np.ones(num_heldout)])
    pred_out_x = design_out @ coeffs_x
    pred_out_y = design_out @ coeffs_y
    sse_heldout = float(((pred_out_x - obs_heldout[:, :, 0]) ** 2).sum() + ((pred_out_y - obs_heldout[:, :, 1]) ** 2).sum())
    n_obs = num_heldout * num_points * 2
    params = 4 * num_points
    bic = n_obs * np.log(max(sse_heldout / max(n_obs, 1), 1e-9)) + params * np.log(max(n_obs, 2))
    return dict(
        params=params,
        sse_train=sse_train,
        sse_heldout=sse_heldout,
        rmse_heldout=float(np.sqrt(sse_heldout / max(n_obs, 1))),
        bic_heldout=float(bic),
        fit=dict(note="independent_constant_velocity_per_point"),
    )


def fit_c7_free_rigid(obs_train: np.ndarray, obs_heldout: np.ndarray) -> dict:
    """Tomasi-Kanade rank<=3 factorization on TRAIN only, per-frame centroid
    recomputed on both train and held-out (a per-frame spatial recentering,
    not a temporal leak): this tests whether the RELATIVE rank<=3 structure
    extrapolates, not the absolute translation, matching nullspace_rank3.py's
    convention."""
    num_train, num_points, _ = obs_train.shape
    centered = obs_train.copy()
    centered[:, :, 0] -= centered[:, :, 0].mean(axis=1, keepdims=True)
    centered[:, :, 1] -= centered[:, :, 1].mean(axis=1, keepdims=True)
    matrix = np.vstack([centered[:, :, 0], centered[:, :, 1]])  # (2T, P)
    u, s, vt = np.linalg.svd(matrix, full_matrices=False)
    rank = min(3, s.shape[0])
    motion = u[:, :rank] * s[:rank]  # (2T, rank): rows [0:T)=x-block, [T:2T)=y-block
    shape = vt[:rank, :]  # (rank, P)
    pred_train = motion @ shape
    pred_train_x, pred_train_y = pred_train[:num_train], pred_train[num_train:]
    sse_train = float(((pred_train_x - centered[:, :, 0]) ** 2).sum() + ((pred_train_y - centered[:, :, 1]) ** 2).sum())

    motion_x, motion_y = motion[:num_train], motion[num_train:]  # each (T, rank)
    t = np.arange(num_train)
    design = np.column_stack([t, np.ones(num_train)])
    coeffs_x, *_ = np.linalg.lstsq(design, motion_x, rcond=None)
    coeffs_y, *_ = np.linalg.lstsq(design, motion_y, rcond=None)

    num_heldout = obs_heldout.shape[0]
    t_out = np.arange(num_train, num_train + num_heldout)
    design_out = np.column_stack([t_out, np.ones(num_heldout)])
    pred_out_x = (design_out @ coeffs_x) @ shape  # (H, P)
    pred_out_y = (design_out @ coeffs_y) @ shape  # (H, P)

    heldout_x = obs_heldout[:, :, 0] - obs_heldout[:, :, 0].mean(axis=1, keepdims=True)
    heldout_y = obs_heldout[:, :, 1] - obs_heldout[:, :, 1].mean(axis=1, keepdims=True)
    sse_heldout = float(((pred_out_x - heldout_x) ** 2).sum() + ((pred_out_y - heldout_y) ** 2).sum())
    n_obs = num_heldout * num_points * 2
    params = 3 * num_points + 2 * rank
    bic = n_obs * np.log(max(sse_heldout / max(n_obs, 1), 1e-9)) + params * np.log(max(n_obs, 2))
    return dict(
        params=params,
        sse_train=sse_train,
        sse_heldout=sse_heldout,
        rmse_heldout=float(np.sqrt(sse_heldout / max(n_obs, 1))),
        bic_heldout=float(bic),
        fit=dict(rank=rank, note="tomasi_kanade_rank_le_3_factorization_shape_charged_heavily"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stream = args.corpus / f"{args.source_id}.pgmstream"
    slices_hbp = args.corpus / f"{args.source_id}-SLICES.hbp"
    frames, meta = load_stream(stream, slices_hbp)

    residuals = background_residual(frames)
    per_frame_blobs = []
    for frame, residual in zip(frames, residuals):
        bloom = saturation_bloom_mask(frame)
        per_frame_blobs.append(blob_centroids(residual, bloom, RESIDUAL_THRESHOLD))
    tracks = greedy_track(per_frame_blobs, MAX_JUMP_PX)

    max_template_points = max(len(t) for _, t, _ in TEMPLATES.values())
    frame_ids, point_ids = build_window(tracks, len(frames), max_template_points)

    rows = [
        hbp_row(
            "TOURNAMENTHDR",
            schema=SCHEMA,
            source_id=args.source_id,
            total_slices=len(frames),
            tracks_detected=len(tracks),
            train_fraction=TRAIN_FRACTION,
            camera_model="orthographic_weak_perspective_v1",
            **CLAIMS_GATE,
        )
    ]

    if frame_ids is None or len(frame_ids) < MIN_TRACK_LEN:
        rows.append(hbp_row("TOURNAMENTRESULT", source_id=args.source_id, status="INSUFFICIENT_TRACKS"))
        rows.append(hbp_row("TOURNAMENTFTR", source_id=args.source_id, **CLAIMS_GATE))
        hbp, hbi = write_hbp_hbi(args.output, rows, SCHEMA)
        print(hbp_row("TOURNAMENTPASS", source_id=args.source_id, hbp_sha256=sha256_file(hbp), hbi_sha256=sha256_file(hbi), **CLAIMS_GATE))
        return 0

    lookup = {tid: {f: (x, y) for f, x, y in tracks[tid]} for tid in point_ids}
    obs = np.array([[lookup[tid][f] for tid in point_ids] for f in frame_ids])  # (F, P, 2)
    split = max(MIN_TRACK_LEN // 2, int(len(frame_ids) * TRAIN_FRACTION))
    split = min(split, len(frame_ids) - 4) if len(frame_ids) > 8 else len(frame_ids) - 2
    obs_train, obs_heldout = obs[:split], obs[split:]

    results: dict[str, dict] = {}
    results["C0"] = fit_c0_artifact(obs_train, obs_heldout)

    # C1: template = the observed frame-0 layout itself (no 3D shape claim),
    # both template and observations independently angle-sorted from the
    # same frame-0 reference so vertex i <-> observed point i consistently.
    order_z = angular_sort(obs_train[0])
    obs_train_z = obs_train[:, order_z, :]
    obs_heldout_z = obs_heldout[:, order_z, :]
    template_c1 = np.column_stack(
        [obs_train[0][order_z] - obs_train[0].mean(axis=0), np.zeros(len(order_z))]
    )
    results["C1"] = fit_rotation_hypothesis(
        template_c1, "z", np.arange(len(order_z)), obs_train_z, obs_heldout_z
    )

    # C2-C8: fixed 3D templates. Deterministic correspondence heuristic
    # (stated limitation, not a search): sort the usable tracked points by
    # angle around their own frame-0 centroid, sort the template's own
    # vertices by angle around its projected centroid, match index-by-index.
    for code, (name, template, axis) in TEMPLATES.items():
        usable = min(len(template), obs_train.shape[1])
        obs_train_sub = obs_train[:, :usable, :]
        obs_heldout_sub = obs_heldout[:, :usable, :]
        point_order = angular_sort(obs_train_sub[0])
        obs_train_sorted = obs_train_sub[:, point_order, :]
        obs_heldout_sorted = obs_heldout_sub[:, point_order, :]
        template_2d = template[:, [0, 2]] if axis == "y" else template[:, [0, 1]]
        template_order = angular_sort(template_2d)[:usable]
        results[code] = fit_rotation_hypothesis(
            template, axis, template_order, obs_train_sorted, obs_heldout_sorted
        )
    results["C7"] = fit_c7_free_rigid(obs_train, obs_heldout)

    for code in ("C0", "C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"):
        result = results[code]
        rows.append(
            hbp_row(
                "TOURNAMENTRESULT",
                source_id=args.source_id,
                hypothesis=code,
                params=result["params"],
                sse_train=f"{result['sse_train']:.4f}",
                sse_heldout=f"{result['sse_heldout']:.4f}",
                rmse_heldout=f"{result['rmse_heldout']:.4f}",
                bic_heldout=f"{result['bic_heldout']:.4f}",
                fit=str(result["fit"]),
            )
        )

    ranked = sorted(results.items(), key=lambda item: item[1]["bic_heldout"])
    winner_code, winner = ranked[0]
    c0_bic = results["C0"]["bic_heldout"]
    beats_c0 = winner["bic_heldout"] < c0_bic
    rows.append(
        hbp_row(
            "TOURNAMENTVERDICT",
            source_id=args.source_id,
            train_frames=split,
            heldout_frames=len(frame_ids) - split,
            usable_points=obs.shape[1],
            best_hypothesis=winner_code,
            best_bic_heldout=f"{winner['bic_heldout']:.4f}",
            c0_bic_heldout=f"{c0_bic:.4f}",
            best_beats_artifact_null=beats_c0,
            ranking=[code for code, _ in ranked],
            single_run_promotes_to_canon=0,
            interpretation="geometry_measurement_only_not_identity_or_physical_claim",
        )
    )
    rows.append(hbp_row("TOURNAMENTFTR", source_id=args.source_id, **CLAIMS_GATE))

    hbp, hbi = write_hbp_hbi(args.output, rows, SCHEMA)
    print(
        hbp_row(
            "TOURNAMENTPASS",
            source_id=args.source_id,
            best_hypothesis=winner_code,
            beats_artifact_null=beats_c0,
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
