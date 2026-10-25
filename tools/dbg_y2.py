import sys, collections
sys.path.insert(0, 'tools')
import numpy as np, fetch, ro

def chain_matrix(nodes):
    by = {n.name: n for n in nodes}
    out = {}
    def walk(n, parent):
        base = np.eye(4)
        base[:3, 3] = n.pos
        # rotation
        R = np.eye(4)
        x, y, z = n.rotaxis
        ln = (x*x+y*y+z*z) ** 0.5
        if ln > 1e-9:
            x, y, z = x/ln, y/ln, z/ln
            c, s = np.cos(n.rotangle), np.sin(n.rotangle)
            C = 1 - c
            R[:3, :3] = [[c+x*x*C, x*y*C-z*s, x*z*C+y*s],
                         [y*x*C+z*s, c+y*y*C, y*z*C-x*s],
                         [z*x*C-y*s, z*y*C+x*s, c+z*z*C]]
        S = np.eye(4); S[0, 0], S[1, 1], S[2, 2] = n.scale
        m = parent @ base @ R @ S
        out[n.name] = m
        for c2 in nodes:
            if c2.parent == n.name and c2 is not n:
                walk(c2, m)
    roots = [n for n in nodes if not n.parent or n.parent not in by or n.parent == n.name]
    for n in roots:
        walk(n, np.eye(4))
    return out

def full_pts(m):
    ch = chain_matrix(m.nodes)
    pts = []
    for n in m.nodes:
        if not n.vertices:
            continue
        M = np.array(ch.get(n.name, np.eye(4)))
        if not n.only:
            T = np.eye(4); T[:3, 3] = n.offset
            g = n.mat3
            M3 = np.eye(4)
            M3[0,0],M3[0,1],M3[0,2]=g[0],g[3],g[6]
            M3[1,0],M3[1,1],M3[1,2]=g[1],g[4],g[7]
            M3[2,0],M3[2,1],M3[2,2]=g[2],g[5],g[8]
            M = M @ T @ M3
        v = np.array(n.vertices)
        h = np.c_[v, np.ones(len(v))]
        pts.append((h @ M.T)[:, :3])
    return np.vstack(pts)

rsw = ro.parse_rsw(fetch.fetch(r'data\prontera.rsw').read_bytes())
c = collections.Counter(o.filename for o in rsw['objects'] if o.kind == 1)
for k in list(c)[:6]:
    m = ro.parse_rsm(fetch.fetch(r'data\model' + '\\' + k).read_bytes())
    a = full_pts(m)
    print(len(m.nodes), 'nodes  bbox', a.min(0).round(1).tolist(), a.max(0).round(1).tolist())
