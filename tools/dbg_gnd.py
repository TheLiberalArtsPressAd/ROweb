import sys, collections
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro
gnd = ro.parse_gnd(fetch.fetch(r'data\prontera.gnd').read_bytes())
lm_count, pcx, pcy, lm = gnd.lightmap
print('lightmap count', lm_count, 'per cell', pcx, pcy, 'bytes', len(lm))
print('lights used', sorted({t.light for t in gnd.tiles})[:20])
print('tiles', len(gnd.tiles), 'textures', len(gnd.textures))
print('tile color sample', [t.color for t in gnd.tiles[:4]])
print('uv sample', gnd.tiles[0].u, gnd.tiles[0].v)
print('textures', gnd.textures)
print('water', gnd.water)
print('version', gnd.version, 'zoom', gnd.zoom)
# lightmap mean per light
a = np.frombuffer(lm, np.uint8)
print('lm alpha mean', a[:64].mean())
