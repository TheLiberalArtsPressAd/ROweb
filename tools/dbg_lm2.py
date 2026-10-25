import sys
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro
gnd = ro.parse_gnd(fetch.fetch(r'data\prontera.gnd').read_bytes())
count, pcx, pcy, data = gnd.lightmap
raw = np.frombuffer(data, np.uint8)
for i in (1,):
    b = raw[i * 256 : (i + 1) * 256]
    for y in range(16):
        print(' '.join(f'{v:3d}' for v in b[y * 16 : (y + 1) * 16]))
# interleaved view of block 1 as 8x8 RGBA
b = raw[256:512].reshape(8, 8, 4)
print('R min/max', b[..., 0].min(), b[..., 0].max())
print('G min/max', b[..., 1].min(), b[..., 1].max())
print('B min/max', b[..., 2].min(), b[..., 2].max())
print('A min/max', b[..., 3].min(), b[..., 3].max())
