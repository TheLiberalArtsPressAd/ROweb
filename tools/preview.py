#!/usr/bin/env python3
"""Software previews of the baked map, used to sanity-check transforms.

  top    orthographic top-down of terrain + props
  front  elevation view along +Z (shows whether props stand on the ground)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(r"D:\ROweb")
ASSETS = ROOT / "web" / "assets"


def load_terrain(map_name="prontera"):
    d = ASSETS / "map" / map_name
    raw = (d / "terrain.bin").read_bytes()
    assert raw[:4] == b"ROM2"
    nv = np.frombuffer(raw[4:8], np.uint32)[0]
    ni = np.frombuffer(raw[8:12], np.uint32)[0]
    o = 12
    pos = np.frombuffer(raw[o : o + nv * 12], np.float32).reshape(-1, 3).copy(); o += nv * 12
    uv = np.frombuffer(raw[o : o + nv * 8], np.float32).reshape(-1, 2).copy(); o += nv * 8
    uv2 = np.frombuffer(raw[o : o + nv * 8], np.float32).reshape(-1, 2).copy(); o += nv * 8
    col = np.frombuffer(raw[o : o + nv * 4], np.uint8).reshape(-1, 4).copy(); o += nv * 4
    idx = np.frombuffer(raw[o : o + ni * 4], np.uint32).reshape(-1, 3).copy()
    meta = json.loads((d / "terrain.json").read_text(encoding="utf8"))
    return pos, uv, uv2, col, idx, meta


def load_props(map_name="prontera"):
    d = ASSETS / "map" / map_name
    raw = (d / "props.bin").read_bytes()
    assert raw[:4] == b"ROPR"
    ng = np.frombuffer(raw[4:8], np.uint32)[0]
    nv = np.frombuffer(raw[8:12], np.uint32)[0]
    ni = np.frombuffer(raw[12:16], np.uint32)[0]
    o = 16
    pos = np.frombuffer(raw[o : o + nv * 12], np.float32).reshape(-1, 3); o += nv * 12
    nrm = np.frombuffer(raw[o : o + nv * 12], np.float32).reshape(-1, 3); o += nv * 12
    uv = np.frombuffer(raw[o : o + nv * 8], np.float32).reshape(-1, 2); o += nv * 8
    col = np.frombuffer(raw[o : o + nv * 4], np.uint8).reshape(-1, 4); o += nv * 4
    idx = np.frombuffer(raw[o : o + ni * 4], np.uint32).reshape(-1, 3)
    groups = json.loads((d / "props.json").read_text(encoding="utf8"))["groups"]
    return pos, nrm, uv, col, idx, groups


def raster(pos, idx, w, h, sx, sz, ox, oz, value, zbuf, img):
    """Project triangles onto the XZ plane, z-buffering by `value`."""
    for tri in idx:
        p = pos[tri]
        xs = (p[:, 0] * sx + ox)
        zs = (p[:, 2] * sz + oz)
        x0, x1 = int(np.floor(xs.min())), int(np.ceil(xs.max()))
        z0, z1 = int(np.floor(zs.min())), int(np.ceil(zs.max()))
        if x1 < 0 or z1 < 0 or x0 >= w or z0 >= h:
            continue
        x0, x1 = max(x0, 0), min(x1, w - 1)
        z0, z1 = max(z0, 0), min(z1, h - 1)
        if x0 > x1 or z0 > z1:
            continue
        gx, gz = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(z0, z1 + 1) + 0.5)
        d = (zs[1] - zs[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (zs[0] - zs[2])
        if abs(d) < 1e-9:
            continue
        a = ((zs[1] - zs[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gz - zs[2])) / d
        b = ((zs[2] - zs[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gz - zs[2])) / d
        c = 1 - a - b
        inside = (a >= -0.02) & (b >= -0.02) & (c >= -0.02)
        if not inside.any():
            continue
        v = a * value[tri[0]] + b * value[tri[1]] + c * value[tri[2]]
        sub = zbuf[z0 : z1 + 1, x0 : x1 + 1]
        mask = inside & (v > sub)
        if mask.any():
            sub[mask] = v[mask]
            img[z0 : z1 + 1, x0 : x1 + 1][mask] = 1.0


def main():
    scale = 2.0
    pos, uv, uv2, col, idx, meta = load_terrain()
    W = int(meta["width"] * 2 * scale)
    H = int(meta["height"] * 2 * scale)

    atlas = np.asarray(Image.open(ASSETS / "map" / "prontera" / "atlas.webp").convert("RGB"), np.float32) / 255.0
    lm = np.asarray(Image.open(ASSETS / "map" / "prontera" / "lightmap.png").convert("RGB"), np.float32) / 255.0

    def sample(tex, u, v):
        x = np.clip((u * tex.shape[1]).astype(int), 0, tex.shape[1] - 1)
        y = np.clip((v * tex.shape[0]).astype(int), 0, tex.shape[0] - 1)
        return tex[y, x]

    ground = np.zeros((H, W, 3), np.float32)
    cover = np.zeros((H, W), bool)
    # rasterise every ground triangle, interpolating atlas colour * lightmap
    for tri in idx:
        p = pos[tri]
        c = sample(atlas, uv[tri][:, 0], uv[tri][:, 1]) * sample(lm, uv2[tri][:, 0], uv2[tri][:, 1]) * (col[tri][:, :3] / 255.0)
        xs = p[:, 0] * scale
        zs = p[:, 2] * scale
        x0, x1 = int(np.floor(xs.min())), int(np.ceil(xs.max()))
        z0, z1 = int(np.floor(zs.min())), int(np.ceil(zs.max()))
        x0, x1 = max(x0, 0), min(x1, W - 1)
        z0, z1 = max(z0, 0), min(z1, H - 1)
        if x0 > x1 or z0 > z1:
            continue
        gx, gz = np.meshgrid(np.arange(x0, x1 + 1) + 0.5, np.arange(z0, z1 + 1) + 0.5)
        d = (zs[1] - zs[2]) * (xs[0] - xs[2]) + (xs[2] - xs[1]) * (zs[0] - zs[2])
        if abs(d) < 1e-9:
            continue
        a = ((zs[1] - zs[2]) * (gx - xs[2]) + (xs[2] - xs[1]) * (gz - zs[2])) / d
        b = ((zs[2] - zs[0]) * (gx - xs[2]) + (xs[0] - xs[2]) * (gz - zs[2])) / d
        cw = 1 - a - b
        inside = (a >= -0.02) & (b >= -0.02) & (cw >= -0.02)
        if not inside.any():
            continue
        sub = ground[z0 : z1 + 1, x0 : x1 + 1]
        sub[inside] = (a[inside, None] * c[0] + b[inside, None] * c[1] + cw[inside, None] * c[2])
        cover[z0 : z1 + 1, x0 : x1 + 1][inside] = True

    ppos, pnrm, puv, pcol, pidx, groups = load_props()
    zbuf = np.full((H, W), -1e9, np.float32)
    propmask = np.zeros((H, W), np.float32)
    raster(ppos, pidx, W, H, scale, scale, 0, 0, ppos[:, 1], zbuf, propmask)

    top = ground.copy()
    top[~cover] = (0.06, 0.05, 0.06)
    top[propmask > 0] = (0.95, 0.45, 0.28)
    Image.fromarray((np.clip(top, 0, 1) * 255).astype(np.uint8)).save(ROOT / "out" / "preview_top.png")

    # elevation: slice through the middle, project along +Z onto XY
    HE = 400
    WE = int(meta["width"] * 2 * scale)
    el = np.zeros((HE, WE, 3), np.float32) + np.array([0.05, 0.05, 0.07], np.float32)
    ez = np.full((HE, WE), -1e9, np.float32)
    em = np.zeros((HE, WE), np.float32)
    oy = HE - 60.0
    band = (180.0, 196.0)
    for tri in idx:
        p = pos[tri]
        if p[:, 2].max() < band[0] or p[:, 2].min() > band[1]:
            continue
        for x in range(int(p[:, 0].min() * scale), int(p[:, 0].max() * scale) + 1):
            if 0 <= x < WE:
                y = int(np.clip(oy - p[:, 1].max() * scale, 0, HE - 1))
                el[y:, x] = (0.22, 0.30, 0.18)
    sel = (ppos[pidx][:, :, 2].max(1) >= band[0]) & (ppos[pidx][:, :, 2].min(1) <= band[1])
    raster(ppos, pidx[sel], WE, HE, scale, -scale, 0, oy, -ppos[:, 2], ez, em)
    el[em > 0] = (0.92, 0.52, 0.28)
    Image.fromarray((np.clip(el, 0, 1) * 255).astype(np.uint8)).save(ROOT / "out" / "preview_front.png")

    print("props y", ppos[:, 1].min(), ppos[:, 1].max(), "x", ppos[:, 0].min(), ppos[:, 0].max(), "z", ppos[:, 2].min(), ppos[:, 2].max())
    print("wrote out/preview_top.png out/preview_front.png")


if __name__ == "__main__":
    main()
