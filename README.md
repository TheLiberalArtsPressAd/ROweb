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
| `tools/check_pages.py` | pre-deploy guard: pack/manifest references, build stamp, 1 GiB and 100 MiB limits |
| `tools/retrycheck.mjs` | headless smoke test: break the manifest, confirm the error screen, press `R`, expect recovery |
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

Three independent caps are enforced:

1. **Published site ≤ 1024 MiB** — `tools/build_web.py` sums every file in
   `docs/` and refuses to finish above the budget, and `tools/check_pages.py`
   runs the same check (plus GitHub's 100 MiB per-file cap) in CI before the
   Pages upload. The current site is ~55 MiB.
2. **WASM heap ≤ 1024 MiB** — the Emscripten module is emitted with a 2 GiB
   maximum (32768 pages). The build rewrites the WebAssembly memory section's
   maximum to **16384 pages = 1 GiB**. The LEB128 encoding keeps the same byte
   length, so the patch is in-place and safe.
3. **Asset pack ≈ 17 MiB** — only Prontera, its props, six sprites and one BGM
   track are exported from the 2.17 GB `data.grf`.

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
| `R` | Retry loading after a network/asset error |
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
(`.nojekyll`, `index.html`, `index.wasm`, `index.<hash>.pck`, `assets/`), so both
modes work.

## Notes

### Why the deployed client could go stale (and how that is fixed)

GitHub Pages sends `Cache-Control: max-age=600` for every file, so a fresh
deployment can be mixed with a client the browser cached ten minutes earlier.
`index.html` used to load `index.pck` by its fixed name; a stale pack from
before the gzip fix then started against a fresh asset pack and failed with
**“could not load assets/manifest.json”**.

The build now pins the client pack by content hash:

- `tools/build_web.py` copies `index.pck` to `index.<sha256>.pck`, sets
  `GODOT_CONFIG.mainPack` to that name and keeps the previous four packs in
  `docs/`, so a cached `index.html` still finds the pack it expects while a new
  `index.html` can never start an old client.
- The same build stamps `window.RO_ASSET_BUILD` (hash of `web/assets`) into
  `index.html`. `Fetcher` appends it as `?v=<stamp>` to every asset request, so
  the asset pack is cached per build rather than per URL.
- Every request is retried three times; retries use a unique `&t=<nonce>`, which
  skips a stale or half-written copy. On failure the client prints the HTTP
  status and offers **Retry** (or press `R`) instead of dying on a black screen.

Troubleshooting, in order:

1. If the game reports an error, press `R` (or click **Retry**). Most failures
   are a deployment in progress or a flaky connection, and both recover without
   a reload.
2. Still stuck? Hard refresh (`Ctrl+Shift+R` / `Cmd+Shift+R`); that discards the
   cached `index.html`.
3. Opening `docs/index.html` directly from disk (`file://`) cannot work — use
   the Pages URL or `tools/serve.py`.

Other notes:

- The client disables Godot's own gzip decompression (`HTTPRequest.accept_gzip
  = false`). Browsers already decompress `gzip`/`br` responses for the
  `fetch()` that backs `HTTPRequest` on the web; decompressing twice fails with
  a `StreamPeerGZIP` error, which GitHub Pages' gzipped JSON triggered.
- Ragnarok Online is a trademark of Gravity Co., Ltd. This repository is a
  technical demo built from locally owned game files; do not redistribute the
  original GRF or extracted assets commercially.
- The colour-key pass is marked by `web/assets/.degraded`. Re-running
  `degrade_assets.py` is a no-op unless you pass `--force`.
- CPU spikes during automated testing came from headless Chromium's software
  WebGL (SwiftShader), not from the game. In a normal browser with GPU
  acceleration the client runs at the 60 FPS cap set in `project.godot`.
