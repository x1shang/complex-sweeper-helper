# -*- coding: utf-8 -*-
"""复扫雷约束引擎：把"看到的数字 + 四类雷总数"变成逐格概率和推荐动作。

数学要点（推导见 ../complexweeper-analysis/）：
  * 显示值 N = a^2+b^2（圆复数）或 a^2-b^2（闵可夫斯基），
    a = #(+1)-#(-1)，b = #(+i)-#(-i)，每种雷给 |a|+|b| 贡献 1。
    所以数字几乎唯一决定邻域雷数（只有 25 例外：5 或 7）。
  * 每格 5 种状态（空/+1/-1/+i/-i），远比经典扫雷的二元状态难。
  * 全局约束：四类雷总数（表头计雷器 + 棋盘上已插的旗）。
  * 概率 = 对"与所见相容的全部布雷方案"按"剩余雷放进自由格"的多项式系数加权。

规模控制（重要）：一个 16×16 中级的边界连通分量能有 56 格、5^56 的裸空间，
精确枚举不现实。所以：
  * 小分量 -> 精确枚举（节点预算 + 墙钟截止）
  * 大分量 -> 先随机下潜找一个可行解，再做 MCMC 均匀采样（单格换态 + 局部校验），
    概率标记为 approx
  * 分量之间用"计数向量分布"做加权卷积；规模过大时退化为均值场近似
"""
import random
import time
from itertools import product
from math import lgamma, exp

TYPES = ((1, 0), (-1, 0), (0, 1), (0, -1))
TNAMES = ("+1", "-1", "+i", "-i")

NODE_BUDGET = 200_000      # 单分量精确枚举节点预算
COMP_SECONDS = 4.0         # 单分量精确枚举/找解的时间上限
SAMPLE_TARGET = 4000       # MCMC 采样次数
BURN_IN = 1200
TIME_BUDGET = 25.0         # analyze 总预算


def disp(a, b, mode):
    return a * a + b * b if mode == "complex" else a * a - b * b


class Obs:
    def __init__(self, w, h, mode):
        self.w, self.h, self.mode = w, h, mode
        self.value = [[None] * w for _ in range(h)]
        self.blank = [[False] * w for _ in range(h)]
        self.flag = [[0] * w for _ in range(h)]
        self.totals = None
        self.started = False

    def nbrs(self, r, c):
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr or dc:
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < self.h and 0 <= cc < self.w:
                        out.append((rr, cc))
        return out


def obs_from_board(b):
    o = Obs(b.w, b.h, b.mode)
    for r in range(b.h):
        for c in range(b.w):
            k = b.cells[r][c]
            if k.kind == "num":
                o.value[r][c] = k.val
            elif k.kind == "blank":
                o.value[r][c], o.blank[r][c] = 0, True
            elif k.kind in ("flag", "flagmine"):
                o.flag[r][c] = k.val
    o.totals = b.totals()
    o.started = b.counters is not None
    return o


class Result:
    def __init__(self, obs):
        self.obs = obs
        self.prob = {}
        self.ptype = {}
        self.exact = {}
        self.status = "ok"
        self.msg = ""
        self.approx = False
        self.n_states = 0
        self.comp_info = []
        self.elapsed = 0.0


def _allowed_vectors(d, k, mode):
    out = set()
    for v in product(range(k + 1), repeat=4):
        if sum(v) > k:
            continue
        a = sum(v[i] * TYPES[i][0] for i in range(4))
        b = sum(v[i] * TYPES[i][1] for i in range(4))
        if disp(a, b, mode) == d:
            out.add(v)
    return frozenset(out)


def _multinom_log(n, ks):
    s = sum(ks)
    if any(k < 0 for k in ks) or s > n:
        return None
    v = lgamma(n + 1) - lgamma(n - s + 1)
    for k in ks:
        v -= lgamma(k + 1)
    return v


class _Budget(Exception):
    pass


class _Search:
    """一次搜索的状态机：变量序按"约束尽早完整"排，可行性检查带记忆化。"""

    def __init__(self, cells, cls, node_budget=NODE_BUDGET, deadline=None):
        local = {g: k for k, g in enumerate(cells)}
        cons = [(sorted(local[g] for g in gi), av) for gi, av in cls]
        order, seen = [], set()
        for ks, _ in sorted(cons, key=lambda kv: len(kv[0])):
            for k in ks:
                if k not in seen:
                    seen.add(k)
                    order.append(k)
        for k in range(len(cells)):
            if k not in seen:
                order.append(k)
        rank = {k: i for i, k in enumerate(order)}
        self.order = order
        self.cinfo = [(sorted(rank[k] for k in ks), av) for ks, av in cons]
        self.cell_cons = [[] for _ in order]
        for ci, (ks, _) in enumerate(self.cinfo):
            for k in ks:
                self.cell_cons[k].append(ci)
        self.cur = [[0, 0, 0, 0] for _ in self.cinfo]
        self.rem = [len(ks) for ks, _ in self.cinfo]
        self.cache = [dict() for _ in self.cinfo]
        self.state = [0] * len(order)
        self.nodes = 0
        self.node_budget = node_budget
        self.deadline = deadline

    def feasible(self, ci):
        c = self.cur[ci]
        key = (c[0], c[1], c[2], c[3], self.rem[ci])
        d = self.cache[ci]
        v = d.get(key)
        if v is None:
            r = self.rem[ci]
            sc = c[0] + c[1] + c[2] + c[3]
            v = False
            for av in self.cinfo[ci][1]:
                if (av[0] >= c[0] and av[1] >= c[1] and av[2] >= c[2] and av[3] >= c[3]
                        and av[0] + av[1] + av[2] + av[3] - sc <= r):
                    v = True
                    break
            d[key] = v
        return v

    def tick(self):
        self.nodes += 1
        if self.nodes > self.node_budget:
            raise _Budget()
        if (self.nodes & 1023) == 0 and self.deadline and time.time() > self.deadline:
            raise _Budget()


def _enum_component(cells, cls, deadline):
    s = _Search(cells, cls, deadline=deadline)
    u_map, cell_map = {}, {}
    order, cell_cons, state = s.order, s.cell_cons, s.state

    def rec(d):
        s.tick()
        if d == len(order):
            u = [0, 0, 0, 0]
            for k in range(len(order)):
                if state[k]:
                    u[state[k] - 1] += 1
            ut = tuple(u)
            u_map[ut] = u_map.get(ut, 0) + 1
            for k in range(len(order)):
                key = (cells[order[k]], state[k])
                m = cell_map.setdefault(key, {})
                m[ut] = m.get(ut, 0) + 1
            return
        touched = cell_cons[d]
        for val in range(5):
            for ci in touched:
                if val:
                    s.cur[ci][val - 1] += 1
                s.rem[ci] -= 1
            if all(s.feasible(ci) for ci in touched):
                state[d] = val
                rec(d + 1)
                state[d] = 0
            for ci in touched:
                if val:
                    s.cur[ci][val - 1] -= 1
                s.rem[ci] += 1

    rec(0)
    return u_map, cell_map, s.nodes


def _find_solution(cells, cls, rng, deadline, restarts=40, steps=4000):
    """min-conflicts 局部搜索找一个可行解（DFS 在这种 5 态大分量上太慢）。

    随机初始化 -> 反复挑一条被违反的约束，改它里面最"无害"的那一格。
    """
    local = {g: k for k, g in enumerate(cells)}
    cons = [(sorted(local[g] for g in gi), av) for gi, av in cls]
    cell_cons = [[] for _ in cells]
    for ci, (ks, _) in enumerate(cons):
        for k in ks:
            cell_cons[k].append(ci)

    for _ in range(restarts):
        state = [rng.randrange(5) for _ in cells]
        cur = [[0, 0, 0, 0] for _ in cons]
        for ci, (ks, _) in enumerate(cons):
            for k in ks:
                if state[k]:
                    cur[ci][state[k] - 1] += 1
        ok_all = all(tuple(cur[ci]) in cons[ci][1] for ci in range(len(cons)))
        for step in range(steps):
            if ok_all:
                return state
            if deadline and (step & 127) == 0 and time.time() > deadline:
                return None
            viol = [ci for ci in range(len(cons)) if tuple(cur[ci]) not in cons[ci][1]]
            ci = viol[rng.randrange(len(viol))]
            ks = cons[ci][0]
            k = ks[rng.randrange(len(ks))]
            old = state[k]
            best_v, best_score, ties = old, 10 ** 9, []
            for v in range(5):
                if v == old:
                    continue
                score = 0
                for cj in cell_cons[k]:
                    c = cur[cj]
                    a0, a1, a2, a3 = c
                    if old:
                        if old == 1:
                            a0 -= 1
                        elif old == 2:
                            a1 -= 1
                        elif old == 3:
                            a2 -= 1
                        else:
                            a3 -= 1
                    if v:
                        if v == 1:
                            a0 += 1
                        elif v == 2:
                            a1 += 1
                        elif v == 3:
                            a2 += 1
                        else:
                            a3 += 1
                    if (a0, a1, a2, a3) not in cons[cj][1]:
                        score += 1
                if score < best_score:
                    best_score, best_v, ties = score, v, [v]
                elif score == best_score:
                    ties.append(v)
            if not ties:
                continue
            new = ties[rng.randrange(len(ties))]
            if new != old:
                for cj in cell_cons[k]:
                    if old:
                        cur[cj][old - 1] -= 1
                    if new:
                        cur[cj][new - 1] += 1
                state[k] = new
            ok_all = all(tuple(cur[cj]) in cons[cj][1] for cj in range(len(cons)))
        if ok_all:
            return state
    return None


def _mcmc_component(cells, cls, rng, deadline, n_samples=SAMPLE_TARGET, burn=BURN_IN):
    """MCMC 均匀采样。两种提议都用"对称提议"保证平稳分布是可行赋值上的均匀分布：

      1) 单格换态：均匀挑格 + 均匀挑新态；
      2) 约束块移动：均匀挑一条约束 + 均匀挑它允许的计数向量 + 把该约束的格子
         按这个计数向量均匀重排。（单格换态在紧约束下几乎全被拒，链会冻住，
         块移动是让链真正走起来的关键。）
    """
    local = {g: k for k, g in enumerate(cells)}
    cons = [(sorted(local[g] for g in gi), av, tuple(sorted(av))) for gi, av in cls]
    cell_cons = [[] for _ in cells]
    for ci, (ks, av, _) in enumerate(cons):
        for k in ks:
            cell_cons[k].append(ci)
    state = _find_solution(cells, cls, rng, deadline)
    if state is None:
        return None, None, None
    cur = [[0, 0, 0, 0] for _ in cons]
    for ci, (ks, _, _) in enumerate(cons):
        for k in ks:
            if state[k]:
                cur[ci][state[k] - 1] += 1

    def valid(ci):
        return tuple(cur[ci]) in cons[ci][1]

    n = len(cells)
    acc = tr = 0
    u_map, cell_map = {}, {}
    got = 0
    n_cons = len(cons)

    def block_move(seed):
        """区域重采样：把 seed 附近的若干格一起重新随机安排。

        单格/单约束的局部移动在紧约束下几乎全被拒，链会冻在少数解上；
        把一小片格子整体重排（块外固定）才能在不同解之间跳。
        块的选择只依赖约束结构、赋值在块内均匀采样，所以提议仍然对称。
        """
        block, frontier = [seed], {seed}
        while frontier and len(block) < 9:
            k = frontier.pop()
            for ci in cell_cons[k]:
                for j in cons[ci][0]:
                    if j not in block:
                        block.append(j)
                        frontier.add(j)
                        if len(block) >= 9:
                            break
                if len(block) >= 9:
                    break
        bset = set(block)
        rel = []
        for ci in sorted({ci for k in block for ci in cell_cons[k]}):
            ks, av, _ = cons[ci]
            fixed = [0, 0, 0, 0]
            for k in ks:
                if k not in bset and state[k]:
                    fixed[state[k] - 1] += 1
            allowed = {tuple(v[i] - fixed[i] for i in range(4)) for v in av
                       if all(v[i] >= fixed[i] for i in range(4))}
            if not allowed:
                return None
            rel.append(([k for k in ks if k in bset], allowed, tuple(sorted(allowed))))
        bcur = [[0, 0, 0, 0] for _ in rel]
        brem = [len(ks) for ks, _, _ in rel]
        pos = {k: i for i, k in enumerate(block)}
        bcell = [[] for _ in block]
        for ri, (ks, _, _) in enumerate(rel):
            for k in ks:
                bcell[pos[k]].append(ri)
        bstate = [0] * len(block)

        def ok(ri):
            c, r = bcur[ri], brem[ri]
            sc = c[0] + c[1] + c[2] + c[3]
            for av in rel[ri][2]:
                if (av[0] >= c[0] and av[1] >= c[1] and av[2] >= c[2] and av[3] >= c[3]
                        and av[0] + av[1] + av[2] + av[3] - sc <= r):
                    return True
            return False

        def dive(d):
            if d == len(block):
                return True
            touched = bcell[d]
            vals = [0, 1, 2, 3, 4]
            rng.shuffle(vals)
            for v in vals:
                for ri in touched:
                    if v:
                        bcur[ri][v - 1] += 1
                    brem[ri] -= 1
                if all(ok(ri) for ri in touched):
                    bstate[d] = v
                    if dive(d + 1):
                        return True
                    bstate[d] = 0
                for ri in touched:
                    if v:
                        bcur[ri][v - 1] -= 1
                    brem[ri] += 1
            return False

        if not dive(0):
            return None
        return {block[i]: bstate[i] for i in range(len(block))}

    for it in range(burn + n_samples):
        if (it & 255) == 0 and time.time() > deadline:
            break
        tr += 1
        r = rng.random()
        if r < 0.35:
            cell = rng.randrange(n)
            old = state[cell]
            new = rng.randrange(5)
            if new == old:
                tr -= 1
                continue
            touched = cell_cons[cell]
            for ci in touched:
                if old:
                    cur[ci][old - 1] -= 1
                if new:
                    cur[ci][new - 1] += 1
            if all(valid(ci) for ci in touched):
                state[cell] = new
                acc += 1
            else:
                for ci in touched:
                    if new:
                        cur[ci][new - 1] -= 1
                    if old:
                        cur[ci][old - 1] += 1
        elif r < 0.65:
            ci = rng.randrange(n_cons)
            ks, av, avl = cons[ci]
            av_new = avl[rng.randrange(len(avl))]
            pool = []
            for t in range(1, 5):
                pool += [t] * av_new[t - 1]
            pool += [0] * (len(ks) - len(pool))
            rng.shuffle(pool)
            old_vals = [state[k] for k in ks]
            if old_vals == pool:
                tr -= 1
                continue
            touched = set()
            for k in ks:
                touched.update(cell_cons[k])
            for j, k in enumerate(ks):
                if old_vals[j]:
                    for cj in cell_cons[k]:
                        cur[cj][old_vals[j] - 1] -= 1
                if pool[j]:
                    for cj in cell_cons[k]:
                        cur[cj][pool[j] - 1] += 1
            if all(valid(cj) for cj in touched):
                for j, k in enumerate(ks):
                    state[k] = pool[j]
                acc += 1
            else:
                for j, k in enumerate(ks):
                    if pool[j]:
                        for cj in cell_cons[k]:
                            cur[cj][pool[j] - 1] -= 1
                    if old_vals[j]:
                        for cj in cell_cons[k]:
                            cur[cj][old_vals[j] - 1] += 1
        else:
            newmap = block_move(rng.randrange(n))
            if newmap is None:
                continue
            touched = set()
            for k in newmap:
                touched.update(cell_cons[k])
            old_vals = {k: state[k] for k in newmap}
            for k, v in newmap.items():
                if old_vals[k]:
                    for cj in cell_cons[k]:
                        cur[cj][old_vals[k] - 1] -= 1
                if v:
                    for cj in cell_cons[k]:
                        cur[cj][v - 1] += 1
            if all(valid(cj) for cj in touched):
                for k, v in newmap.items():
                    state[k] = v
                acc += 1
            else:
                for k, v in newmap.items():
                    if v:
                        for cj in cell_cons[k]:
                            cur[cj][v - 1] -= 1
                    if old_vals[k]:
                        for cj in cell_cons[k]:
                            cur[cj][old_vals[k] - 1] += 1
        if it < burn:
            continue
        got += 1
        u = [0, 0, 0, 0]
        for k in range(n):
            if state[k]:
                u[state[k] - 1] += 1
        ut = tuple(u)
        u_map[ut] = u_map.get(ut, 0) + 1.0
        for k in range(n):
            key = (cells[k], state[k])
            m = cell_map.setdefault(key, {})
            m[ut] = m.get(ut, 0) + 1.0
    if got == 0:
        return None, None, None
    for k in list(u_map):
        u_map[k] /= got
    for m in cell_map.values():
        for k in list(m):
            m[k] /= got
    return u_map, cell_map, {"samples": got, "accept": round(acc / max(tr, 1), 3)}


def analyze(obs, seed=0, time_budget=TIME_BUDGET, exact_only=False, verbose=False):
    t_start = time.time()
    rng = random.Random(seed)
    res = Result(obs)
    w, h = obs.w, obs.h
    if not obs.started or obs.totals is None:
        res.status = "not_started"
        res.msg = "还没开局（计雷器是空的）"
        return res
    if any(t < 0 for t in obs.totals):
        res.status = "inconsistent"
        res.msg = "四类雷总数出现负数，计雷器识别可能有误"
        return res
    closed = [(r, c) for r in range(h) for c in range(w) if obs.value[r][c] is None]
    if not closed:
        res.status = "done"
        res.msg = "没有未翻开的格子了"
        return res
    idx = {rc: i for i, rc in enumerate(closed)}
    n = len(closed)

    cons = []
    for r in range(h):
        for c in range(w):
            if obs.value[r][c] is None:
                continue
            U = tuple(idx[q] for q in obs.nbrs(r, c) if q in idx)
            if not U:
                if not obs.blank[r][c] and obs.value[r][c] != 0:
                    res.status = "inconsistent"
                    res.msg = "格 (%d,%d) 显示 %s，但八个邻居都已翻开" % (r, c, obs.value[r][c])
                    return res
                continue
            if obs.blank[r][c]:
                cons.append((U, frozenset({(0, 0, 0, 0)})))
                continue
            av = _allowed_vectors(obs.value[r][c], len(U), obs.mode)
            if not av:
                res.status = "inconsistent"
                res.msg = "格 (%d,%d) 显示值 %s 与 %d 个未知邻居矛盾" % (r, c, obs.value[r][c], len(U))
                return res
            cons.append((U, av))

    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for U, _ in cons:
        for i in range(1, len(U)):
            a, b = find(U[0]), find(U[i])
            if a != b:
                parent[a] = b
    comps = {}
    for i in range(n):
        comps.setdefault(find(i), []).append(i)
    comp_list = list(comps.values())
    comp_of = {}
    for ci, cells in enumerate(comp_list):
        for i in cells:
            comp_of[i] = ci
    comp_cons = [[] for _ in comp_list]
    for U, av in cons:
        comp_cons[comp_of[U[0]]].append((U, av))

    active = [ci for ci in range(len(comp_list)) if comp_cons[ci]]
    free_idx = [i for i in range(n) if not comp_cons[comp_of[i]]]
    nfree = len(free_idx)
    free_cells = [closed[i] for i in free_idx]

    comp_maps = []
    for ci in active:
        cells = comp_list[ci]
        t_c = time.time()
        dl = min(t_c + COMP_SECONDS, t_start + time_budget)
        mode, info = "exact", None
        try:
            u_map, cell_map, nodes = _enum_component(cells, comp_cons[ci], dl)
            info = {"nodes": nodes}
        except _Budget:
            if exact_only:
                res.status = "too_big"
                res.msg = "分量 %d 精确枚举超预算（%d 格）" % (ci, len(cells))
                return res
            mode = "mcmc"
            u_map, cell_map, info = _mcmc_component(
                cells, comp_cons[ci], rng, min(time.time() + 8.0, t_start + time_budget + 10))
            if u_map is None:
                res.status = "too_big"
                res.msg = "分量 %d（%d 格）连一个可行解都找不到" % (ci, len(cells))
                return res
        comp_maps.append((cells, u_map, cell_map, mode))
        res.comp_info.append({"cells": len(cells), "cons": len(comp_cons[ci]),
                              "mode": mode, "info": info, "sec": time.time() - t_c})
        for g in cells:
            res.exact[closed[g]] = (mode == "exact")
        if verbose:
            print("   [引擎] 分量%d: %d 格 %s %s %.2fs"
                  % (ci, len(cells), mode, info, time.time() - t_c), flush=True)

    totals = obs.totals
    dists, means, zs = [], [], []
    for _, u_map, _, _ in comp_maps:
        z = sum(u_map.values()) or 1.0
        dists.append({u: c / z for u, c in u_map.items()})
        means.append([sum(u[i] * c for u, c in dists[-1].items()) for i in range(4)])
        zs.append(z)

    def weight_of(u):
        lg = _multinom_log(nfree, [totals[i] - u[i] for i in range(4)])
        return 0.0 if lg is None else exp(lg)

    def conv(a, b):
        out = {}
        for ua, wa in a.items():
            for ub, wb in b.items():
                t = (ua[0] + ub[0], ua[1] + ub[1], ua[2] + ub[2], ua[3] + ub[3])
                if t[0] > totals[0] or t[1] > totals[1] or t[2] > totals[2] or t[3] > totals[3]:
                    continue
                out[t] = out.get(t, 0) + wa * wb
        return out

    exact_ok = True
    full = {(0, 0, 0, 0): 1.0}
    for d in dists:
        if len(full) * len(d) > 1_000_000 or len(full) > 20000:
            exact_ok = False
            break
        full = conv(full, d)
    res.approx = (not exact_ok) or any(m[3] != "exact" for m in comp_maps)

    if exact_ok:
        pref = [{(0, 0, 0, 0): 1.0}]
        for d in dists:
            pref.append(conv(pref[-1], d))
        suf = [{(0, 0, 0, 0): 1.0} for _ in range(len(dists) + 1)]
        for i in range(len(dists) - 1, -1, -1):
            suf[i] = conv(dists[i], suf[i + 1])
        total = sum(c * weight_of(u) for u, c in full.items())
        if total <= 0:
            res.status = "inconsistent"
            res.msg = "与四类雷总数不兼容（计数器或识别可能有误）"
            return res
        res.n_states = len(full)
        for ci, (cells, u_map, cell_map, mode) in enumerate(comp_maps):
            other = conv(pref[ci], suf[ci + 1])
            wgt = {}
            for u in u_map:
                s = 0.0
                for su, c in other.items():
                    t = (u[0] + su[0], u[1] + su[1], u[2] + su[2], u[3] + su[3])
                    lg = _multinom_log(nfree, [totals[i] - t[i] for i in range(4)])
                    if lg is not None:
                        s += c * exp(lg)
                wgt[u] = s
            for g in cells:
                rc = closed[g]
                pt = [0.0, 0.0, 0.0, 0.0]
                for s in range(1, 5):
                    m = cell_map.get((g, s))
                    if m:
                        pt[s - 1] = sum(c * wgt.get(u, 0.0) for u, c in m.items()) / total
                res.ptype[rc] = pt
                res.prob[rc] = sum(pt)
        er = [0.0] * 4
        for u, c in full.items():
            w = c * weight_of(u) / total
            for i in range(4):
                er[i] += w * (totals[i] - u[i])
    else:
        tot_mean = [sum(m[i] for m in means) for i in range(4)]
        for ci, (cells, u_map, cell_map, mode) in enumerate(comp_maps):
            om = [tot_mean[i] - means[ci][i] for i in range(4)]
            wgt = {}
            for u in dists[ci]:
                lg = _multinom_log(nfree, [totals[i] - u[i] - om[i] for i in range(4)])
                wgt[u] = 0.0 if lg is None else exp(lg)
            zw = sum(wgt.values()) or 1.0
            for g in cells:
                rc = closed[g]
                pt = [0.0, 0.0, 0.0, 0.0]
                for s in range(1, 5):
                    m = cell_map.get((g, s))
                    if m:
                        pt[s - 1] = sum(c / zs[ci] * wgt.get(u, 0.0) for u, c in m.items()) / zw
                res.ptype[rc] = pt
                res.prob[rc] = sum(pt)
        er = [max(totals[i] - tot_mean[i], 0.0) for i in range(4)]
        res.n_states = sum(len(d) for d in dists)

    for rc in free_cells:
        pt = [er[i] / nfree for i in range(4)] if nfree else [0.0] * 4
        res.ptype[rc] = pt
        res.prob[rc] = sum(pt)
        res.exact[rc] = True
    res.elapsed = time.time() - t_start
    return res


def recommend(obs, res):
    """给出建议。

    安全保证只来自"精确枚举"或"自由格解析"的格子：采样得到的 0 概率不算数，
    否则助手会自信地把真雷说成安全格。
    """
    out = {"safe": [], "guesses": [], "chords": [], "flag_errors": [], "approx_cells": []}

    def sure_safe(rc):
        return res.exact.get(rc, False) and res.prob.get(rc, 1.0) <= 1e-12

    if res.status != "ok":
        return out
    for rc, p in res.prob.items():
        if not res.exact.get(rc, False):
            out["approx_cells"].append(rc)
        if sure_safe(rc):
            out["safe"].append(rc)
    for r in range(obs.h):
        for c in range(obs.w):
            if obs.flag[r][c] and sure_safe((r, c)):
                out["flag_errors"].append(((r, c), "这一格必然不是雷，旗插错了"))
    for r in range(obs.h):
        for c in range(obs.w):
            if obs.value[r][c] is None:
                continue
            un = [q for q in obs.nbrs(r, c)
                  if obs.value[q[0]][q[1]] is None and obs.flag[q[0]][q[1]] == 0]
            if un and all(sure_safe(q) for q in un):
                out["chords"].append(((r, c), tuple(un)))
    if not out["safe"]:
        cand = sorted(res.prob.items(), key=lambda kv: (round(kv[1], 9), -len(obs.nbrs(*kv[0]))))
        out["guesses"] = [(rc, p, res.exact.get(rc, False)) for rc, p in cand[:6]]
    return out
