import sys, json
sys.path.insert(0, 'tools')
import fetch, ro
from build_assets import bake_rsm_local

with open('filelist.json', encoding='utf8') as f:
    fl = json.load(f)
models = [x for x in fl if x.lower().startswith('data\\model\\') and x.lower().endswith('.rsm')]
models.sort(key=lambda x: ('프론테라' not in x))
print('model count', len(models))
p = models[0]
print('path', repr(p))
print('url', fetch.url_for(p))
d = fetch.fetch(p)
print('size', d.stat().st_size)
m = ro.parse_rsm(d.read_bytes())
print('ver', m.version, 'nodes', len(m.nodes))
b = bake_rsm_local(m)
print('baked', None if b is None else (b[0].shape, len(set(b[2]))))
if b is not None:
    print('bbox', b[0].min(0).round(2).tolist(), b[0].max(0).round(2).tolist())
