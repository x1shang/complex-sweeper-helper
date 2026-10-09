# -*- coding: utf-8 -*-
"""诊断 MCMC 采样链到底动没动。"""
import os
import random
import sys
import time
from collections import Counter

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cshelper import engine as E                                   # noqa: E402
from cshelper.atlas import default_atlas                           # noqa: E402
from cshelper.layout import fit_zoom                               # noqa: E402
from cshelper.recognize import read_board                          # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.environ.get("CS_GAME_DIR", os.path.join(os.path.dirname(ROOT), "complexweeper"))
LAB = os.path.join(ROOT, "_lab")
ATLAS = default_atlas(GAME)

img = Image.open(os.path.join(LAB, "demo.png"))
b = read_board(img, ATLAS, *fit_zoom(img.width, img.height))
obs = E.obs_from_board(b)
w, h = obs.w, obs.h
closed = [(r, c) for r in range(h) for c in range(w) if obs.value[r][c] is None]
idx = {rc: i for i, rc in enumerate(closed)}
cons = []
for r in range(h):
    for c in range(w):
        if obs.value[r][c] is None:
            continue
        U = tuple(idx[q] for q in obs.nbrs(r, c) if q in idx)
        if not U:
            continue
        cons.append((U, frozenset({(0, 0, 0, 0)}) if obs.blank[r][c]
                     else E._allowed_vectors(obs.value[r][c], len(U), obs.mode)))
parent = list(range(len(closed)))


def find(x):
    while parent[x] != x:
        parent[x] = parent[parent[x]]
        x = parent[x]
    return x


for U, _ in cons:
    for i in range(1, len(U)):
        a, bb = find(U[0]), find(U[i])
        if a != bb:
            parent[a] = bb
comps = {}
for i in range(len(closed)):
    comps.setdefault(find(i), []).append(i)
comp_list = list(comps.values())
comp_of = {}
for ci, cells in enumerate(comp_list):
    for i in cells:
        comp_of[i] = ci
cc = [[] for _ in comp_list]
for U, av in cons:
    cc[comp_of[U[0]]].append((U, av))
big = max(range(len(comp_list)), key=lambda i: len(comp_list[i]))
cells = comp_list[big]
print("最大分量: %d 格 / %d 约束" % (len(cells), len(cc[big])))

rng = random.Random(0)
t0 = time.time()
sol = E._find_solution(cells, cc[big], rng, t0 + 20)
print("min-conflicts 找解: %s  用时 %.2fs" % ("成功" if sol else "失败", time.time() - t0))
if sol:
    # 校验这个解真的满足所有约束
    ok = True
    loc = {g: k for k, g in enumerate(cells)}
    for U, av in cc[big]:
        nv = [0, 0, 0, 0]
        for g in U:
            s = sol[loc[g]]
            if s:
                nv[s - 1] += 1
        if tuple(nv) not in av:
            ok = False
            break
    print("该解满足全部约束:", ok)
    print("该解的雷数:", sum(1 for s in sol if s), " 真值局面的四类总数:", obs.totals)

# 手工跑一次采样，统计链的活跃度
loc = {g: k for k, g in enumerate(cells)}
cons_l = [(sorted(loc[g] for g in U), av) for U, av in cc[big]]
cell_cons = [[] for _ in cells]
for ci, (ks, _) in enumerate(cons_l):
    for k in ks:
        cell_cons[k].append(ci)
state = list(sol) if sol else [0] * len(cells)
cur = [[0, 0, 0, 0] for _ in cons_l]
for ci, (ks, _) in enumerate(cons_l):
    for k in ks:
        if state[k]:
            cur[ci][state[k] - 1] += 1
print("起始状态已满足:", all(tuple(cur[ci]) in cons_l[ci][1] for ci in range(len(cons_l))))

acc = tr = 0
changes = Counter()
seen_states = set()
uv = Counter()
N = 4000
t0 = time.time()
for _ in range(N):
    cell = rng.randrange(len(cells))
    old = state[cell]
    new = rng.randrange(5)
    if new == old:
        continue
    tr += 1
    for ci in cell_cons[cell]:
        if old:
            cur[ci][old - 1] -= 1
        if new:
            cur[ci][new - 1] += 1
    if all(tuple(cur[ci]) in cons_l[ci][1] for ci in cell_cons[cell]):
        state[cell] = new
        acc += 1
        changes[cell] += 1
    else:
        for ci in cell_cons[cell]:
            if new:
                cur[ci][new - 1] -= 1
            if old:
                cur[ci][old - 1] += 1
    seen_states.add(tuple(state))
    u = [0, 0, 0, 0]
    for k in range(len(cells)):
        if state[k]:
            u[state[k] - 1] += 1
    uv[tuple(u)] += 1
print("提议 %d 次，接受 %d 次 (%.3f)，用时 %.2fs" % (tr, acc, acc / max(tr, 1), time.time() - t0))
print("出现过的不同完整状态数:", len(seen_states))
print("出现过的不同计数向量数:", len(uv))
print("每个格子被改动次数的分布:", sorted(Counter(changes.values()).items()))
print("从未被改动的格子数:", len(cells) - len(changes))
print("计数向量最频繁的几个:", uv.most_common(5))
