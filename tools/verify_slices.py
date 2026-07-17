#!/usr/bin/env python3
"""Independent structural verifier for the derived-slice corpus.

Needs no raw media: verifies sha sidecars, HBI byte-range coverage, every
SLICE row's stream range hash, the PTS cadence math, and that the claims-gate
rows are present and un-inflated. This is the cloud gate for corpus integrity.
"""

from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hbp import (  # noqa: E402
    hbp_row,
    parse_row,
    read_rows,
    sha256_bytes,
    sha256_file,
    verify_hbi,
    verify_sha_sidecar,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def verify_source(corpus: Path, source_id: str) -> tuple[int, int]:
    stream = corpus / f"{source_id}.pgmstream"
    hbp = corpus / f"{source_id}-SLICES.hbp"
    hbi = corpus / f"{source_id}-SLICES.hbi"
    for path in (stream, hbp, hbi):
        require(path.is_file(), f"missing {path}")
        verify_sha_sidecar(path)
    rows = verify_hbi(hbp, hbi)

    data = stream.read_bytes()
    parsed = read_rows(hbp)
    require(parsed[0][0] == "SLICEHDR", "missing SLICEHDR")
    require(parsed[-1][0] == "SLICEFTR", "missing SLICEFTR")
    header = parsed[0][1]
    footer = parsed[-1][1]
    for gate in (header, footer):
        require(gate["fire"] == "0", "fire inflated")
        require(gate["physical_claim"] == "0", "physical_claim inflated")
        require(gate["object_identity_claim"] == "0", "object_identity_claim inflated")
        require(gate["authenticity"] == "UNRESOLVED", "authenticity inflated")
    require(header["raw_media_in_repo"] == "0", "raw media lane violated")

    offset = 0
    count = 0
    previous_target = -1
    for kind, item in parsed[1:-1]:
        require(kind == "SLICE", f"unexpected row kind {kind}")
        target_index = int(item["target_index"])
        require(target_index == previous_target + 1, "target index gap")
        previous_target = target_index
        require(
            Decimal(item["target_pts"]) == Decimal(target_index) / Decimal(10),
            "target PTS is not n*0.100",
        )
        require(
            Decimal(item["actual_pts"]) - Decimal(item["target_pts"]) == Decimal(item["error_s"]),
            "PTS error arithmetic mismatch",
        )
        start, length = int(item["offset"]), int(item["len"])
        require(start == offset, "stream offset gap")
        chunk = data[start : start + length]
        require(len(chunk) == length, "short stream range")
        require(sha256_bytes(chunk) == item["sha256"], "slice sha mismatch")
        require(chunk.startswith(b"P5\n"), "slice is not P5")
        offset += length
        count += 1

    require(offset == len(data), "stream not fully covered by SLICE rows")
    require(int(footer["targets"]) == count, "footer target count mismatch")
    require(int(footer["stream_bytes"]) == len(data), "footer stream bytes mismatch")
    require(footer["stream_sha256"] == sha256_file(stream), "footer stream sha mismatch")
    return rows, count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--source-id", action="append", required=True)
    args = parser.parse_args()
    total_rows = total_slices = 0
    for source_id in args.source_id:
        rows, count = verify_source(args.corpus.resolve(), source_id)
        total_rows += rows
        total_slices += count
    print(
        hbp_row(
            "SLICEVERIFYPASS",
            sources=len(args.source_id),
            source_ids=args.source_id,
            hbp_rows=total_rows,
            slices=total_slices,
            fire=0,
            physical_claim=0,
            authenticity="UNRESOLVED",
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"SLICEVERIFYFAIL|error={exc}|fire=0|json=0", file=sys.stderr)
        raise SystemExit(1)
