import sys, collections, json
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro

rsw = ro.parse_rsw(fetch.fetch(r'data\prontera.rsw').read_bytes())
ms = [o for o in rsw['objects'] if o.kind == 1]
c = collections.Counter(o.filename for o in ms)
for k, v in c.most_common(8):
    m = ro.parse_rsm(fetch.fetch(r'data\model\\' + k).read_bytes())
    pts = []
    for n in m.nodes:
        if n.vertices:
            pts.append(np.array(n.vertices))
    a = np.vstack(pts)
    print(v, 'nodes', len(m.nodes), 'v', len(a))
    print('   min', a.min(0).round(1).tolist(), 'max', a.max(0).round(1).tolist())
