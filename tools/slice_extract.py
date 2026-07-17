#!/usr/bin/env python3
"""Extract the public derived-slice corpus from a LOCAL raw video.

Raw media never enters the repository. This tool runs on the seat that holds
the pinned materialization; it emits, per source:

  corpus/<source_id>.pgmstream        concatenated P5 gray slices, target order
  corpus/<source_id>-SLICES.hbp/.hbi  per-slice receipts (PTS math + stream ranges)
  sha sidecars for all of the above

Cadence contract (identical to the cross-seat Moving-Flashlight contract):
targets are exactly n*0.100 s; the chosen frame is the nearest decoded
best_effort_timestamp_time; ties break by absolute error, then lower PTS,
then lower source frame index. Every receipt row records target PTS, actual
PTS, signed error, and source frame index.

Determinism boundary (stated, not hidden): ffmpeg decode+scale output is
deterministic for a given ffmpeg build; the receipts pin the build. Cloud
jobs verify the published stream by SHA — they do not re-derive from raw.
"""

from __future__ import annotations

import argparse
import bisect
import subprocess
import sys
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hbp import (  # noqa: E402
    CLAIMS_GATE,
    hbp_row,
    sha256_bytes,
    sha256_file,
    write_hbp_hbi,
    write_sha_sidecar,
)

SCHEMA = "ASOLARIA-VIDEO-MATH-SLICE-CORPUS-V1"
CADENCE = Decimal("0.100")


@dataclass(frozen=True)
class FramePTS:
    index: int
    pts: Decimal


@dataclass(frozen=True)
class TargetChoice:
    target_index: int
    target_pts: Decimal
    frame_index: int
    actual_pts: Decimal

    @property
    def error(self) -> Decimal:
        return self.actual_pts - self.target_pts


def run_checked(command: list[str], *, binary: bool = False) -> bytes | str:
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace")[-4000:]
        raise RuntimeError(f"command failed ({result.returncode}): {command[0]}: {detail}")
    return result.stdout if binary else result.stdout.decode("utf-8", errors="strict")


def tool_version(tool: str) -> str:
    return str(run_checked([tool, "-version"])).splitlines()[0]


def probe_dimensions(path: Path) -> tuple[int, int]:
    text = run_checked(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "csv=p=0:s=x", str(path),
        ]
    )
    width, height = str(text).strip().splitlines()[0].split("x", 1)
    return int(width), int(height)


def probe_pts(path: Path) -> list[FramePTS]:
    text = run_checked(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0", "-show_frames",
            "-show_entries", "frame=best_effort_timestamp_time", "-of", "csv=p=0", str(path),
        ]
    )
    frames: list[FramePTS] = []
    for source_index, line in enumerate(str(text).splitlines()):
        token = line.strip().split(",", 1)[0]
        if not token or token == "N/A":
            continue
        frames.append(FramePTS(index=source_index, pts=Decimal(token)))
    if not frames:
        raise RuntimeError(f"no decoded PTS values: {path}")
    if any(frames[i].pts > frames[i + 1].pts for i in range(len(frames) - 1)):
        raise RuntimeError("decoded best-effort PTS sequence is not monotonic")
    return frames


def nearest_choices(frames: list[FramePTS], limit: int | None) -> list[TargetChoice]:
    pts = [frame.pts for frame in frames]
    choices: list[TargetChoice] = []
    target_index = 0
    while True:
        target = CADENCE * target_index
        if target > pts[-1]:
            break
        position = bisect.bisect_left(pts, target)
        candidates = []
        if position < len(frames):
            candidates.append(frames[position])
        if position > 0:
            candidates.append(frames[position - 1])
        chosen = min(candidates, key=lambda item: (abs(item.pts - target), item.pts, item.index))
        choices.append(TargetChoice(target_index, target, chosen.index, chosen.pts))
        target_index += 1
        if limit is not None and len(choices) >= limit:
            break
    return choices


def scaled_dimensions(native_w: int, native_h: int, analysis_w: int) -> tuple[int, int]:
    if analysis_w <= 0:
        raise ValueError("analysis width must be positive")
    height = int(native_h * analysis_w / native_w + 0.5)
    if height % 2:
        height += 1
    return analysis_w, height


def decode_selected(path: Path, choices: list[TargetChoice], width: int, height: int) -> dict[int, bytes]:
    wanted = sorted({choice.frame_index for choice in choices})
    wanted_set = set(wanted)
    max_index = wanted[-1]
    command = [
        "ffmpeg", "-v", "error", "-i", str(path), "-an",
        "-vf", f"scale={width}:{height}:flags=area,format=gray",
        "-frames:v", str(max_index + 1),
        "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
    ]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None
    frame_bytes = width * height
    selected: dict[int, bytes] = {}
    for frame_index in range(max_index + 1):
        data = proc.stdout.read(frame_bytes)
        if len(data) != frame_bytes:
            stderr = b"" if proc.stderr is None else proc.stderr.read()
            proc.kill()
            raise RuntimeError(
                f"short decoded frame {frame_index}: {len(data)}/{frame_bytes}: "
                + stderr.decode("utf-8", errors="replace")[-2000:]
            )
        if frame_index in wanted_set:
            selected[frame_index] = data
    proc.stdout.close()
    stderr = b"" if proc.stderr is None else proc.stderr.read()
    if proc.wait() != 0:
        raise RuntimeError(stderr.decode("utf-8", errors="replace")[-4000:])
    if set(selected) != wanted_set:
        raise RuntimeError("decoded frame set does not match selected frame set")
    return selected


def pgm_bytes(width: int, height: int, pixels: bytes) -> bytes:
    assert len(pixels) == width * height
    return b"P5\n%d %d\n255\n" % (width, height) + pixels


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--analysis-width", type=int, default=320)
    parser.add_argument("--limit", type=int, default=None, help="bounded smoke: first N targets only")
    args = parser.parse_args()

    actual_sha = sha256_file(args.input)
    if actual_sha != args.expected_sha256:
        raise SystemExit(
            f"SLICEEXTRACTFAIL|source_id={args.source_id}|reason=source_sha_mismatch"
            f"|actual={actual_sha}|expected={args.expected_sha256}|json=0"
        )

    native_w, native_h = probe_dimensions(args.input)
    out_w, out_h = scaled_dimensions(native_w, native_h, args.analysis_width)
    frames = probe_pts(args.input)
    choices = nearest_choices(frames, args.limit)
    selected = decode_selected(args.input, choices, out_w, out_h)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    stream_path = output / f"{args.source_id}.pgmstream"

    rows = [
        hbp_row(
            "SLICEHDR",
            schema=SCHEMA,
            source_id=args.source_id,
            source_basename=args.input.name,
            source_sha256=actual_sha,
            source_bytes=args.input.stat().st_size,
            native_width=native_w,
            native_height=native_h,
            analysis_width=out_w,
            analysis_height=out_h,
            decoded_pts_count=len(frames),
            cadence="0.100",
            target_rule="n*0.100s",
            selection_rule="nearest_decoded_best_effort_pts",
            tie_rule="absolute_error_then_lower_pts_then_lower_source_frame",
            scale_filter=f"scale={out_w}:{out_h}:flags=area,format=gray",
            ffmpeg_version=tool_version("ffmpeg"),
            ffprobe_version=tool_version("ffprobe"),
            raw_media_in_repo=0,
            **CLAIMS_GATE,
        )
    ]

    offset = 0
    with stream_path.open("wb") as stream:
        for choice in choices:
            chunk = pgm_bytes(out_w, out_h, selected[choice.frame_index])
            stream.write(chunk)
            rows.append(
                hbp_row(
                    "SLICE",
                    source_id=args.source_id,
                    target_index=choice.target_index,
                    target_pts=f"{choice.target_pts:.3f}",
                    actual_pts=f"{choice.actual_pts:.6f}",
                    error_s=f"{choice.error:.6f}",
                    abs_error_s=f"{abs(choice.error):.6f}",
                    source_frame=choice.frame_index,
                    source_frame_semantics="ffprobe_decoded_frame_order_zero_based",
                    offset=offset,
                    len=len(chunk),
                    sha256=sha256_bytes(chunk),
                )
            )
            offset += len(chunk)

    stream_sha = sha256_file(stream_path)
    rows.append(
        hbp_row(
            "SLICEFTR",
            source_id=args.source_id,
            targets=len(choices),
            unique_source_frames=len({choice.frame_index for choice in choices}),
            stream_file=stream_path.name,
            stream_bytes=offset,
            stream_sha256=stream_sha,
            limit=args.limit if args.limit is not None else "NONE",
            **CLAIMS_GATE,
        )
    )
    write_sha_sidecar(stream_path)
    hbp, hbi = write_hbp_hbi(output / f"{args.source_id}-SLICES", rows, SCHEMA)
    print(
        hbp_row(
            "SLICEEXTRACTPASS",
            source_id=args.source_id,
            targets=len(choices),
            stream_bytes=offset,
            stream_sha256=stream_sha,
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
