import sys
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro

gnd = ro.parse_gnd(fetch.fetch(r'data\prontera.gnd').read_bytes())
hs = np.array([s.h for s in gnd.surfaces])
print('GND h min/max', hs.min(), hs.max())
gat = ro.parse_gat(fetch.fetch(r'data\prontera.gat').read_bytes())
gs = np.array([c[:4] for c in gat.cells])
print('GAT h min/max', gs.min(), gs.max())

import collections
rsw = ro.parse_rsw(fetch.fetch(r'data\prontera.rsw').read_bytes())
c = collections.Counter(o.filename for o in rsw['objects'] if o.kind == 1)
for k in list(c)[:4]:
    m = ro.parse_rsm(fetch.fetch(r'data\model\\' + k).read_bytes())
    pts = []
    for n in m.nodes:
        pts.append(np.array(n.vertices))
    a = np.vstack(pts)
    print('---', len(m.nodes), 'nodes', 'raw y', round(a[:, 1].min(), 1), round(a[:, 1].max(), 1))
    for n in m.nodes[:2]:
        print('   node', repr(n.name)[:20], 'pos', [round(x, 2) for x in n.pos], 'rot', round(n.rotangle, 3), [round(x, 2) for x in n.rotaxis], 'scale', [round(x, 2) for x in n.scale])
        print('   mat3', [round(x, 2) for x in n.mat3], 'offset', [round(x, 2) for x in n.offset], 'only', n.only)
