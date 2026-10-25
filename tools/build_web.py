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
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME = ROOT / "game"
ASSETS = ROOT / "web" / "assets"
DOCS = ROOT / "docs"
DEFAULT_GODOT = ROOT / "godot_bin" / "Godot_v4.7.2-stable_win64_console.exe"
MIB = 1024 * 1024
GIB = 1024 * MIB
WASM_MAX_PAGES = 16384  # 16384 * 64 KiB = 1 GiB


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+", " ".join(str(c) for c in cmd))
    subprocess.run(cmd, cwd=cwd, check=True)


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

    # 5. size report / budget check
    files = [p for p in args.out.rglob("*") if p.is_file()]
    total = sum(p.stat().st_size for p in files)
    largest = max(files, key=lambda p: p.stat().st_size)
    info = {
        "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
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
