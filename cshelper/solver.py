"""Global five-state constraint solver. Exact proofs, bounded model estimates.

Enumerate only frontier assignments; free cells are integrated with integer
multinomial weights. Partial enumeration is a heuristic, never a safety proof.
"""
import math
import time
from .engine import Result, _allowed_vectors


def analyze(obs, seed=0, time_budget=20, exact_only=False, verbose=False, cancel=None):
    import z3
    started = time.monotonic()
    deadline = started + max(0.05, time_budget)
    out = Result(obs)
    out.proven_safe = set()
    out.proven_mines = set()
    def finish(status, msg):
        out.status, out.msg = status, msg
        out.elapsed = time.monotonic() - started
        return out
    if getattr(obs, 'observation_error', None):
        return finish('unreadable', obs.observation_error)
    if obs.mode not in ('complex', 'hyper'):
        return finish('inconsistent', '未知模式')
    if not obs.started or obs.totals is None:
        return finish('not_started', '等待首次点击')
    closed = [(r,c) for r in range(obs.h) for c in range(obs.w) if obs.value[r][c] is None]
    totals = obs.totals
    if len(totals) != 4 or any(type(t) is not int or t < 0 for t in totals) or sum(totals) > len(closed):
        return finish('inconsistent', '四类雷总数与未开格数量矛盾')
    if not closed:
        return finish('done', '所有安全格均已翻开')
    clues = [(r,c) for r in range(obs.h) for c in range(obs.w) if obs.value[r][c] is not None]
    closed_set = set(closed)
    frontier = sorted({q for rc in clues for q in obs.nbrs(*rc) if q in closed_set})
    free = sorted(closed_set - set(frontier))
    # A separate context permits independent worker threads.
    ctx = z3.Context()
    solver = z3.Solver(ctx=ctx)
    solver.set(random_seed=seed)
    v = {rc: [z3.Bool('v_%d_%d_%d' % (*rc,t), ctx=ctx) for t in range(5)] for rc in frontier}
    def count(xs):
        return z3.Sum([z3.If(x,1,0) for x in xs]) if xs else z3.IntVal(0,ctx)
    for states in v.values():
        solver.add(z3.PbEq([(x,1) for x in states],1))
    counts = [count([v[rc][t] for rc in frontier]) for t in range(1,5)]
    for t in range(4):
        solver.add(counts[t] <= totals[t])
    solver.add(sum(totals) - z3.Sum(counts) <= len(free))
    for r,c in clues:
        ns = [q for q in obs.nbrs(r,c) if q in v]
        if obs.blank[r][c]:
            solver.add(*[v[q][0] for q in ns])
        else:
            allowed = _allowed_vectors(obs.value[r][c],len(ns),obs.mode)
            nc = [count([v[q][t] for q in ns]) for t in range(1,5)]
            solver.add(z3.Or(*[z3.And(*[nc[t] == a[t] for t in range(4)]) for a in allowed]) if allowed else z3.BoolVal(False,ctx))
    def check(limit=deadline):
        if (cancel and cancel.is_set()) or time.monotonic() >= limit:
            return z3.unknown
        solver.set(timeout=max(1,min(250,int((limit-time.monotonic())*1000))))
        return solver.check()
    # Retry short solver slices until deadline; cancellation remains responsive.
    def checked(limit):
        while True:
            state = check(limit)
            if state != z3.unknown or time.monotonic() >= limit or (cancel and cancel.is_set()):
                return state
    first = checked(deadline)
    if first == z3.unsat:
        return finish('inconsistent','没有符合线索与四类总数的棋盘')
    if first != z3.sat:
        return finish('cancelled' if cancel and cancel.is_set() else 'too_big','求解超时或已停止，未生成动作')
    model = solver.model()
    # Prove all model-safe candidates together. Each SAT counterexample removes
    # at least one candidate. UNSAT proves the remaining set in one query.
    candidates = {rc for rc in frontier if z3.is_true(model.eval(v[rc][0]))}
    proof_deadline = started + max(0.05,time_budget)*0.45
    while candidates and time.monotonic() < proof_deadline:
        solver.push()
        solver.add(z3.Or(*[z3.Not(v[q][0]) for q in candidates]))
        state = checked(proof_deadline)
        if state == z3.sat:
            witness = solver.model()
            candidates = {q for q in candidates if z3.is_true(witness.eval(v[q][0]))}
        solver.pop()
        if state == z3.unsat:
            out.proven_safe.update(candidates)
            break
        if state != z3.sat:
            break
    if free:
        solver.push()
        solver.add(z3.Sum(counts) < sum(totals))
        state = checked(proof_deadline)
        solver.pop()
        if state == z3.unsat:
            out.proven_safe.update(free)
    weights = 0
    marg = {q:[0]*4 for q in closed}
    models = 0
    complete = False
    solver.push()
    while models < 2048:
        state = checked(deadline)
        if state == z3.unsat:
            complete = True
            break
        if state != z3.sat:
            break
        m = solver.model()
        assignment = {q: next(t for t in range(5) if z3.is_true(m.eval(v[q][t]))) for q in frontier}
        used = [sum(t == k for t in assignment.values()) for k in range(1,5)]
        remain = [totals[k]-used[k] for k in range(4)]
        weight = 1
        n = len(free)
        for k in remain:
            weight *= math.comb(n,k)
            n -= k
        weights += weight
        models += 1
        for q,t in assignment.items():
            if t:
                marg[q][t-1] += weight
        for q in free:
            for t in range(4):
                # Integer numerator, divide by free count only at the end.
                marg[q][t] += weight * remain[t]
        if not frontier:
            complete = True
            break
        solver.add(z3.Or(*[z3.Not(v[q][t]) for q,t in assignment.items()]))
    solver.pop()
    out.approx = not complete
    out.n_states = models
    out.comp_info = [dict(cells=len(frontier),cons=len(clues),mode='exact' if complete else 'bounded',info={'models':models,'proofs':len(out.proven_safe)},sec=time.monotonic()-started)]
    for q in closed:
        if weights:
            divisor = weights * (len(free) if q in free else 1)
            pt = [x/divisor for x in marg[q]]
        else:
            pt = [t/len(closed) for t in totals]
        if not complete and q not in out.proven_safe:
            # Partial models are not uniform samples. Shrink away from 0/1.
            pt = [0.9*p + 0.1*totals[t]/len(closed) for t,p in enumerate(pt)]
        if q in out.proven_safe:
            pt = [0.0]*4
        out.ptype[q] = pt
        out.prob[q] = sum(pt)
        out.exact[q] = complete or q in out.proven_safe
        if complete and sum(marg[q]) == 0:
            out.proven_safe.add(q)
        if complete and sum(marg[q]) == divisor:
            out.proven_mines.add(q)
    if cancel and cancel.is_set():
        return finish('cancelled','已停止')
    if exact_only and not complete:
        return finish('too_big','精确计数未完成')
    return finish('ok','精确概率' if complete else '有界模型估计（非均匀采样）；安全格另经不可满足性证明')
