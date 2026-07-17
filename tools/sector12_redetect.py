#!/usr/bin/env python3
"""Independent re-detection: N-fold angular-symmetry test on bright residual
blobs, run fresh against OUR OWN acer-materialization slices.

This is the "offered, not yet run" item from the prior Codex disconfirmation
on the star_oe9 footage (12-sector rigid-solid hypothesis, DISCONFIRMED
2026-07-16 on a different byte-materialization). Running it again here, on a
different encoding of the same content, and on the pyramid + PR-038 sources
for comparison, is itself part of the tournament: does the conclusion survive
a change of materialization?

Method: per frame, count visible bright blobs (background-subtracted,
saturation/bloom-excluded), then for each candidate fold order N in
{4,6,8,10,12,16,20}, fit a periodic angular model (bin blob angles-from-
centroid into N bins, score by BIC against a null of no periodicity), and
report which N (if any) wins. Also reports correlation of visible-blob-count
with frame brightness (the confound check from the prior disconfirmation).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common_track import background_residual, blob_centroids, load_stream, saturation_bloom_mask  # noqa: E402
from hbp import CLAIMS_GATE, hbp_row, sha256_file, write_hbp_hbi  # noqa: E402

SCHEMA = "ASOLARIA-VIDEO-MATH-SECTOR12-REDETECT-V1"
RESIDUAL_THRESHOLD = 22.0
CANDIDATE_ORDERS = (4, 6, 8, 10, 12, 16, 20)


def frame_center(frame: np.ndarray) -> tuple[float, float]:
    height, width = frame.shape
    return width / 2.0, height / 2.0


def angular_bic(angles: list[float], order: int, num_blobs: int) -> float:
    """BIC of a periodic-order-N histogram model vs a uniform null.

    Lower is better. Bins angles into N equal sectors; the model's
    log-likelihood is the multinomial log-likelihood of the observed bin
    counts under their own empirical frequencies (best case for that N),
    penalized by N parameters. This rewards genuine concentration into N
    sectors without letting large N trivially win by overfitting.
    """
    if num_blobs == 0:
        return float("inf")
    counts = np.zeros(order)
    for angle in angles:
        bin_index = int((angle % (2 * np.pi)) / (2 * np.pi) * order) % order
        counts[bin_index] += 1
    probs = counts / counts.sum()
    probs = np.clip(probs, 1e-9, 1.0)
    log_likelihood = float((counts * np.log(probs)).sum())
    return -2 * log_likelihood + order * np.log(max(num_blobs, 1))


def r_squared_periodic(angles: list[float], order: int) -> float:
    """Fraction of angular-histogram variance explained by an order-N cosine
    fit — a second, independent goodness-of-fit signal alongside BIC."""
    if not angles:
        return 0.0
    bins = np.zeros(order)
    for angle in angles:
        bin_index = int((angle % (2 * np.pi)) / (2 * np.pi) * order) % order
        bins[bin_index] += 1
    if bins.sum() == 0:
        return 0.0
    mean = bins.mean()
    total_var = float(((bins - mean) ** 2).sum())
    if total_var == 0:
        return 0.0
    theta = np.linspace(0, 2 * np.pi, order, endpoint=False)
    design = np.column_stack([np.ones(order), np.cos(theta), np.sin(theta)])
    coeffs, *_ = np.linalg.lstsq(design, bins, rcond=None)
    fitted = design @ coeffs
    residual_var = float(((bins - fitted) ** 2).sum())
    return max(0.0, 1.0 - residual_var / total_var)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    stream = args.corpus / f"{args.source_id}.pgmstream"
    slices_hbp = args.corpus / f"{args.source_id}-SLICES.hbp"
    frames, meta = load_stream(stream, slices_hbp)
    residuals = background_residual(frames)

    visible_counts: list[int] = []
    brightness: list[float] = []
    order_wins = {order: 0 for order in CANDIDATE_ORDERS}
    order_bic_sums = {order: 0.0 for order in CANDIDATE_ORDERS}
    order_r2_sums = {order: 0.0 for order in CANDIDATE_ORDERS}
    scored_frames = 0

    rows = [
        hbp_row(
            "SECTOR12HDR",
            schema=SCHEMA,
            source_id=args.source_id,
            total_slices=len(frames),
            residual_threshold=RESIDUAL_THRESHOLD,
            candidate_orders=list(CANDIDATE_ORDERS),
            **CLAIMS_GATE,
        )
    ]

    for frame, residual in zip(frames, residuals):
        bloom = saturation_bloom_mask(frame)
        blobs = blob_centroids(residual, bloom, RESIDUAL_THRESHOLD)
        visible_counts.append(len(blobs))
        brightness.append(float(frame.mean()))
        if len(blobs) < 3:
            continue
        cx, cy = frame_center(frame)
        angles = [float(np.arctan2(y - cy, x - cx)) for x, y, _, _ in blobs]
        best_order, best_bic = None, None
        for order in CANDIDATE_ORDERS:
            bic = angular_bic(angles, order, len(blobs))
            r2 = r_squared_periodic(angles, order)
            order_bic_sums[order] += bic
            order_r2_sums[order] += r2
            if best_bic is None or bic < best_bic:
                best_bic, best_order = bic, order
        if best_order is not None:
            order_wins[best_order] += 1
            scored_frames += 1

    brightness_arr = np.array(brightness)
    counts_arr = np.array(visible_counts, dtype=np.float64)
    if brightness_arr.std() > 0 and counts_arr.std() > 0:
        brightness_corr = float(np.corrcoef(brightness_arr, counts_arr)[0, 1])
    else:
        brightness_corr = 0.0

    rows.append(
        hbp_row(
            "SECTOR12VISIBILITY",
            source_id=args.source_id,
            frames_scored=scored_frames,
            max_visible_count=int(counts_arr.max()) if len(counts_arr) else 0,
            mean_visible_count=f"{counts_arr.mean():.4f}" if len(counts_arr) else "0",
            brightness_correlation=f"{brightness_corr:.6f}",
            brightness_confound_present=abs(brightness_corr) > 0.3,
        )
    )

    for order in CANDIDATE_ORDERS:
        mean_bic = order_bic_sums[order] / scored_frames if scored_frames else float("nan")
        mean_r2 = order_r2_sums[order] / scored_frames if scored_frames else float("nan")
        rows.append(
            hbp_row(
                "SECTOR12ORDER",
                source_id=args.source_id,
                order=order,
                wins=order_wins[order],
                win_ratio=f"{order_wins[order] / scored_frames:.6f}" if scored_frames else "NA",
                mean_bic=f"{mean_bic:.4f}" if scored_frames else "NA",
                mean_r2=f"{mean_r2:.6f}" if scored_frames else "NA",
            )
        )

    order12_supported = (
        scored_frames > 0
        and order_wins[12] / scored_frames > 0.5
        and order_r2_sums[12] / scored_frames > 0.3
        and abs(brightness_corr) < 0.3
    )
    rows.append(
        hbp_row(
            "SECTOR12VERDICT",
            source_id=args.source_id,
            twelve_fold_supported=order12_supported,
            best_overall_order=max(order_wins, key=lambda o: order_wins[o]) if scored_frames else "NA",
            interpretation="independent_redetection_on_this_materialization_geometry_only",
        )
    )
    rows.append(hbp_row("SECTOR12FTR", source_id=args.source_id, **CLAIMS_GATE))

    hbp, hbi = write_hbp_hbi(args.output, rows, SCHEMA)
    print(
        hbp_row(
            "SECTOR12PASS",
            source_id=args.source_id,
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
