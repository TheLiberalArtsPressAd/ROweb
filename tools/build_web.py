#!/usr/bin/env python3
"""Build the Godot web export into docs/ for GitHub Pages.

Pipeline:
  1. colour-key the magenta prop textures (tools/degrade_assets.py, once),
  2. import + export the Godot project with the single-threaded Web preset,
  3. copy the external asset pack next to index.html,
  4. patch the wasm memory section so the heap can never exceed 1 GiB,
  5. verify the published site is under the GitHub Pages 1 GiB budget.

Run from the repository root:

    python tools/build_web.py

Requires Godot 4.7.2 (godot_bin/Godot_v4.7.2-stable_win64_console.exe by
default) and the matching export templates (web_nothreads_release.zip).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "game"
ASSETS = ROOT / "web" / "assets"
DOCS = ROOT / "docs"
PCK_CACHE = ROOT / "build" / "pck_cache"
DEFAULT_GODOT = ROOT / "godot_bin" / "Godot_v4.7.2-stable_win64_console.exe"
MIB = 1024 * 1024
GIB = 1024 * MIB
WASM_MAX_PAGES = 16384  # 16384 * 64 KiB = 1 GiB
KEEP_OLD_PCKS = 4

CONFIG_RE = re.compile(r"const GODOT_CONFIG = (\{[^\n]*\});")


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


def short_hash(data: bytes, length: int = 10) -> str:
    return hashlib.sha256(data).hexdigest()[:length]


def tree_hash(root: Path) -> str:
    """Stable hash of a directory's contents (paths + bytes)."""
    digest = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        digest.update(str(path.relative_to(root)).replace("\\", "/").encode())
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()[:12]


def stash_old_pcks(out: Path) -> None:
    """Save previously published content-addressed packs before docs/ is wiped."""
    if not out.is_dir():
        return
    PCK_CACHE.mkdir(parents=True, exist_ok=True)
    for candidate in out.glob("index.*.pck"):
        target = PCK_CACHE / candidate.name
        if not target.exists():
            shutil.copy2(candidate, target)


def carry_over_pcks(out: Path, new_name: str) -> list[str]:
    """Keep the previous content-addressed packs next to the new build.

    index.html always points at ``index.<hash>.pck``.  A browser that still has
    an older index.html cached for a few minutes will ask for the *old* hash,
    so those files have to stay reachable for a while.
    """
    kept = sorted(PCK_CACHE.glob("index.*.pck"), key=lambda p: p.stat().st_mtime, reverse=True)
    names: list[str] = []
    for pck in kept[:KEEP_OLD_PCKS]:
        if pck.name == new_name:
            continue
        if not (out / pck.name).exists():
            shutil.copy2(pck, out / pck.name)
        names.append(pck.name)
    for stale in kept[KEEP_OLD_PCKS:]:
        stale.unlink()
    return names


def patch_index_html(path: Path, pack_name: str, pack_bytes: int, asset_build: str) -> None:
    """Point the shell at the content-addressed pack and stamp the asset pack.

    GitHub Pages serves everything with ``Cache-Control: max-age=600``, so the
    plain ``index.pck`` URL can keep handing out the *previous* client build for
    ten minutes after a deploy.  Versioning the pack name makes the HTML and the
    client it starts upgrade atomically.
    """
    html = path.read_text(encoding="utf8")
    match = CONFIG_RE.search(html)
    if not match:
        raise SystemExit("could not find GODOT_CONFIG in the exported index.html")
    config = json.loads(match.group(1))
    config["mainPack"] = pack_name
    sizes = config.get("fileSizes") or {}
    if isinstance(sizes, list):  # older shells allow a list, we need the dict form
        sizes = {}
    sizes[pack_name] = pack_bytes
    config["fileSizes"] = sizes
    html = html[: match.start(1)] + json.dumps(config, separators=(",", ":")) + html[match.end(1) :]

    stamp = f'<script>window.RO_ASSET_BUILD = "{asset_build}";</script>\n\t\t'
    marker = '<script src="index.js"></script>'
    if "RO_ASSET_BUILD" not in html:
        if marker not in html:
            raise SystemExit("could not find the index.js script tag in index.html")
        html = html.replace(marker, stamp + marker, 1)
    path.write_text(html, encoding="utf8")


def leb128(data: bytes, offset: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        byte = data[offset]
        offset += 1
        result |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return result, offset


def patch_wasm_memory(path: Path, max_pages: int = WASM_MAX_PAGES) -> bool:
    """Cap the WebAssembly heap by rewriting the memory section maximum.

    Emscripten emits a fixed maximum (2 GiB for wasm32).  The maximum is a
    LEB128 integer in section 5; both 32768 and 16384 use three bytes, so the
    section size does not change.
    """
    data = bytearray(path.read_bytes())
    if data[:4] != b"\x00asm":
        raise SystemExit(f"{path} is not a wasm module")
    offset = 8
    while offset < len(data):
        section_id = data[offset]
        offset += 1
        size, body = leb128(data, offset)
        if section_id == 5:  # memory section
            count, p = leb128(data, body)
            for _ in range(count):
                flags = data[p]
                p += 1
                _minimum, p = leb128(data, p)
                if not flags & 1:
                    continue
                current, q = leb128(data, p)
                if current == max_pages:
                    return False
                if current != 32768:
                    raise SystemExit(f"unexpected wasm memory max {current} pages")
                encoded = bytearray()
                value = max_pages
                while True:
                    byte = value & 0x7F
                    value >>= 7
                    if value:
                        encoded.append(byte | 0x80)
                    else:
                        encoded.append(byte)
                        break
                if len(encoded) != q - p:
                    raise SystemExit("cannot patch wasm memory max in place")
                data[p:q] = encoded
                path.write_bytes(data)
                return True
            return False
        offset = body + size
    raise SystemExit("memory section not found in wasm")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--godot", type=Path, default=DEFAULT_GODOT)
    ap.add_argument("--out", type=Path, default=DOCS)
    ap.add_argument("--limit-mib", type=int, default=1024)
    ap.add_argument("--skip-degrade", action="store_true")
    args = ap.parse_args()

    godot = args.godot
    if not godot.exists():
        raise SystemExit(f"Godot not found: {godot} (pass --godot)")
    if not ASSETS.is_dir():
        raise SystemExit(f"asset pack not found: {ASSETS}")

    # 1. colour-key pass (idempotent via sentinel)
    sentinel = ASSETS / ".degraded"
    if not args.skip_degrade and not sentinel.exists():
        run([sys.executable, str(ROOT / "tools" / "degrade_assets.py")])
        sentinel.write_text(time.strftime("%Y-%m-%d %H:%M:%S"), encoding="utf8")
    elif sentinel.exists():
        print("degrade: already applied (web/assets/.degraded)")

    # 2. import + export
    run([str(godot), "--headless", "--path", str(GAME), "--import"])
    stash_old_pcks(args.out)
    if args.out.exists():
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True)
    run(
        [
            str(godot),
            "--headless",
            "--path",
            str(GAME),
            "--export-release",
            "Web",
            str(args.out / "index.html"),
        ]
    )

    # 3. external asset pack
    shutil.copytree(ASSETS, args.out / "assets")
    (args.out / ".nojekyll").write_text("", encoding="utf8")

    # 4. hard 1 GiB wasm heap cap
    wasm = args.out / "index.wasm"
    patched = patch_wasm_memory(wasm)
    print(f"wasm: memory max -> {WASM_MAX_PAGES * 64 // 1024} MiB" if patched else "wasm: memory cap already set")

    # 5. content-addressed client pack + asset stamp
    #    GitHub Pages caches for ten minutes, so a fixed index.pck name can
    #    start a stale client against a fresh asset pack (that is what produced
    #    "could not load assets/manifest.json").  The hash name makes the HTML,
    #    the client and the assets upgrade together.
    pck = args.out / "index.pck"
    client_build = short_hash(pck.read_bytes())
    pack_name = f"index.{client_build}.pck"
    shutil.copy2(pck, args.out / pack_name)
    asset_build = tree_hash(ASSETS)
    old_packs = carry_over_pcks(args.out, pack_name)
    patch_index_html(args.out / "index.html", pack_name, pck.stat().st_size, asset_build)
    print(f"client: {pack_name} (asset build {asset_build}, kept {len(old_packs)} older packs)")

    # 6. size report / budget check
    files = [p for p in args.out.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    largest = max(files, key=lambda p: p.stat().st_size)
    info = {
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "client_build": client_build,
        "asset_build": asset_build,
        "pack": pack_name,
        "files": len(files),
        "total_bytes": total,
        "total_mib": round(total / MIB, 2),
        "wasm_bytes": wasm.stat().st_size,
        "wasm_memory_max_mib": WASM_MAX_PAGES * 64 // 1024,
        "largest": {"path": str(largest.relative_to(args.out)), "bytes": largest.stat().st_size},
    }
    (args.out / "build-info.json").write_text(json.dumps(info, indent=2), encoding="utf8")

    print(
        f"site: {total / MIB:.2f} MiB in {len(files)} files "
        f"(wasm {wasm.stat().st_size / MIB:.2f} MiB, max heap 1024 MiB)"
    )
    if total > args.limit_mib * MIB:
        raise SystemExit(f"site exceeds {args.limit_mib} MiB budget")
    if largest.stat().st_size > 100 * MIB:
        raise SystemExit(f"file exceeds GitHub's 100 MiB limit: {largest}")
    print(f"OK: under the {args.limit_mib} MiB budget")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
