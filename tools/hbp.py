#!/usr/bin/env python3
"""Shared HBP/HBI tuple-row helpers for the video-math tournament.

Delimiter-anchored format law: rows split on `|` then `=` — never bare
substring matching. Every row ends with json=0 (hot-path, cold JSON banned
for system artifacts). See PROJECT-CONTRACT.hbp for the governing claims gate.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Iterable, Sequence


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def tuple_value(value: object) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return ",".join(tuple_value(item) for item in value)
    return (
        str(value)
        .replace("%", "%25")
        .replace("|", "%7C")
        .replace("\r", "%0D")
        .replace("\n", "%0A")
    )


def hbp_row(kind: str, **fields: object) -> str:
    parts = [kind]
    parts.extend(f"{key}={tuple_value(value)}" for key, value in fields.items())
    if "json" not in fields:
        parts.append("json=0")
    return "|".join(parts)


def parse_row(line: str) -> tuple[str, dict[str, str]]:
    """Split on `|` then `=` — the delimiter-anchored parse law."""
    parts = line.rstrip("\r\n").split("|")
    parsed: dict[str, str] = {}
    for part in parts[1:]:
        if "=" in part:
            key, value = part.split("=", 1)
            parsed[key] = (
                value.replace("%0A", "\n")
                .replace("%0D", "\r")
                .replace("%7C", "|")
                .replace("%25", "%")
            )
    return parts[0], parsed


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def write_sha_sidecar(path: Path) -> Path:
    sidecar = path.with_name(path.name + ".sha256")
    atomic_write(sidecar, f"{sha256_file(path)}  {path.name}\n".encode("utf-8"))
    return sidecar


def verify_sha_sidecar(path: Path) -> None:
    sidecar = path.with_name(path.name + ".sha256")
    expected, name = sidecar.read_text(encoding="utf-8").strip().split(None, 1)
    if name.strip() != path.name:
        raise AssertionError(f"sidecar name mismatch: {sidecar}")
    if sha256_file(path) != expected:
        raise AssertionError(f"sidecar hash mismatch: {path}")


def write_hbp_hbi(base: Path, rows: Sequence[str], schema: str) -> tuple[Path, Path]:
    """Write base.hbp (LF rows) + base.hbi byte-range index + sha sidecars."""
    hbp = base.with_suffix(".hbp")
    normalized = [row.rstrip("\r\n") + "\n" for row in rows]
    payload = "".join(normalized).encode("utf-8")
    atomic_write(hbp, payload)
    offset = 0
    index = [
        hbp_row(
            "HBIHDR",
            schema=schema,
            source_file=hbp.name,
            source_bytes=len(payload),
            source_sha256=sha256_bytes(payload),
            row_count=len(normalized),
            offsets="UTF8_BYTES",
            line_endings="LF",
        )
    ]
    for number, line in enumerate(normalized, 1):
        encoded = line.encode("utf-8")
        index.append(
            hbp_row(
                "HBIROW",
                row=number,
                offset=offset,
                len=len(encoded),
                sha256=sha256_bytes(encoded),
            )
        )
        offset += len(encoded)
    index.append(
        hbp_row(
            "HBIFTR",
            source_file=hbp.name,
            indexed_bytes=offset,
            source_bytes=len(payload),
            complete=offset == len(payload),
        )
    )
    hbi = base.with_suffix(".hbi")
    atomic_write(hbi, "".join(row + "\n" for row in index).encode("utf-8"))
    write_sha_sidecar(hbp)
    write_sha_sidecar(hbi)
    return hbp, hbi


def verify_hbi(hbp: Path, hbi: Path) -> int:
    """Every HBI byte range must re-hash to its recorded sha; full coverage."""
    data = hbp.read_bytes()
    rows = 0
    header_seen = footer_seen = False
    for line in hbi.read_text(encoding="utf-8").splitlines():
        kind, item = parse_row(line)
        if kind == "HBIHDR":
            header_seen = True
            assert int(item["source_bytes"]) == len(data), "HBI source_bytes mismatch"
            assert item["source_sha256"] == sha256_bytes(data), "HBI source_sha256 mismatch"
        elif kind == "HBIROW":
            offset, length = int(item["offset"]), int(item["len"])
            payload = data[offset : offset + length]
            assert len(payload) == length, "HBI short range"
            assert sha256_bytes(payload) == item["sha256"], "HBI range sha mismatch"
            rows += 1
        elif kind == "HBIFTR":
            footer_seen = True
            assert item["complete"] == "1", "HBI incomplete"
            assert int(item["indexed_bytes"]) == len(data), "HBI coverage gap"
    assert header_seen and footer_seen, "HBI missing header/footer"
    assert rows == len(data.splitlines()), "HBI row count mismatch"
    return rows


CLAIMS_GATE = dict(
    fire=0,
    physical_claim=0,
    object_identity_claim=0,
    authenticity="UNRESOLVED",
    E=0,
)


def read_rows(hbp: Path) -> list[tuple[str, dict[str, str]]]:
    return [parse_row(line) for line in hbp.read_text(encoding="utf-8").splitlines()]


def iter_pgm_slices(stream: Path, slices_hbp: Path) -> Iterable[tuple[dict[str, str], bytes]]:
    """Yield (slice-row fields, raw gray bytes) for each SLICE row, verifying
    the recorded sha over the stream range before yielding."""
    data = stream.read_bytes()
    for kind, item in read_rows(slices_hbp):
        if kind != "SLICE":
            continue
        offset, length = int(item["offset"]), int(item["len"])
        chunk = data[offset : offset + length]
        assert sha256_bytes(chunk) == item["sha256"], f"slice sha mismatch @ {offset}"
        header, _, rest = chunk.partition(b"\n")
        assert header == b"P5", "not a P5 slice"
        dims, _, rest = rest.partition(b"\n")
        width, height = (int(token) for token in dims.split())
        maxval, _, pixels = rest.partition(b"\n")
        assert maxval == b"255", "unexpected maxval"
        assert len(pixels) == width * height, "pixel length mismatch"
        item = dict(item)
        item["width"], item["height"] = str(width), str(height)
        yield item, pixels
