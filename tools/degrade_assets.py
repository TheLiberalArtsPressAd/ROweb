#!/usr/bin/env python3
"""Post-process the web asset pack for the browser build.

Ragnarok's BMP/RSM textures use pure magenta (255, 0, 255) as a colour key
instead of an alpha channel.  The original pack kept that magenta, which shows
up as bright pink billboards in the Godot client.  This pass:

  * turns magenta colour-key pixels into real alpha (with a soft edge matte),
  * flips ``alpha`` on the affected prop material groups,
  * re-encodes the small prop textures as WebP with alpha,
  * reports the total size so the GitHub Pages 1 GiB budget can be enforced.

It is intentionally a post-process: ``build_assets.py`` keeps doing the heavy
GRF work, and this pass is cheap enough to run on every web export.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ASSETS = ROOT / "web" / "assets"


def colour_key_to_alpha(im: Image.Image) -> tuple[Image.Image, bool]:
    """Replace magenta colour-key pixels with alpha, recovering edge colour."""
    rgba = np.asarray(im.convert("RGBA"), dtype=np.float32)
    rgb = rgba[..., :3]
    alpha = rgba[..., 3] / 255.0

    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    # 1.0 for pure magenta, 0.0 for greys/whites and for red/blue/green.
    key = np.clip((np.minimum(r, b) - g - 8.0) / 120.0, 0.0, 1.0)
    new_alpha = alpha * (1.0 - key)

    # Un-composite the pixel from its magenta background so filtered edges do
    # not keep a pink fringe: C = a*F + (1-a)*M, solve for F.
    safe = new_alpha > 0.02
    out = np.zeros_like(rgb)
    a = np.where(safe, new_alpha, 1.0)[..., None]
    recovered = (rgb - (1.0 - a) * np.array([255.0, 0.0, 255.0], dtype=np.float32)) / a
    out = np.where(safe[..., None], np.clip(recovered, 0.0, 255.0), 0.0)

    result = np.empty_like(rgba)
    result[..., :3] = out
    result[..., 3] = np.clip(new_alpha * 255.0, 0.0, 255.0)

    changed = bool(np.any(new_alpha < alpha - 0.002))
    return Image.fromarray(result.round().astype(np.uint8), "RGBA"), changed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--assets", type=Path, default=DEFAULT_ASSETS)
    ap.add_argument("--quality", type=int, default=90)
    ap.add_argument("--force", action="store_true", help="re-run even if already applied")
    args = ap.parse_args()

    assets: Path = args.assets
    tex_dir = assets / "textures"
    if not tex_dir.is_dir():
        raise SystemExit(f"missing texture directory: {tex_dir}")

    sentinel = assets / ".degraded"
    if sentinel.exists() and not args.force:
        print(f"degrade: already applied ({sentinel})")
        return 0

    transparent: set[str] = set()
    converted = 0
    before = 0
    after = 0
    for path in sorted(tex_dir.glob("*.webp")):
        before += path.stat().st_size
        im = Image.open(path).convert("RGBA")
        im2, changed = colour_key_to_alpha(im)
        if changed:
            converted += 1
            transparent.add(path.name)
            im2.save(path, "WEBP", quality=args.quality, alpha_quality=100, method=6)
        after += path.stat().st_size
        # A texture can also carry a real alpha channel from the source data.
        if im2.getchannel("A").getextrema()[0] < 250:
            transparent.add(path.name)

    # Flip the per-material alpha flag so the client enables alpha scissor.
    group_files = list(assets.glob("map/*/props.json"))
    groups_updated = 0
    for jf in group_files:
        data = json.loads(jf.read_text(encoding="utf8"))
        for group in data.get("groups", []):
            tex = str(group.get("texture", ""))
            name = tex.rsplit("/", 1)[-1]
            if name in transparent and not group.get("alpha"):
                group["alpha"] = True
                groups_updated += 1
        jf.write_text(json.dumps(data, ensure_ascii=False), encoding="utf8")

    total = sum(p.stat().st_size for p in assets.rglob("*") if p.is_file())
    print(f"degrade: {converted} textures colour-keyed, {groups_updated} groups -> alpha")
    print(f"degrade: textures {before / 1e6:.2f} MB -> {after / 1e6:.2f} MB")
    print(f"degrade: asset pack total {total / (1024 * 1024):.2f} MiB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
