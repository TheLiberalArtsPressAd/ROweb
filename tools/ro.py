#!/usr/bin/env python3
"""Readers for the Gravity file formats used by Ragnarok Online.

Only the pieces the offline web client needs are implemented: ground (GND),
altitude (GAT), world (RSW), models (RSM v1.x/2.1) and sprites (SPR/ACT).
All coordinates are returned in Ragnarok's 1/5 world units where relevant.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


class Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.o = 0

    def seek(self, n: int):
        self.o = n

    def skip(self, n: int):
        self.o += n

    def u8(self) -> int:
        v = self.d[self.o]
        self.o += 1
        return v

    def i8(self) -> int:
        v = struct.unpack_from("<b", self.d, self.o)[0]
        self.o += 1
        return v

    def u16(self) -> int:
        v = struct.unpack_from("<H", self.d, self.o)[0]
        self.o += 2
        return v

    def i16(self) -> int:
        v = struct.unpack_from("<h", self.d, self.o)[0]
        self.o += 2
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.o)[0]
        self.o += 4
        return v

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.o)[0]
        self.o += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.o)[0]
        self.o += 4
        return v

    def raw(self, n: int) -> bytes:
        v = self.d[self.o : self.o + n]
        self.o += n
        return v

    def string(self, n: int) -> str:
        raw = self.raw(n).split(b"\0")[0]
        try:
            return raw.decode("cp949")
        except UnicodeDecodeError:
            return raw.decode("latin1")


# --------------------------------------------------------------------------- GND


@dataclass
class Tile:
    u: tuple[float, float, float, float]
    v: tuple[float, float, float, float]
    texture: int
    light: int
    color: tuple[int, int, int, int]


@dataclass
class Surface:
    h: tuple[float, float, float, float]
    up: int
    front: int
    right: int


@dataclass
class Gnd:
    version: float
    width: int
    height: int
    zoom: float
    textures: list[str]
    texture_indexes: list[int]
    lightmap: tuple[int, int, int, bytes]
    tiles: list[Tile]
    surfaces: list[Surface]
    water: dict = field(default_factory=dict)


def parse_gnd(data: bytes) -> Gnd:
    r = Reader(data)
    assert r.raw(4) == b"GRGN", "not a GND"
    version = r.u8() + r.u8() / 10
    width, height, zoom = r.u32(), r.u32(), r.f32()

    count, length = r.u32(), r.u32()
    textures: list[str] = []
    indexes: list[int] = []
    for _ in range(count):
        name = r.string(length)
        if name not in textures:
            textures.append(name)
        indexes.append(textures.index(name))

    lm_count, pcx, pcy, cell = r.i32(), r.i32(), r.i32(), r.i32()
    per_cell = pcx * pcy * cell
    lm = r.raw(lm_count * per_cell * 4)

    tile_count = r.u32()
    tiles: list[Tile] = []
    for _ in range(tile_count):
        u = (r.f32(), r.f32(), r.f32(), r.f32())
        v = (r.f32(), r.f32(), r.f32(), r.f32())
        tex, light = r.u16(), r.u16()
        color = (r.u8(), r.u8(), r.u8(), r.u8())  # BGRA
        tiles.append(Tile(u, v, indexes[tex], light, color))

    surfaces: list[Surface] = []
    for _ in range(width * height):
        h = (r.f32() / 5, r.f32() / 5, r.f32() / 5, r.f32() / 5)
        surfaces.append(Surface(h, r.i32(), r.i32(), r.i32()))

    water = {}
    if version >= 1.8:
        water = {
            "level": r.f32() / 5,
            "type": r.i32(),
            "wave_height": r.f32() / 5,
            "wave_speed": r.f32(),
            "wave_pitch": r.f32(),
            "anim_speed": r.i32(),
            "split_width": r.i32(),
            "split_height": r.i32(),
        }
        if version >= 1.9:
            n = water["split_width"] * water["split_height"]
            water["zones"] = [
                {
                    "level": r.f32(),
                    "type": r.i32(),
                    "wave_height": r.f32(),
                    "wave_speed": r.f32(),
                    "wave_pitch": r.f32(),
                    "anim_speed": r.i32(),
                }
                for _ in range(max(0, n))
            ]

    return Gnd(version, width, height, zoom, textures, indexes, (lm_count, pcx, pcy, lm), tiles, surfaces, water)


# --------------------------------------------------------------------------- GAT

GAT_WALKABLE = 1 << 1
GAT_WATER = 1 << 2
GAT_TYPE_TABLE = {
    0: GAT_WALKABLE,
    1: 0,
    2: GAT_WALKABLE,
    3: GAT_WALKABLE | GAT_WATER,
    4: GAT_WALKABLE,
    5: 0,
    6: GAT_WALKABLE,
}
GAT_TYPE_TABLE.update({-1: 0})


@dataclass
class Gat:
    version: float
    width: int
    height: int
    cells: list[tuple[float, float, float, float, int]]  # h1..h4, flags


def parse_gat(data: bytes) -> Gat:
    r = Reader(data)
    assert r.raw(4) == b"GRAT", "not a GAT"
    version = r.u8() + r.u8() / 10
    width, height = r.u32(), r.u32()
    cells = []
    for _ in range(width * height):
        h = (r.f32() * 0.2, r.f32() * 0.2, r.f32() * 0.2, r.f32() * 0.2)
        t = r.u32()
        if t > 0x7FFFFFFF:
            t -= 1 << 32
        cells.append((*h, GAT_TYPE_TABLE.get(t, 0)))
    return Gat(version, width, height, cells)


# --------------------------------------------------------------------------- RSW


@dataclass
class RswObject:
    kind: int
    name: str = ""
    filename: str = ""
    nodename: str = ""
    position: tuple[float, float, float] = (0, 0, 0)
    rotation: tuple[float, float, float] = (0, 0, 0)
    scale: tuple[float, float, float] = (1, 1, 1)
    anim_type: int = 0
    anim_speed: float = 1.0
    block_type: int = 0


def parse_rsw(data: bytes) -> dict:
    r = Reader(data)
    assert r.raw(4) == b"GRSW", "not a RSW"
    version = r.i8() + r.i8() / 10
    build = 0
    if version >= 2.5:
        build = r.i32()
    if version >= 2.2:
        r.u8()

    files = {
        "ini": r.string(40),
        "gnd": r.string(40),
        "gat": r.string(40),
    }
    if version >= 1.4:
        files["src"] = r.string(40)

    water = {}
    if version < 2.6:
        water["level"] = r.f32() / 5 if version >= 1.3 else 0.0
        if version >= 1.8:
            water["type"] = r.i32()
            water["wave_height"] = r.f32() / 5
            water["wave_speed"] = r.f32()
            water["wave_pitch"] = r.f32()
        else:
            water = {"level": 0.0, "type": 0, "wave_height": 1.0, "wave_speed": 2.0, "wave_pitch": 50.0}
        if version >= 1.9:
            water["anim_speed"] = r.i32()

    light = {}
    if version >= 1.5:
        light = {
            "longitude": r.i32(),
            "latitude": r.i32(),
            "diffuse": (r.f32(), r.f32(), r.f32()),
            "ambient": (r.f32(), r.f32(), r.f32()),
        }
        if version >= 1.7:
            light["opacity"] = r.f32()

    ground = {}
    if version >= 1.6:
        ground = {"top": r.i32(), "bottom": r.i32(), "left": r.i32(), "right": r.i32()}

    if version >= 2.7 and build >= 221:
        n = r.i32()
        r.skip(4 * n)

    objects: list[RswObject] = []
    count = r.i32()
    for _ in range(count):
        kind = r.i32()
        if kind == 1:
            name = r.string(40) if version >= 1.3 else ""
            anim_type = r.i32() if version >= 1.3 else 0
            anim_speed = r.f32() if version >= 1.3 else 1.0
            block_type = r.i32() if version >= 1.3 else 0
            if version >= 2.6 and build >= 186:
                r.u8()
            if version >= 2.7:
                r.i32()
            filename = r.string(80)
            nodename = r.string(80)
            pos = (r.f32() / 5, r.f32() / 5, r.f32() / 5)
            rot = (r.f32(), r.f32(), r.f32())
            scale = (r.f32() / 5, r.f32() / 5, r.f32() / 5)
            objects.append(
                RswObject(1, name, filename, nodename, pos, rot, scale, anim_type, anim_speed, block_type)
            )
        elif kind == 2:
            objects.append(RswObject(2, r.string(80)))
            r.skip(12 + 12 + 4)
        elif kind == 3:
            objects.append(RswObject(3, r.string(80)))
            r.skip(80 + 12 + 4 + 4 + 4 + 4 + (4 if version >= 2.0 else 0))
        elif kind == 4:
            objects.append(RswObject(4, r.string(80)))
            r.skip(12 + 4 + 4 + 16)

    return {
        "version": version,
        "build": build,
        "files": files,
        "water": water,
        "light": light,
        "ground": ground,
        "objects": objects,
    }


# --------------------------------------------------------------------------- RSM


@dataclass
class RsmNode:
    name: str
    parent: str
    textures: list[str]
    mat3: list[float]
    offset: tuple[float, float, float]
    pos: tuple[float, float, float]
    rotangle: float
    rotaxis: tuple[float, float, float]
    scale: tuple[float, float, float]
    vertices: list[tuple[float, float, float]]
    tvertices: list[tuple[float, float]]
    faces: list[tuple[tuple[int, int, int], tuple[int, int, int], int, int]]
    only: bool


@dataclass
class Rsm:
    version: float
    anim_len: int
    shade_type: int
    alpha: float
    textures: list[str]
    nodes: list[RsmNode]
    main: str


def parse_rsm(data: bytes) -> Rsm:
    r = Reader(data)
    magic = r.raw(4)
    assert magic in (b"GRSM", b"GRSX"), "not a RSM"
    major, minor = r.u8(), r.u8()
    version = major + minor / 10
    if major == 2 and minor >= 2:
        raise NotImplementedError("RSM2")

    anim_len, shade = r.i32(), r.i32()
    alpha = r.u8() / 255.0 if version >= 1.4 else 1.0
    additional: list[str] = []
    main_name = ""
    global_textures: list[str] = []
    if version >= 2.2:
        r.f32()
        n = r.i32()
        for _ in range(n):
            additional.append(r.string(r.i32()))
        n = r.i32()
        global_textures = [r.string(r.i32()) for _ in range(n)]
    else:
        r.skip(16)
        n = r.i32()
        for _ in range(n):
            additional.append(r.string(40))
        main_name = r.string(40)
        global_textures = additional

    node_count = r.i32()
    nodes: list[RsmNode] = []
    for _ in range(node_count):
        if version >= 2.2:
            name, parent = r.string(r.i32()), r.string(r.i32())
        else:
            name, parent = r.string(40), r.string(40)
        ntex = r.i32()
        node_tex = []
        for _ in range(ntex):
            if version >= 2.3:
                node_tex.append(r.string(r.i32()))
            else:
                idx = r.i32()
                node_tex.append(global_textures[idx] if 0 <= idx < len(global_textures) else "")
        mat3 = [r.f32() for _ in range(9)]
        offset = (r.f32(), r.f32(), r.f32())
        if version >= 2.2:
            pos, rotangle, rotaxis, scale = (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0), (1.0, 1.0, 1.0)
        else:
            pos = (r.f32(), r.f32(), r.f32())
            rotangle = r.f32()
            rotaxis = (r.f32(), r.f32(), r.f32())
            scale = (r.f32(), r.f32(), r.f32())

        vcount = r.i32()
        verts = [(r.f32(), r.f32(), r.f32()) for _ in range(vcount)]
        tvcount = r.i32()
        tverts = []
        for _ in range(tvcount):
            if version >= 1.2:
                r.skip(4)  # vertex color
            tverts.append((r.f32() * 0.98 + 0.01, r.f32() * 0.98 + 0.01))
        fcount = r.i32()
        faces = []
        for _ in range(fcount):
            flen = r.i32() if version >= 2.2 else -1
            vi = (r.u16(), r.u16(), r.u16())
            ti = (r.u16(), r.u16(), r.u16())
            texid, _pad, two_side = r.u16(), r.u16(), r.i32()
            smooth = 0
            if version >= 1.2:
                smooth = r.i32()
                if flen > 24:
                    r.skip(min(flen - 28, 8)) if flen <= 32 else None
                if flen > 32:
                    r.skip(flen - 32)
            faces.append((vi, ti, texid, two_side))
        if version >= 1.6:
            n = r.i32()
            r.skip(n * 20)
        n = r.i32()
        r.skip(n * 20)
        if version >= 2.2:
            n = r.i32()
            r.skip(n * 20)
        if version >= 2.3:
            n = r.i32()
            for _ in range(n):
                r.i32()
                types = r.i32()
                for _ in range(types):
                    r.i32()
                    frames = r.i32()
                    r.skip(frames * 8)
        nodes.append(
            RsmNode(name, parent, node_tex, mat3, offset, pos, rotangle, rotaxis, scale, verts, tverts, faces, node_count == 1)
        )

    if version < 1.6:
        n = r.i32()
        r.skip(n * 20)
    if r.o + 4 <= len(r.d):
        n = r.i32()
        r.skip(n * (40 if version >= 1.3 else 36))

    out = Rsm(version, anim_len, shade, alpha, global_textures, nodes, main_name or (nodes[0].name if nodes else ""))
    out.additional = additional
    return out


# --------------------------------------------------------------------------- SPR


@dataclass
class SprFrame:
    width: int
    height: int
    rgba: bytes  # RGBA, top-down
    rgba_source: bool


@dataclass
class Spr:
    version: float
    frames: list[SprFrame]


def _flip_rgba(buf: bytes, w: int, h: int) -> bytes:
    stride = w * 4
    return b"".join(buf[(h - 1 - y) * stride : (h - y) * stride] for y in range(h))


def parse_spr(data: bytes) -> Spr:
    r = Reader(data)
    assert r.raw(2) == b"SP", "not a SPR"
    version = r.u8() / 10 + r.u8()
    indexed = r.u16()
    rgba_count = r.u16() if version > 1.1 else 0
    indexed_frames: list[tuple[int, int, bytes]] = []

    if version < 2.1:
        for _ in range(indexed):
            w, h = r.u16(), r.u16()
            indexed_frames.append((w, h, r.raw(w * h)))
    else:
        for _ in range(indexed):
            w, h = r.u16(), r.u16()
            size = w * h
            out = bytearray(size)
            i = 0
            end = r.u16() + r.o
            while r.o < end and i < size:
                c = r.u8()
                if i < size:
                    out[i] = c
                i += 1
                if c == 0:
                    count = r.u8()
                    if count == 0:
                        if i < size:
                            out[i] = 0
                        i += 1
                    else:
                        for _ in range(count - 1):
                            if i < size:
                                out[i] = 0
                            i += 1
            indexed_frames.append((w, h, bytes(out)))

    rgba_frames: list[tuple[int, int, bytes]] = []
    for _ in range(rgba_count):
        w, h = r.i16(), r.i16()
        raw = r.raw(w * h * 4)
        # stored as A,B,G,R per pixel
        rgba = bytearray(w * h * 4)
        for i in range(w * h):
            a, b, g, rr = raw[i * 4 : i * 4 + 4]
            rgba[i * 4 : i * 4 + 4] = bytes((rr, g, b, a))
        rgba_frames.append((w, h, _flip_rgba(bytes(rgba), w, h)))

    palette = r.d[-1024:] if version > 1.0 and len(r.d) >= 1024 else None
    frames: list[SprFrame] = []
    for w, h, idx in indexed_frames:
        if palette is None:
            frames.append(SprFrame(w, h, b"\0" * (w * h * 4), False))
            continue
        rgba = bytearray(w * h * 4)
        for i, v in enumerate(idx):
            if v == 0:
                continue
            rr, gg, bb = palette[v * 4], palette[v * 4 + 1], palette[v * 4 + 2]
            if rr == 255 and gg == 0 and bb == 255:
                continue
            rgba[i * 4 : i * 4 + 4] = bytes((rr, gg, bb, 255))
        frames.append(SprFrame(w, h, bytes(rgba), False))
    for w, h, rgba in rgba_frames:
        frames.append(SprFrame(w, h, rgba, True))
    return Spr(version, frames)


# --------------------------------------------------------------------------- ACT


@dataclass
class ActLayer:
    x: int
    y: int
    index: int
    mirror: bool
    color: tuple[int, int, int, int]
    scale_x: float
    scale_y: float
    angle: int
    spr_type: int
    width: int = 0
    height: int = 0


@dataclass
class Act:
    version: float
    actions: list[list[list[ActLayer]]]
    delays: list[float]
    sounds: list[str]


def parse_act(data: bytes) -> Act:
    r = Reader(data)
    assert r.raw(2) == b"AC", "not a ACT"
    version = r.u8() / 10 + r.u8()
    count = r.u16()
    r.skip(10)
    actions = []
    for _ in range(count):
        nframes = r.u32()
        anims = []
        for _ in range(nframes):
            r.skip(32)
            nlayers = r.u32()
            layers = []
            for _ in range(nlayers):
                x, y, index, mirror = r.i32(), r.i32(), r.i32(), r.i32()
                color = (255, 255, 255, 255)
                sx = sy = 1.0
                angle = 0
                spr_type = 0
                width = height = 0
                if version >= 2.0:
                    color = (r.u8(), r.u8(), r.u8(), r.u8())
                    sx = r.f32()
                    sy = sx if version <= 2.3 else r.f32()
                    angle = r.i32()
                    spr_type = r.i32()
                    if version >= 2.5:
                        width, height = r.i32(), r.i32()
                layers.append(ActLayer(x, y, index, bool(mirror), color, sx, sy, angle, spr_type, width, height))
            if version >= 2.0:
                r.i32()  # sound id
            if version >= 2.3:
                n = r.i32()
                r.skip(n * 16)
            anims.append(layers)
        actions.append(anims)

    sounds = []
    delays = []
    if version >= 2.1:
        n = r.i32()
        for _ in range(n):
            sounds.append(r.string(40))
        if version >= 2.2:
            for _ in range(len(actions)):
                delays.append(r.f32() * 25)
    if not delays:
        delays = [150.0] * len(actions)
    return Act(version, actions, delays, sounds)
