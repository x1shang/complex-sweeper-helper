# -*- coding: utf-8 -*-
"""诊断：demo 局面的约束图规模有多大（不做枚举）。"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cshelper.atlas import default_atlas                       # noqa: E402
from cshelper.engine import _allowed_vectors, obs_from_board   # noqa: E402
from cshelper.layout import fit_zoom                           # noqa: E402
from cshelper.recognize import read_board                      # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.environ.get("CS_GAME_DIR", os.path.join(os.path.dirname(ROOT), "complexweeper"))
LAB = os.path.join(ROOT, "_lab")
ATLAS = default_atlas(GAME)

for name in ("demo.png", "demo-lose.png"):
    img = Image.open(os.path.join(LAB, name))
    fit = fit_zoom(img.width, img.height)
    b = read_board(img, ATLAS, *fit)
    obs = obs_from_board(b)
    w, h = obs.w, obs.h
    closed = [(r, c) for r in range(h) for c in range(w) if obs.value[r][c] is None]
    idx = {rc: i for i, rc in enumerate(closed)}
    n = len(closed)
    print("=== %s: 未翻开 %d 格, 四类总数 %s" % (name, n, obs.totals))

    cons = []
    for r in range(h):
        for c in range(w):
            if obs.value[r][c] is None:
                continue
            U = tuple(idx[q] for q in obs.nbrs(r, c) if q in idx)
            if not U:
                continue
            if obs.blank[r][c]:
                cons.append((U, 1, len(U)))
                continue
            av = _allowed_vectors(obs.value[r][c], len(U), obs.mode)
            cons.append((U, len(av), len(U)))
    print("  约束条数 %d; 每条 (候选向量数 x 格数):" % len(cons))
    from collections import Counter
    print("   候选向量数分布:", sorted(Counter(c[1] for c in cons).items()))
    print("   约束格数分布:", sorted(Counter(c[2] for c in cons).items()))

    # 连通分量（只统计有约束的）
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for U, _, _ in cons:
        for i in range(1, len(U)):
            a, b2 = find(U[0]), find(U[i])
            if a != b2:
                parent[a] = b2
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    sizes = sorted((len(v) for v in comps.values()), reverse=True)
    print("  分量数 %d，最大几个:", sizes[:10])
    # 每个格子的候选状态数（该格只被一条约束覆盖时）
    print("  各未翻开格被多少条约束覆盖:",
          sorted(Counter(sum(1 for U, _, _ in cons if i in U) for i in range(n)).items()))
