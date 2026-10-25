import sys
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro
gnd = ro.parse_gnd(fetch.fetch(r'data\prontera.gnd').read_bytes())
count, pcx, pcy, data = gnd.lightmap
raw = np.frombuffer(data, np.uint8)
print('count', count, 'pcx', pcx, 'pcy', pcy, 'len', len(raw), 'per', len(raw) // count)
for i in (0, 1, 2, 100):
    b = raw[i * 256 : (i + 1) * 256]
    print('block', i, 'first16', b[:16].tolist())
    print('   alpha plane mean', b[:64].mean(), 'rgb plane mean', b[64:].mean())
    print('   interleaved mean rgb', b.reshape(-1, 4)[:, :3].mean(), 'alpha', b.reshape(-1, 4)[:, 3].mean())
print('overall mean', raw.mean())
