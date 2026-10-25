# ROweb — Ragnarok Online, degraded for the browser

A small, playable **Godot 4.7.2 Web** client of Ragnarok Online's Prontera map,
built from the assets in `D:\RagnarokOffline` and capped at **1 GiB**.

- Play: **https://theliberalartspressad.github.io/ROweb/** (after Pages is enabled)
- Engine: Godot 4.7.2, GL Compatibility renderer, **single-threaded Web export**
- Published site: ~55 MiB (238 files), well under GitHub Pages' 1 GiB limit
- WebAssembly heap: hard-capped at **1024 MiB** (patched `memory.max`)

## What is in this repository

| Path | Purpose |
| --- | --- |
| `game/` | Godot project (terrain, props, billboard sprites, click-to-move, orbit camera, BGM) |
| `tools/build_assets.py` | GRF → web asset pack pipeline (GND/GAT/RSM/BMP/SPR → JSON + WebP + PNG) |
| `tools/degrade_assets.py` | colour-key pass: Ragnarok's `255,0,255` magenta → alpha, with edge matte |
| `tools/build_web.py` | one-shot build: import → export → copy assets → patch wasm → size check |
| `web/assets/` | pre-baked asset pack (manifest, map, props, textures, sprites, audio) |
| `docs/` | exported playable site, committed so GitHub Pages can serve it directly |
| `.github/workflows/pages.yml` | deploys `docs/` to GitHub Pages on every push to `main` |

## Analysis: `D:\RagnarokOffline` vs `D:\ROweb`

`D:\RagnarokOffline` is an **Electron** wrapper around **roBrowserLegacy** plus a
local rAthena stack. The renderer is JavaScript/WebGL, the game data is the full
`data.grf` (**2.17 GB**), and the client expects a local HTTP/WebSocket server.
That is a desktop-sized payload: far over GitHub Pages' 1 GiB site limit and too
heavy for a quick browser load.

`D:\ROweb` takes a different route: a **native Godot** client that consumes a
small, pre-baked vertical slice. Instead of shipping the GRF, the Python
pipeline extracts only Prontera's terrain, walkability, prop meshes, textures,
sprites and BGM, converts them to web-friendly formats, and writes a
`manifest.json` that the Godot client fetches at runtime. The result is ~17 MiB
of assets instead of ~2.2 GB.

### The 1 GiB budget

Two independent caps are enforced:

1. **Published site ≤ 1024 MiB** — `tools/build_web.py` sums every file in
   `docs/` and refuses to finish above the budget. The current site is ~55 MiB.
2. **WASM heap ≤ 1024 MiB** — the Emscripten module is emitted with a 2 GiB
   maximum (32768 pages). The build rewrites the WebAssembly memory section's
   maximum to **16384 pages = 1 GiB**. The LEB128 encoding keeps the same byte
   length, so the patch is in-place and safe.

The export uses `variant/thread_support=false`. GitHub Pages cannot send the
`Cross-Origin-Opener-Policy` / `Cross-Origin-Embedder-Policy` headers that
threaded Godot builds require, so the single-threaded variant is the only one
that runs there without a custom server.

## Play

Open the Pages URL. Controls:

| Input | Action |
| --- | --- |
| Left click / tap | Move to that point |
| Right-drag / middle-drag | Orbit the camera |
| Mouse wheel | Zoom |
| `H` | Toggle the help overlay |
| `Esc` | Quit (desktop builds) |

The first click also starts the town BGM (browsers block autoplay until a user
gesture).

## Build locally

Requirements: Godot **4.7.2** with the `web_nothreads_release` export template,
Python 3.10+ with `Pillow` and `numpy`.

```bat
python tools\build_web.py
```

The script writes the complete site to `docs/`. Preview it with:

```bat
python tools\serve.py 8080 docs
```

Then open <http://127.0.0.1:8080/>.

`tools/build_web.py` also accepts `--godot <path>`, `--out <dir>`,
`--limit-mib <n>` and `--skip-degrade`.

## Regenerate the asset pack (optional)

The pack in `web/assets/` is already baked. To rebuild it from the GRF:

```bat
python tools\build_assets.py --help
```

The pipeline expects the extracted client tree under `clientroot/` (or the
paths configured in `tools/ro.py`). It is intentionally a *slice*: only the
Prontera map, the props placed on it, the sprites used by the demo entities and
one BGM track are exported.

## Deploy to GitHub Pages

The repository is set up for **GitHub Actions** deployment:

1. Push `main` to `https://github.com/TheLiberalArtsPressAd/ROweb`.
2. In **Settings → Pages**, set **Source** to **GitHub Actions**.
3. The `Deploy GitHub Pages` workflow uploads `docs/` and publishes it.
4. The site appears at `https://theliberalartspressad.github.io/ROweb/`.

If you prefer branch deployment, set **Source** to **Deploy from a branch**,
branch `main`, folder `/docs`. The `docs/` directory is self-contained
(`.nojekyll`, `index.html`, `index.wasm`, `index.pck`, `assets/`), so both modes
work.

## Notes

- Ragnarok Online is a trademark of Gravity Co., Ltd. This repository is a
  technical demo built from locally owned game files; do not redistribute the
  original GRF or extracted assets commercially.
- The colour-key pass is marked by `web/assets/.degraded`. Re-running
  `degrade_assets.py` is a no-op unless you pass `--force`.
- CPU spikes during automated testing came from headless Chromium's software
  WebGL (SwiftShader), not from the game. In a normal browser with GPU
  acceleration the client runs at the 60 FPS cap set in `project.godot`.
