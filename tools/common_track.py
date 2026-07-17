#!/usr/bin/env python3
"""Shared bright-node detection + tracking for nullspace/tournament/sector12.

Deliberately simple and inspectable: connected-component blob detection on a
background-subtracted residual, greedy nearest-neighbor tracking across the
slice sequence. This is a measurement instrument, not a claim — its output
feeds the rank<=3 test and the hypothesis tournament, both of which carry
their own negative controls.
"""

from __future__ import annotations

from collections import deque

import numpy as np


def gray_to_array(pixels: bytes, width: int, height: int) -> np.ndarray:
    return np.frombuffer(pixels, dtype=np.uint8).reshape(height, width).astype(np.float64)


def background_residual(frames: list[np.ndarray]) -> list[np.ndarray]:
    """Median background over the whole sequence; residual = |frame - bg|."""
    stack = np.stack(frames, axis=0)
    background = np.median(stack, axis=0)
    return [np.abs(frame - background) for frame in frames]


def saturation_bloom_mask(frame: np.ndarray, radius: int = 2) -> np.ndarray:
    saturated = frame >= 250
    if not saturated.any():
        return np.zeros_like(frame, dtype=bool)
    bloom = saturated.copy()
    height, width = frame.shape
    ys, xs = np.where(saturated)
    for y, x in zip(ys.tolist(), xs.tolist()):
        y0, y1 = max(0, y - radius), min(height, y + radius + 1)
        x0, x1 = max(0, x - radius), min(width, x + radius + 1)
        bloom[y0:y1, x0:x1] = True
    return bloom


def connected_components(mask: np.ndarray) -> list[list[tuple[int, int]]]:
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    components: list[list[tuple[int, int]]] = []
    for sy in range(height):
        for sx in range(width):
            if not mask[sy, sx] or seen[sy, sx]:
                continue
            queue = deque([(sy, sx)])
            seen[sy, sx] = True
            component: list[tuple[int, int]] = []
            while queue:
                y, x = queue.popleft()
                component.append((y, x))
                for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                    if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                        seen[ny, nx] = True
                        queue.append((ny, nx))
            components.append(component)
    return components


def blob_centroids(
    residual: np.ndarray,
    exclude_mask: np.ndarray,
    threshold: float,
    min_area: int = 3,
    max_blobs: int = 24,
) -> list[tuple[float, float, int, float]]:
    """Return (x, y, area, peak_intensity) sorted by area desc, largest-first."""
    mask = (residual >= threshold) & (~exclude_mask)
    blobs = []
    for component in connected_components(mask):
        if len(component) < min_area:
            continue
        ys = np.array([p[0] for p in component], dtype=np.float64)
        xs = np.array([p[1] for p in component], dtype=np.float64)
        peak = float(max(residual[y, x] for y, x in component))
        blobs.append((float(xs.mean()), float(ys.mean()), len(component), peak))
    blobs.sort(key=lambda item: item[2], reverse=True)
    return blobs[:max_blobs]


def greedy_track(
    per_frame_blobs: list[list[tuple[float, float, int, float]]],
    max_jump: float,
) -> dict[int, list[tuple[int, float, float]]]:
    """Greedy nearest-neighbor track linking across consecutive frames.

    Returns {track_id: [(frame_index, x, y), ...]}. A track continues only if
    the nearest unmatched blob in the next frame is within max_jump pixels.
    """
    tracks: dict[int, list[tuple[int, float, float]]] = {}
    active: dict[int, tuple[float, float]] = {}
    next_id = 0
    for frame_index, blobs in enumerate(per_frame_blobs):
        unmatched = list(range(len(blobs)))
        matched_track_ids = []
        for track_id, (last_x, last_y) in list(active.items()):
            if not unmatched:
                break
            best_j, best_dist = None, None
            for j in unmatched:
                x, y, _, _ = blobs[j]
                dist = ((x - last_x) ** 2 + (y - last_y) ** 2) ** 0.5
                if best_dist is None or dist < best_dist:
                    best_j, best_dist = j, dist
            if best_dist is not None and best_dist <= max_jump:
                x, y, _, _ = blobs[best_j]
                tracks[track_id].append((frame_index, x, y))
                active[track_id] = (x, y)
                unmatched.remove(best_j)
                matched_track_ids.append(track_id)
        for track_id in list(active):
            if track_id not in matched_track_ids:
                del active[track_id]
        for j in unmatched:
            x, y, _, _ = blobs[j]
            tracks[next_id] = [(frame_index, x, y)]
            active[next_id] = (x, y)
            next_id += 1
    return tracks


def load_stream(stream_path, slices_hbp):
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from hbp import iter_pgm_slices  # noqa: E402

    frames: list[np.ndarray] = []
    meta: list[dict] = []
    for item, pixels in iter_pgm_slices(Path(stream_path), Path(slices_hbp)):
        width, height = int(item["width"]), int(item["height"])
        frames.append(gray_to_array(pixels, width, height))
        meta.append(item)
    return frames, meta
