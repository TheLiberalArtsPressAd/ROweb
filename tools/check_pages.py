#!/usr/bin/env python3
"""Sanity-check the published site in docs/ before it goes to GitHub Pages.

Catches the failure modes that are invisible locally but break the deployed
build:

  * index.html points at a client pack that is missing from docs/,
  * a manifest entry points at an asset that was not copied,
  * the asset pack and the client disagree about the build stamp,
  * the site (or a single file) is over GitHub's limits (1 GiB / 100 MiB).

    python tools/check_pages.py [docs-dir]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

MIB = 1024 * 1024
SITE_LIMIT = 1024 * MIB
FILE_LIMIT = 100 * MIB
CONFIG_RE = re.compile(r"const GODOT_CONFIG = (\{[^\n]*\});")


def fail(msg: str) -> None:
    print("FAIL:", msg)
    raise SystemExit(1)


def check(root: Path) -> None:
    index = root / "index.html"
    assets = root / "assets"
    if not index.is_file():
        fail(f"{index} is missing")
    if not (root / ".nojekyll").is_file():
        fail(".nojekyll is missing (GitHub Pages would run Jekyll)")

    html = index.read_text(encoding="utf8")
    match = CONFIG_RE.search(html)
    if not match:
        fail("GODOT_CONFIG not found in index.html")
    config = json.loads(match.group(1))
    pack = config.get("mainPack")
    if not pack:
        fail("index.html does not pin a client pack (mainPack)")
    if not (root / pack).is_file():
        fail(f"index.html points at {pack}, which is not in the site")

    stamp = re.search(r'window\.RO_ASSET_BUILD = "([^"]*)"', html)
    if not stamp:
        fail("index.html is missing the RO_ASSET_BUILD stamp")

    manifest_path = assets / "manifest.json"
    if not manifest_path.is_file():
        fail("assets/manifest.json is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf8"))

    wanted: list[str] = []
    for key in ("terrain", "walk"):
        if key in manifest:
            wanted.append(str(manifest[key]))
    if manifest.get("props"):
        wanted.append(str(manifest["props"]))
    for sprite in manifest.get("sprites", []):
        wanted.append(f"{sprite['file']}.webp")
        wanted.append(f"{sprite['file']}.json")
    audio = manifest.get("audio") or {}
    if audio.get("file"):
        wanted.append(str(audio["file"]))
    for entry in manifest.get("files", []):
        wanted.append(str(entry) if isinstance(entry, str) else str(entry.get("path", "")))

    for rel in sorted(set(wanted)):
        if rel and not (assets / rel).is_file():
            fail(f"manifest references assets/{rel}, which is missing")

    terrain = json.loads((assets / str(manifest["terrain"])).read_text(encoding="utf8"))
    map_dir = (assets / str(manifest["terrain"])).parent
    for key in ("atlas", "lightmap"):
        file = (terrain.get(key) or {}).get("file")
        if file and not (map_dir / file).is_file():
            fail(f"terrain.json references {key} {file}, which is missing")
    walk_file = (terrain.get("walk") or {}).get("file")
    if walk_file and not (map_dir / walk_file).is_file():
        fail(f"terrain.json references walk {walk_file}, which is missing")

    props = json.loads((assets / str(manifest["props"])).read_text(encoding="utf8"))
    for group in props.get("groups", []):
        texture = str(group.get("texture", ""))
        if texture and not (assets / texture).is_file():
            fail(f"props.json references {texture}, which is missing")

    files = [p for p in root.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    largest = max(files, key=lambda p: p.stat().st_size)
    if total > SITE_LIMIT:
        fail(f"site is {total / MIB:.1f} MiB, over the 1 GiB Pages limit")
    if largest.stat().st_size > FILE_LIMIT:
        fail(f"{largest.name} is over 100 MiB")

    print(
        f"OK: {total / MIB:.1f} MiB in {len(files)} files, pack {pack}, "
        f"asset build {stamp.group(1)}, largest {largest.name} "
        f"({largest.stat().st_size / MIB:.1f} MiB)"
    )


if __name__ == "__main__":
    check(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "docs")
