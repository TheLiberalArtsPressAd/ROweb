#!/usr/bin/env python3
"""Carve assets out of a protected/GRF-like archive.

The data.grf shipped with the TW client in this workspace has a scrambled
header and file table, but every entry body is still a plain zlib stream.
This tool walks the archive, inflates every zlib stream it can validate and
classifies the result by magic bytes.  Output is written to
<out>/<kind>/<offset>.<ext> plus manifest.jsonl.

Usage:
  python carve_grf.py INPUT [--out DIR] [--limit BYTES] [--max-entry MB]
"""
from __future__ import annotations

import argparse
import json
import mmap
import os
import struct
import zlib
from pathlib import Path

MAGICS = [
    (b"GRGN", "gnd", "gnd"),
    (b"GRAT", "gat", "gat"),
    (b"GRSW", "rsw", "rsw"),
    (b"GRSM", "rsm", "rsm"),
    (b"SP\x01", "spr", "spr"),
    (b"SP\x02", "spr", "spr"),
    (b"AC\x01", "act", "act"),
    (b"AC\x02", "act", "act"),
    (b"AC\x03", "act", "act"),
    (b"AC\x04", "act", "act"),
    (b"AC\x05", "act", "act"),
    (b"\x89PNG", "png", "png"),
    (b"BM", "bmp", "bmp"),
    (b"\xff\xd8\xff", "jpg", "jpg"),
    (b"OggS", "ogg", "ogg"),
    (b"RIFF", "wav", "wav"),
    (b"ID3", "mp3", "mp3"),
    (b"\x1bLua", "lua", "lua"),
    (b"<?xm", "xml", "xml"),
    (b"PK\x03\x04", "zip", "zip"),
    (b"\x00\x00\x02\x00", "tga", "tga"),
]
# zlib CMF/FLG pairs that are valid for level 0..9 and different window sizes
ZLIB_HEADS = [b"\x78\x01", b"\x78\x5e", b"\x78\x9c", b"\x78\xda"]


def classify(data: bytes):
    for magic, kind, ext in MAGICS:
        if data.startswith(magic):
            return kind, ext
    return "bin", "bin"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input")
    ap.add_argument("--out", default="carved")
    ap.add_argument("--limit", type=int, default=0, help="scan only first N bytes")
    ap.add_argument("--max-entry", type=int, default=192, help="max inflated MB per entry")
    ap.add_argument("--start", type=int, default=0)
    args = ap.parse_args()

    src = Path(args.input)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    max_out = args.max_entry * 1024 * 1024

    f = open(src, "rb")
    mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
    size = len(mm)
    end = min(size, args.limit) if args.limit else size
    print(f"scanning {src} ({size:,} bytes, end={end:,})", flush=True)

    hits = 0
    ok = 0
    skipped = 0
    covered_until = args.start
    pos = args.start
    manifest = open(out / "manifest.jsonl", "w", encoding="utf8")
    counts: dict[str, int] = {}
    bytes_by_kind: dict[str, int] = {}

    while pos < end:
        # find the next zlib header
        best = -1
        for h in ZLIB_HEADS:
            i = mm.find(h, pos, end)
            if i >= 0 and (best < 0 or i < best):
                best = i
        if best < 0:
            break
        hits += 1
        if best < covered_until:
            skipped += 1
            pos = best + 1
            continue

        d = zlib.decompressobj()
        chunks = []
        total = 0
        cursor = best
        valid = False
        try:
            while cursor < end:
                buf = mm[cursor : min(cursor + 262144, end)]
                piece = d.decompress(buf, 1048576)
                if piece:
                    total += len(piece)
                    if total > max_out:
                        raise ValueError("too large")
                    chunks.append(piece)
                if d.eof:
                    consumed = len(buf) - len(d.unused_data)
                    cursor += consumed
                    valid = True
                    break
                cursor += len(buf)
                if not buf:
                    break
        except Exception:
            valid = False

        if valid and total > 0:
            data = b"".join(chunks)
            kind, ext = classify(data)
            ddir = out / kind
            ddir.mkdir(exist_ok=True)
            name = f"{best:012d}.{ext}"
            (ddir / name).write_bytes(data)
            manifest.write(
                json.dumps(
                    {
                        "kind": kind,
                        "offset": best,
                        "end": cursor,
                        "compressed": cursor - best,
                        "size": total,
                        "file": f"{kind}/{name}",
                        "crc32": zlib.crc32(data),
                    }
                )
                + "\n"
            )
            ok += 1
            counts[kind] = counts.get(kind, 0) + 1
            bytes_by_kind[kind] = bytes_by_kind.get(kind, 0) + total
            covered_until = cursor
            pos = cursor
            if ok % 500 == 0:
                print(f"  {best:,}: {ok} extracted ({kind})", flush=True)
        else:
            pos = best + 1

    manifest.close()
    print(f"done: hits={hits} extracted={ok} skipped={skipped}")
    for k in sorted(counts, key=lambda x: -bytes_by_kind[x]):
        print(f"  {k:6s} {counts[k]:7d} files {bytes_by_kind[k]/1048576:10.1f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
