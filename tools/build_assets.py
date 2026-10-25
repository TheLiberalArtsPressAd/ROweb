#!/usr/bin/env python3
"""Build a degraded, web-friendly asset pack for one Ragnarok map.

Reads GND/GAT/RSW/RSM/SPR/ACT through tools/ro.py, fetches the referenced
GRF files from the local roBrowser remote client and writes:

  web/assets/map/<map>/terrain.bin   terrain quads (RO units, Godot Y-up)
  web/assets/map/<map>/terrain.json  layout + atlas rects + lightmap atlas
  web/assets/map/<map>/atlas.webp    ground texture atlas
  web/assets/map/<map>/lightmap.png  ground lightmap atlas
  web/assets/map/<map>/props.bin     merged, baked static props
  web/assets/map/<map>/props.json    prop material groups
  web/assets/map/<map>/walk.bin      1 byte per GAT cell (1 = walkable)
  web/assets/textures/<name>.webp    prop textures
  web/assets/sprites/<id>.webp|json  pre-composited sprite atlases
  web/assets/audio/<track>.mp3
  web/assets/manifest.json

Ragnarok's world is Y-down (screen space); everything written here is
converted to Y-up (Godot) by negating Y as the final step.

All heavy format work happens here; the Godot client only reads JSON + binary.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
import fetch  # noqa: E402
import ro  # noqa: E402

ROOT = Path(r"D:\ROweb")
OUT = ROOT / "web" / "assets"
MAP = "prontera"
SPRITE_PIXEL = 1.0 / 35.0  # world units per sprite pixel
CENTER_XZ = False  # recentre models on their bounding box (roBrowser does this)

# ------------------------------------------------------------------ helpers


def tex_path(name: str) -> str | None:
    """Resolve a GND/RSM texture name to a GRF path."""
    name = name.strip().replace("/", "\\")
    if not name:
        return None
    if name.lower().startswith("data\\"):
        return name
    return "data\\texture\\" + name


def apply_color_key(im: Image.Image) -> Image.Image:
    """Turn Ragnarok's pure-magenta transparency key into real alpha.

    Most RO BMP/TGA textures are 24-bit with #FF00FF marking transparent areas.
    Without this the magenta shows up all over the props (banners, foliage,
    fountain ornaments).
    """
    if im.mode != "RGBA":
        im = im.convert("RGBA")
    arr = np.array(im)
    alpha = arr[..., 3]
    if alpha.min() < 250:  # a real alpha channel, nothing to key out
        return im
    key = (arr[..., 0] >= 248) & (arr[..., 1] <= 8) & (arr[..., 2] >= 248)
    if not key.any():
        return im
    arr[key] = (0, 0, 0, 0)
    return Image.fromarray(arr, "RGBA")


def load_texture(name: str) -> tuple[Image.Image | None, str | None]:
    path = tex_path(name)
    if not path:
        return None, None
    candidates = [path]
    stem = path.rsplit("\\", 1)[-1]
    if "." in stem:
        base = path.rsplit(".", 1)[0]
        candidates += [base + ext for ext in (".bmp", ".tga", ".png") if not path.lower().endswith(ext)]
    for cand in candidates:
        try:
            p = fetch.fetch(cand)
            return apply_color_key(Image.open(p).convert("RGBA")), cand
        except Exception:  # noqa: BLE001
            continue
    print(f"  ! missing texture {name}")
    return None, path


def resize_max(im: Image.Image, size: int) -> Image.Image:
    if max(im.size) <= size:
        return im
    s = size / max(im.size)
    return im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))), Image.LANCZOS)


def write_webp(im: Image.Image, path: Path, quality: int = 82, lossless: bool = False):
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "WEBP", quality=quality, lossless=lossless, method=4)


def has_alpha(im: Image.Image) -> bool:
    if im.mode != "RGBA":
        return False
    return im.getchannel("A").getextrema()[0] < 250


# ------------------------------------------------------------------ transforms


def rot_axis(axis, angle) -> np.ndarray:
    x, y, z = axis
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-9:
        return np.eye(4)
    x, y, z = x / n, y / n, z / n
    c, s = math.cos(angle), math.sin(angle)
    C = 1 - c
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s, 0],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s, 0],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C, 0],
            [0, 0, 0, 1],
        ],
        dtype=np.float64,
    )


def T(v) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = v
    return m


def S(v) -> np.ndarray:
    m = np.eye(4)
    m[0, 0], m[1, 1], m[2, 2] = v
    return m


def Rz(deg) -> np.ndarray:
    a = math.radians(deg)
    m = np.eye(4)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
    return m


def Rx(deg) -> np.ndarray:
    a = math.radians(deg)
    m = np.eye(4)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = math.cos(a), -math.sin(a), math.sin(a), math.cos(a)
    return m


def Ry(deg) -> np.ndarray:
    a = math.radians(deg)
    m = np.eye(4)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = math.cos(a), math.sin(a), -math.sin(a), math.cos(a)
    return m


def mat3_to_mat4(flat) -> np.ndarray:
    """glMatrix mat3 arrays are column-major."""
    m = np.eye(4)
    m[0, 0], m[0, 1], m[0, 2] = flat[0], flat[3], flat[6]
    m[1, 0], m[1, 1], m[1, 2] = flat[1], flat[4], flat[7]
    m[2, 0], m[2, 1], m[2, 2] = flat[2], flat[5], flat[8]
    return m


def light_terms(rsw: dict):
    """Reproduce roBrowser's RSW light: direction, diffuse, ambient, env."""
    light = rsw.get("light") or {}
    lon = math.radians(light.get("longitude", 45))
    lat = math.radians(light.get("latitude", 45))
    m = Ry(math.degrees(lon)) @ Rx(math.degrees(lat))
    direction = -m[:3, :3] @ np.array([0.0, 1.0, 0.0])
    diffuse = np.array(light.get("diffuse", (1.0, 1.0, 1.0)), np.float64)
    ambient = np.array(light.get("ambient", (0.3, 0.3, 0.3)), np.float64)
    env = 1.0 - (1.0 - diffuse) * (1.0 - ambient)
    return direction, diffuse, ambient, env


def shade(normals: np.ndarray, light) -> np.ndarray:
    """(w * diffuse + ambient) * env, clamped, as 0-255 RGB."""
    direction, diffuse, ambient, env = light
    w = np.clip(normals @ direction, 0.0, None)
    col = np.clip(w[:, None] * diffuse[None, :] + ambient[None, :], 0.0, 1.0)
    col = np.clip(col * env[None, :], 0.0, 1.0)
    return (col * 255.0).astype(np.uint8)


# ------------------------------------------------------------------ map


def build_lightmaps(gnd: ro.Gnd, out_path: Path) -> dict:
    """Ground lightmaps.

    Each entry is 8x8 pixels stored as four 64-byte planes; this client's data
    only populates the first plane (a shadow/brightness value, 255 = lit), so it
    is written out as a greyscale atlas.
    """
    count, pcx, pcy, data = gnd.lightmap
    size_cell = 8  # RO lightmaps are always 8x8 pixels
    cw = ch = size_cell
    cols = int(math.ceil(math.sqrt(count)))
    rows = int(math.ceil(count / cols))
    atlas = Image.new("RGB", (cols * cw, rows * ch), (255, 255, 255))
    px = atlas.load()
    raw = np.frombuffer(data, np.uint8)
    per = cw * ch
    for i in range(count):
        block = raw[i * 4 * per : (i + 1) * 4 * per]
        gray = block[:per].reshape(per)
        ox, oy = (i % cols) * cw, (i // cols) * ch
        for y in range(ch):
            for x in range(cw):
                v = int(gray[y * cw + x])
                px[ox + x, oy + y] = (v, v, v)
    atlas.save(out_path)
    return {"count": count, "cols": cols, "rows": rows, "cell": size_cell, "size": [atlas.width, atlas.height]}


def build_map(gnd: ro.Gnd, gat: ro.Gat, map_dir: Path, light) -> dict:
    # --- ground texture atlas
    textures: list[Image.Image] = []
    for name in gnd.textures:
        im, _p = load_texture(name)
        if im is None:
            im = Image.new("RGBA", (256, 256), (90, 90, 90, 255))
        textures.append(resize_max(im, 256))

    cell, pad = 260, 2
    cols = 4
    rows = math.ceil(len(textures) / cols)
    atlas = Image.new("RGBA", (cols * cell, rows * cell), (0, 0, 0, 255))
    rects = []
    for i, im in enumerate(textures):
        x, y = (i % cols) * cell + pad, (i // cols) * cell + pad
        atlas.alpha_composite(im, (x, y))
        rects.append((x, y, im.width, im.height))
    write_webp(atlas, map_dir / "atlas.webp", quality=88)
    aw, ah = atlas.size

    lm = build_lightmaps(gnd, map_dir / "lightmap.png")

    # --- terrain quads
    pos: list[float] = []
    uv: list[float] = []
    uv2: list[float] = []
    col: list[int] = []
    idx: list[int] = []
    cells = 0
    for gy in range(gnd.height):
        for gx in range(gnd.width):
            s = gnd.surfaces[gx + gy * gnd.width]
            if s.up < 0:
                continue
            t = gnd.tiles[s.up]
            ti = t.texture % len(rects)
            aox, aoy, tw, th = rects[ti]
            h = s.h
            b = t.color  # stored BGRA
            r, g, bb = b[2], b[1], b[0]
            lx = t.light % lm["count"]
            lcx, lcy = lx % lm["cols"], lx // lm["cols"]
            u1, u2 = (lcx * 8 + 1) / lm["size"][0], (lcx * 8 + 7) / lm["size"][0]
            v1, v2 = (lcy * 8 + 1) / lm["size"][1], (lcy * 8 + 7) / lm["size"][1]
            corners = [
                (gx * 2.0, h[0], gy * 2.0, t.u[0], t.v[0], u1, v1),
                ((gx + 1) * 2.0, h[1], gy * 2.0, t.u[1], t.v[1], u2, v1),
                (gx * 2.0, h[2], (gy + 1) * 2.0, t.u[2], t.v[2], u1, v2),
                ((gx + 1) * 2.0, h[3], (gy + 1) * 2.0, t.u[3], t.v[3], u2, v2),
            ]
            ax, ay, az = corners[1][0] - corners[0][0], corners[1][1] - corners[0][1], corners[1][2] - corners[0][2]
            bx, by, bz = corners[2][0] - corners[0][0], corners[2][1] - corners[0][1], corners[2][2] - corners[0][2]
            nrm = np.array([ay * bz - az * by, az * bx - ax * bz, ax * by - ay * bx])
            ln = np.linalg.norm(nrm)
            nrm /= ln if ln > 1e-9 else 1.0
            sc = shade(nrm[None, :], light)[0]
            base = len(pos) // 3
            for cx, cy, cz, tu, tv, lu, lv in corners:
                pos += [cx, -cy, cz]  # Y-down -> Y-up
                uv += [(aox + tu * tw) / aw, (aoy + tv * th) / ah]
                uv2 += [lu, lv]
                col += [int(sc[0]) * r // 255, int(sc[1]) * g // 255, int(sc[2]) * bb // 255, 255]
            idx += [base, base + 1, base + 2, base + 1, base + 3, base + 2]
            cells += 1

    verts = len(pos) // 3
    with (map_dir / "terrain.bin").open("wb") as f:
        f.write(b"ROM2")
        f.write(np.uint32(verts).tobytes())
        f.write(np.uint32(len(idx)).tobytes())
        f.write(np.array(pos, np.float32).tobytes())
        f.write(np.array(uv, np.float32).tobytes())
        f.write(np.array(uv2, np.float32).tobytes())
        f.write(np.array(col, np.uint8).tobytes())
        f.write(np.array(idx, np.uint32).tobytes())

    walk = bytearray(gat.width * gat.height)
    for i, cellv in enumerate(gat.cells):
        if cellv[4] & ro.GAT_WALKABLE:
            walk[i] = 1
    (map_dir / "walk.bin").write_bytes(bytes(walk))

    terrain = {
        "map": MAP,
        "version": gnd.version,
        "width": gnd.width,
        "height": gnd.height,
        "cell": 2.0,
        "spawn": spawn_point(gnd, gat),
        "walk": {"width": gat.width, "height": gat.height, "cell": 1.0},
        "textures": [n.replace("\\", "/") for n in gnd.textures],
        "atlas": {"file": "atlas.webp", "size": [aw, ah], "slots": rects},
        "lightmap": dict(lm, file="lightmap.png"),
        "heights": heightmap(gnd),
    }
    (map_dir / "terrain.json").write_text(json.dumps(terrain, ensure_ascii=False), encoding="utf8")
    print(f"  map: {cells} ground cells, {verts} verts, atlas {aw}x{ah}, lightmap {lm['size']}")
    return terrain


def heightmap(gnd: ro.Gnd) -> dict:
    """Max/min surface height per GND cell, useful for placing entities."""
    hs = np.full((gnd.height, gnd.width), np.nan, np.float32)
    for y in range(gnd.height):
        for x in range(gnd.width):
            s = gnd.surfaces[x + y * gnd.width]
            if s.up >= 0:
                hs[y, x] = sum(s.h) / 4.0
    hs = np.nan_to_num(hs, nan=0.0)
    return {"scale": 0.1, "data": [int(round(v * 10)) for v in hs.ravel()]}


def spawn_point(gnd: ro.Gnd, gat: ro.Gat):
    cx, cy = gat.width // 2, gat.height // 2
    for radius in range(0, 220):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                if max(abs(dx), abs(dy)) != radius:
                    continue
                x, y = cx + dx, cy + dy
                if not (0 <= x < gat.width and 0 <= y < gat.height):
                    continue
                flags = gat.cells[x + y * gat.width][4]
                gx, gy = x // 2, y // 2
                if flags & ro.GAT_WALKABLE and gnd.surfaces[gx + gy * gnd.width].up >= 0:
                    return [x + 0.5, y + 0.5]
    return [cx + 0.5, cy + 0.5]


# ------------------------------------------------------------------ props


def model_geometry(rsm: ro.Rsm):
    """Bake an RSM into model space (RO coords, base at y=0), following roBrowser.

    Node chain: parent * T(pos) * R(axis, angle) * S(scale); then, unless the
    model is a single node, * T(offset) * mat3.  The whole model is then shifted
    so its lowest point sits at y=0 (the RSW placement point).
    """
    nodes = rsm.nodes
    by_name = {n.name: n for n in nodes}
    chain: dict[str, np.ndarray] = {}

    def walk(n, parent):
        m = parent @ T(n.pos) @ rot_axis(n.rotaxis, n.rotangle) @ S(n.scale)
        chain[n.name] = m
        for child in nodes:
            if child is not n and child.parent == n.name and child.name != n.name:
                walk(child, m)

    for n in nodes:
        if not n.parent or n.parent not in by_name or n.parent == n.name:
            walk(n, np.eye(4))

    # per-node world matrix incl. offset/mat3
    node_mats = {}
    for n in nodes:
        m = chain.get(n.name, np.eye(4))
        if not n.only:
            m = m @ T(n.offset) @ mat3_to_mat4(n.mat3)
        node_mats[n.name] = m

    allpts = []
    for n in nodes:
        if n.vertices:
            v = np.c_[np.array(n.vertices), np.ones(len(n.vertices))]
            allpts.append((v @ node_mats[n.name].T)[:, :3])
    if not allpts:
        return None
    pts = np.vstack(allpts)
    # Anchor the lowest point of the model on the placement point. roBrowser
    # also recentres X/Z on the bounding box; RO models are authored around
    # their origin, so keeping the origin avoids shifting asymmetrical props.
    sx = -(pts[:, 0].min() + pts[:, 0].max()) * 0.5 if CENTER_XZ else 0.0
    sz = -(pts[:, 2].min() + pts[:, 2].max()) * 0.5 if CENTER_XZ else 0.0
    return node_mats, T((sx, -pts[:, 1].max(), sz))


def bake_model(rsm: ro.Rsm):
    """Return (verts Nx3 RO space, normals Nx3, uvs Nx2, texnames list, two_side list)."""
    geom = model_geometry(rsm)
    if geom is None:
        return None
    node_mats, shift = geom
    verts, normals, uvs, texs, twos = [], [], [], [], []
    for n in rsm.nodes:
        if not n.faces:
            continue
        m = shift @ node_mats[n.name]
        world = (np.c_[np.array(n.vertices), np.ones(len(n.vertices))] @ m.T)[:, :3]
        nmat = m[:3, :3]
        for vi, ti, tid, two in n.faces:
            tname = n.textures[tid] if 0 <= tid < len(n.textures) else ""
            if not tname and n.textures:
                tname = n.textures[0]
            if not tname:
                continue
            p0, p1, p2 = world[vi[0]], world[vi[1]], world[vi[2]]
            nrm = np.cross(p1 - p0, p2 - p0)
            ln = np.linalg.norm(nrm)
            nrm = nrm / ln if ln > 1e-9 else np.array([0.0, 1.0, 0.0])
            for k, c in enumerate(vi):
                verts.append(world[c])
                normals.append(nrm)
                tvidx = ti[k]
                uvs.append(n.tvertices[tvidx] if tvidx < len(n.tvertices) else (0.0, 0.0))
                texs.append(tname)
                twos.append(bool(two))
    if not verts:
        return None
    return np.array(verts, np.float64), np.array(normals, np.float64), np.array(uvs, np.float64), texs, twos


def build_props(rsw: dict, gnd: ro.Gnd, map_dir: Path, light, max_texture: int = 256):
    models = [o for o in rsw["objects"] if o.kind == 1 and o.filename]
    uniq = sorted({o.filename for o in models})
    print(f"  props: {len(models)} placements, {len(uniq)} unique models")

    cache = {}
    skipped = 0
    for i, name in enumerate(uniq):
        path = "data\\model\\" + name.replace("/", "\\")
        try:
            rsm = ro.parse_rsm(fetch.fetch(path).read_bytes())
            baked = bake_model(rsm)
            if baked is not None:
                cache[name] = baked
        except Exception:  # noqa: BLE001
            skipped += 1
        if (i + 1) % 100 == 0:
            print(f"    models {i + 1}/{len(uniq)}")
    print(f"    baked {len(cache)} models, skipped {skipped}")

    # texture -> webp
    tex_dir = OUT / "textures"
    tex_info: dict[str, dict] = {}
    tex_imgs: dict[str, Image.Image] = {}

    def texture(tname: str) -> dict:
        if tname in tex_info:
            return tex_info[tname]
        im, p = load_texture(tname)
        if im is None:
            im = Image.new("RGBA", (64, 64), (120, 100, 90, 255))
        im = resize_max(im, max_texture)
        key = f"prop_{len(tex_info):03d}"
        alpha = has_alpha(im)
        write_webp(im, tex_dir / f"{key}.webp", quality=80)
        tex_imgs[tname] = im
        tex_info[tname] = {
            "texture": f"textures/{key}.webp",
            "w": im.width,
            "h": im.height,
            "alpha": bool(alpha),
            "source": p.replace("\\", "/") if p else "",
        }
        return tex_info[tname]

    groups_v: dict[str, list[np.ndarray]] = defaultdict(list)
    groups_uv: dict[str, list[np.ndarray]] = defaultdict(list)
    groups_n: dict[str, list[np.ndarray]] = defaultdict(list)
    groups_c: dict[str, list[np.ndarray]] = defaultdict(list)
    used = 0
    for o in models:
        baked = cache.get(o.filename)
        if baked is None:
            continue
        v, nrm, uv, tex, twos = baked
        inst = (
            T((o.position[0] + gnd.width, o.position[1], o.position[2] + gnd.height))
            @ Rz(o.rotation[2])
            @ Rx(o.rotation[0])
            @ Ry(o.rotation[1])
            @ S(o.scale)
        )
        wv = (np.c_[v, np.ones(len(v))] @ inst.T)[:, :3]
        wn = (np.c_[nrm, np.zeros(len(nrm))] @ np.linalg.inv(inst).T)[:, :3]
        ln = np.linalg.norm(wn, axis=1)
        ln[ln < 1e-9] = 1.0
        wn = wn / ln[:, None]
        lit = shade(wn, light)
        by_v: dict[str, list[np.ndarray]] = defaultdict(list)
        by_uv: dict[str, list[np.ndarray]] = defaultdict(list)
        by_n: dict[str, list[np.ndarray]] = defaultdict(list)
        by_c: dict[str, list[np.ndarray]] = defaultdict(list)
        for i, t in enumerate(tex):
            by_v[t].append(wv[i])
            by_uv[t].append(uv[i])
            by_n[t].append(wn[i])
            by_c[t].append(lit[i])
        for t in by_v:
            groups_v[t].append(np.array(by_v[t]))
            groups_uv[t].append(np.array(by_uv[t]))
            groups_n[t].append(np.array(by_n[t]))
            groups_c[t].append(np.array(by_c[t]))
        used += 1

    groups = []
    v_chunks, uv_chunks, n_chunks, c_chunks, i_chunks = [], [], [], [], []
    v_off = 0
    i_off = 0
    for tname in sorted(groups_v):
        info = texture(tname)
        v = np.vstack(groups_v[tname])
        uv = np.vstack(groups_uv[tname])
        n = np.vstack(groups_n[tname])
        c = np.vstack(groups_c[tname]).astype(np.uint8)
        if c.shape[1] == 3:
            c = np.hstack([c, np.full((len(c), 1), 255, np.uint8)])
        # Y-down -> Y-up
        v = v * np.array([1.0, -1.0, 1.0])
        n = n * np.array([1.0, -1.0, 1.0])
        idx = np.arange(len(v), dtype=np.uint32)
        groups.append(
            {
                "texture": info["texture"],
                "alpha": info["alpha"],
                "vstart": int(v_off),
                "vcount": int(len(v)),
                "istart": int(i_off),
                "icount": int(len(idx)),
            }
        )
        v_chunks.append(v)
        uv_chunks.append(uv)
        n_chunks.append(n)
        c_chunks.append(c)
        i_chunks.append(idx + v_off)
        v_off += len(v)
        i_off += len(idx)

    if not v_chunks:
        print("  no props baked")
        return None
    pos = np.vstack(v_chunks).astype(np.float32)
    uvv = np.vstack(uv_chunks).astype(np.float32)
    nrm = np.vstack(n_chunks).astype(np.float32)
    col = np.vstack(c_chunks).astype(np.uint8)
    idx = np.concatenate(i_chunks).astype(np.uint32)
    with (map_dir / "props.bin").open("wb") as f:
        f.write(b"ROPR")
        f.write(np.uint32(len(groups)).tobytes())
        f.write(np.uint32(len(pos)).tobytes())
        f.write(np.uint32(len(idx)).tobytes())
        f.write(pos.tobytes())
        f.write(nrm.tobytes())
        f.write(uvv.tobytes())
        f.write(col.tobytes())
        f.write(idx.tobytes())
    (map_dir / "props.json").write_text(json.dumps({"groups": groups}, ensure_ascii=False), encoding="utf8")
    print(f"    props: {used} instances, {len(groups)} materials, {len(pos)} verts, {len(idx) // 3} tris")
    return groups


# ------------------------------------------------------------------ sprites


def compose_frame(parts, action: int, frame: int, canvas=(160, 160), ground=140):
    W, H = canvas
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for spr, act, yref in parts:
        idx = action if action < len(act.actions) else 0
        frames = act.actions[idx]
        if not frames:
            continue
        f = frames[min(frame, len(frames) - 1)]
        for layer in f:
            if layer.index < 0 or layer.index >= len(spr.frames):
                continue
            fr = spr.frames[layer.index]
            if fr.width <= 0 or fr.height <= 0:
                continue
            im = Image.frombytes("RGBA", (fr.width, fr.height), fr.rgba)
            sx = layer.scale_x if abs(layer.scale_x) > 1e-6 else 1.0
            sy = layer.scale_y if abs(layer.scale_y) > 1e-6 else 1.0
            if abs(sx - 1) > 1e-3 or abs(sy - 1) > 1e-3:
                im = im.resize((max(1, int(fr.width * sx)), max(1, int(fr.height * sy))), Image.LANCZOS)
            if layer.mirror:
                im = im.transpose(Image.FLIP_LEFT_RIGHT)
            if layer.color != (255, 255, 255, 255):
                r, g, b, a = layer.color
                px = im.load()
                for yy in range(im.height):
                    for xx in range(im.width):
                        pr, pg, pb, pa = px[xx, yy]
                        px[xx, yy] = (pr * r // 255, pg * g // 255, pb * b // 255, pa * a // 255)
            x = W // 2 + layer.x - im.width // 2
            y = ground + (layer.y - yref) - im.height
            out.alpha_composite(im, (x, y))
    return out


def build_sprite(entity_id: str, parts, actions, act, canvas=(160, 160), ground=140):
    imgs = []
    meta_actions = []
    for action in actions:
        nframes = min((len(a.actions[action]) if action < len(a.actions) else 0) for _s, a, _y in parts)
        nframes = max(nframes, 1)
        frames = []
        for fi in range(nframes):
            im = compose_frame(parts, action, fi, canvas, ground)
            imgs.append(im)
            frames.append(im)
        delay = act.delays[action] if action < len(act.delays) else 120
        meta_actions.append({"frames": len(frames), "delay": delay or 120})
    maxw = 1024
    pad = 2
    x = y = 0
    row_h = 0
    rects = []
    for im in imgs:
        w, h = im.size
        if x + w + pad > maxw:
            x = 0
            y += row_h + pad
            row_h = 0
        rects.append([x, y, w, h])
        x += w + pad
        row_h = max(row_h, h)
    atlas = Image.new("RGBA", (maxw, max(1, y + row_h + pad)), (0, 0, 0, 0))
    for im, (rx, ry, _w, _h) in zip(imgs, rects):
        atlas.paste(im, (rx, ry))
    spr_dir = OUT / "sprites"
    spr_dir.mkdir(parents=True, exist_ok=True)
    write_webp(atlas, spr_dir / f"{entity_id}.webp", lossless=True)

    ai = 0
    meta_actions_out = []
    for meta in meta_actions:
        frames = []
        for _ in range(meta["frames"]):
            frames.append(rects[ai])
            ai += 1
        meta_actions_out.append({"frames": frames, "delay": meta["delay"]})
    meta = {
        "id": entity_id,
        "canvas": list(canvas),
        "pivot": [canvas[0] / 2, ground],
        "pixel": SPRITE_PIXEL,
        "actions": meta_actions_out,
        "action_ids": actions,
    }
    (spr_dir / f"{entity_id}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf8")
    print(f"  sprite {entity_id}: {len(imgs)} frames, atlas {atlas.width}x{atlas.height}")
    return meta


def load_spr_pair(path: str):
    spr = ro.parse_spr(fetch.fetch(path + ".spr").read_bytes())
    act = ro.parse_act(fetch.fetch(path + ".act").read_bytes())
    return spr, act


# ------------------------------------------------------------------ audio


def build_audio(track: str, target: str):
    candidates = [Path(r"D:\RagnarokOnline\BGM") / track, ROOT / "downloads" / track]
    for src in candidates:
        if src.exists():
            out = OUT / "audio" / target
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(src.read_bytes())
            print(f"  audio {target}: {out.stat().st_size / 1e6:.1f} MB")
            return
    print(f"  ! bgm not found: {track}")


# ------------------------------------------------------------------ main


def main() -> int:
    global MAP
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="prontera")
    ap.add_argument("--budget-mb", type=int, default=1024)
    ap.add_argument("--skip-props", action="store_true")
    ap.add_argument("--skip-sprites", action="store_true")
    args = ap.parse_args()
    MAP = args.map

    OUT.mkdir(parents=True, exist_ok=True)
    map_dir = OUT / "map" / MAP
    map_dir.mkdir(parents=True, exist_ok=True)

    gnd = ro.parse_gnd(fetch.fetch(f"data\\{MAP}.gnd").read_bytes())
    gat = ro.parse_gat(fetch.fetch(f"data\\{MAP}.gat").read_bytes())
    rsw = ro.parse_rsw(fetch.fetch(f"data\\{MAP}.rsw").read_bytes())
    print(f"{MAP}: GND {gnd.width}x{gnd.height} v{gnd.version}, GAT {gat.width}x{gat.height}, RSW {rsw['version']}")
    light = light_terms(rsw)

    terrain = build_map(gnd, gat, map_dir, light)
    props = None if args.skip_props else build_props(rsw, gnd, map_dir, light)

    sprite_index = []
    if not args.skip_sprites:
        body = load_spr_pair("data\\sprite\\인간족\\몸통\\남\\초보자_남")
        head = load_spr_pair("data\\sprite\\인간족\\머리통\\남\\1_남")
        yref = body[1].actions[0][0][0].y
        meta = build_sprite("novice_m", [(body[0], body[1], yref), (head[0], head[1], yref)], list(range(16)), body[1])
        sprite_index.append(
            {
                "id": "novice_m",
                "file": "sprites/novice_m",
                "action_names": ["idle_%d" % i for i in range(8)] + ["walk_%d" % i for i in range(8)],
                **{k: meta[k] for k in ("actions", "action_ids", "pivot", "pixel")},
            }
        )
        for eid, path in [
            ("poring", "data\\sprite\\몬스터\\poring"),
            ("poporing", "data\\sprite\\몬스터\\poporing"),
            ("lunatic", "data\\sprite\\몬스터\\lunatic"),
            ("fabre", "data\\sprite\\몬스터\\fabre"),
        ]:
            try:
                spr, act = load_spr_pair(path)
                yref = act.actions[0][0][0].y if act.actions and act.actions[0] and act.actions[0][0] else 0
                actions = [a for a in range(16) if a < len(act.actions)]
                meta = build_sprite(eid, [(spr, act, yref)], actions, act, canvas=(128, 128), ground=110)
                names = []
                for a in actions:
                    names.append(("idle_%d" % a) if a < 8 else ("walk_%d" % (a - 8)))
                sprite_index.append(
                    {
                        "id": eid,
                        "file": f"sprites/{eid}",
                        "action_names": names,
                        **{k: meta[k] for k in ("actions", "action_ids", "pivot", "pixel")},
                    }
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  ! sprite {eid}: {exc}")

    build_audio("08.mp3", "prontera.mp3")

    files = []
    total = 0
    for p in sorted(OUT.rglob("*")):
        if p.is_file() and p.name != "manifest.json":
            s = p.stat().st_size
            total += s
            files.append({"path": str(p.relative_to(OUT)).replace("\\", "/"), "size": s})

    manifest = {
        "version": 1,
        "map": MAP,
        "terrain": f"map/{MAP}/terrain.json",
        "props": None if props is None else f"map/{MAP}/props.json",
        "walk": f"map/{MAP}/walk.bin",
        "light": rsw.get("light", {}),
        "ground": rsw.get("ground", {}),
        "spawn": terrain["spawn"],
        "map_size": [terrain["width"], terrain["height"]],
        "sprites": sprite_index,
        "audio": {"bgm": "audio/prontera.mp3", "file": "audio/prontera.mp3"},
        "files": files,
        "total": total,
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf8")
    print(f"total assets: {total / 1e6:.2f} MB (budget {args.budget_mb} MB)")
    if total > args.budget_mb * 1024 * 1024:
        print("! over budget")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
