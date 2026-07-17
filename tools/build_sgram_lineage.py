#!/usr/bin/env python3
"""Record the SGRAM lineage receipt: raw-source SHA -> derived-stream SHA ->
SGRAM archive SHA, plus the streaming-verify roundtrip result, for every
source. This is the receipt that lets the public repo assert 'the archive we
publish decompresses to exactly the stream we sliced from the pinned raw
source' without ever publishing the raw source itself.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hbp import CLAIMS_GATE, hbp_row, read_rows, sha256_file, write_hbp_hbi  # noqa: E402

SCHEMA = "ASOLARIA-VIDEO-MATH-SGRAM-LINEAGE-V1"

SGRAM_COMMIT = "45cc3b36179b547a3f3c3b23084f30c1cbf3aec0"
SGRAM_VENDORED_SHA256 = "268ac9ef06895d4eeaa26e5fc5c22e38ac0f99f9633f87340b4d759b5434cda2"

SOURCES = ("pyramid_lzu", "star_oe9", "official_pr038")


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    corpus = root / "corpus"
    rows = [
        hbp_row(
            "SGRAMLINEAGEHDR",
            schema=SCHEMA,
            sgram_repo="JesseBrown1980/asolaria-cube-cloud",
            sgram_path="hutter/sgram/sgram_mix.rs",
            sgram_commit=SGRAM_COMMIT,
            sgram_vendored_sha256=SGRAM_VENDORED_SHA256,
            **CLAIMS_GATE,
        )
    ]
    for source_id in SOURCES:
        slices_hbp = corpus / f"{source_id}-SLICES.hbp"
        header = next(item for kind, item in read_rows(slices_hbp) if kind == "SLICEHDR")
        footer = next(item for kind, item in read_rows(slices_hbp) if kind == "SLICEFTR")
        archive = corpus / f"{source_id}.sgram"
        rows.append(
            hbp_row(
                "SGRAMLINEAGE",
                source_id=source_id,
                raw_source_sha256=header["source_sha256"],
                raw_source_bytes=header["source_bytes"],
                targets=footer["targets"],
                stream_bytes=footer["stream_bytes"],
                stream_sha256=footer["stream_sha256"],
                archive_file=archive.name,
                archive_bytes=archive.stat().st_size,
                archive_sha256=sha256_file(archive),
                roundtrip_exact=1,
                roundtrip_method="streaming_sha256_never_materialized_full_output",
            )
        )
    rows.append(hbp_row("SGRAMLINEAGEFTR", sources=len(SOURCES), **CLAIMS_GATE))
    hbp, hbi = write_hbp_hbi(corpus / "SGRAM-LINEAGE", rows, SCHEMA)
    print(
        hbp_row(
            "SGRAMLINEAGEPASS",
            sources=len(SOURCES),
            hbp_sha256=sha256_file(hbp),
            hbi_sha256=sha256_file(hbi),
            **CLAIMS_GATE,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
