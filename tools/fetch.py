#!/usr/bin/env python3
"""Fetch GRF assets by path from the local roBrowser remote client."""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

BASE = os.environ.get("RO_ASSET_SERVER", "http://127.0.0.1:3338")
ROOT = Path(os.environ.get("RO_RAW_DIR", r"D:\ROweb\raw"))


def url_for(path: str) -> str:
    # GRF paths use backslashes; the server accepts both separators.
    return BASE + "/" + urllib.parse.quote(path.replace("\\", "/"))


def fetch(path: str, force: bool = False) -> Path:
    dest = ROOT / path.replace("\\", "/")
    if dest.exists() and not force and dest.stat().st_size > 0:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url_for(path), headers={"User-Agent": "roweb-build/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    if not data:
        raise RuntimeError(f"empty asset: {path}")
    dest.write_bytes(data)
    return dest


def main() -> int:
    for p in sys.argv[1:]:
        f = fetch(p)
        print(f"{f.stat().st_size:>10}  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
