import sys, collections
sys.path.insert(0, 'tools')
import fetch, ro
from build_assets import bake_rsm_local

rsw = ro.parse_rsw(fetch.fetch(r'data\prontera.rsw').read_bytes())
ms = [o for o in rsw['objects'] if o.kind == 1]
c = collections.Counter(o.filename for o in ms)

fl = set()
import json
with open('filelist.json', encoding='utf8') as f:
    fl = set(json.load(f))

for k, v in c.most_common(5):
    p = r'data\model\\' + k
    p = p.replace('\\\\', '\\')
    print('placements', v, 'name', repr(k))
    print('in filelist:', p in fl, [x for x in fl if x.endswith(k)][:3])
