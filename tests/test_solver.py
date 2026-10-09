import itertools
import random
import threading
import unittest
from cshelper.engine import Obs, disp, TYPES, recommend
from cshelper.solver import analyze
from cshelper.controller import board_status, choose_action
from cshelper.recognize import Board, Cell


def brute(o):
    closed=[(r,c) for r in range(o.h) for c in range(o.w) if o.value[r][c] is None]
    worlds=[]
    for values in itertools.product(range(5),repeat=len(closed)):
        if tuple(values.count(t) for t in range(1,5)) != o.totals:
            continue
        d=dict(zip(closed,values))
        valid=True
        for r in range(o.h):
            for c in range(o.w):
                if o.value[r][c] is None:
                    continue
                ns=[d.get(q,0) for q in o.nbrs(r,c)]
                a=sum(TYPES[t-1][0] for t in ns if t)
                b=sum(TYPES[t-1][1] for t in ns if t)
                if o.blank[r][c]:
                    valid &= not any(ns)
                else:
                    valid &= any(ns) and disp(a,b,o.mode)==o.value[r][c]
        if valid:
            worlds.append(d)
    return worlds


class SolverTests(unittest.TestCase):
    def test_random_exact_against_bruteforce(self):
        rng=random.Random(73)
        for mode in ('complex','hyper'):
            for case in range(20):
                o=Obs(3,2,mode)
                truth=[rng.randrange(5) for _ in range(6)]
                truth[rng.randrange(6)]=0
                o.totals=tuple(truth.count(t) for t in range(1,5))
                o.started=True
                for i,t in enumerate(truth):
                    if t==0 and rng.random()<0.8:
                        r,c=divmod(i,3)
                        ns=[truth[y*3+x] for y,x in o.nbrs(r,c)]
                        a=sum(TYPES[k-1][0] for k in ns if k)
                        b=sum(TYPES[k-1][1] for k in ns if k)
                        o.value[r][c]=disp(a,b,mode)
                        o.blank[r][c]=not any(ns)
                worlds=brute(o)
                result=analyze(o,time_budget=3)
                self.assertEqual(result.status,'ok')
                self.assertFalse(result.approx)
                for rc,p in result.prob.items():
                    expected=sum(d[rc]!=0 for d in worlds)/len(worlds)
                    self.assertAlmostEqual(p,expected,places=10)
                    for t in range(4):
                        self.assertAlmostEqual(result.ptype[rc][t],sum(d[rc]==t+1 for d in worlds)/len(worlds),places=10)
                self.assertTrue(all(all(d[q]==0 for d in worlds) for q in result.proven_safe))

    def test_zero_is_not_blank(self):
        for mode in ('complex','hyper'):
            o=Obs(3,1,mode); o.started=True; o.totals=(0,0,0,0); o.value[0][1]=0
            self.assertEqual(analyze(o).status,'inconsistent')
            o.blank[0][1]=True
            r=analyze(o)
            self.assertEqual(len(r.proven_safe),2)
            o.blank[0][1]=False; o.totals=(1,1,0,0)
            self.assertEqual(analyze(o).prob,{(0,0):1.0,(0,2):1.0})

    def test_free_cells_and_overflow(self):
        o=Obs(40,30,'complex'); o.started=True; o.totals=(100,100,100,100)
        r=analyze(o,time_budget=2)
        self.assertFalse(r.approx)
        self.assertAlmostEqual(r.prob[(0,0)],1/3)

    def test_cancel(self):
        event=threading.Event(); event.set()
        o=Obs(3,1,'complex'); o.started=True; o.totals=(1,0,0,0)
        self.assertEqual(analyze(o,cancel=event).status,'cancelled')

    def test_flags_are_not_constraints(self):
        o=Obs(3,1,'complex'); o.started=True; o.totals=(1,0,0,0); o.flag[0][0]=4
        self.assertAlmostEqual(analyze(o).prob[(0,0)],1/3)

    def test_controller_gates(self):
        b=Board(3,1,1,'complex'); b.cells=[[Cell('closed') for _ in range(3)]]; b.face='face_normal'
        self.assertEqual(board_status(b),'ready')
        self.assertIsNotNone(choose_action(b,None))
        self.assertIsNone(choose_action(b,None,False))
        b.cells[0][0]=Cell('unknown')
        self.assertIsNone(choose_action(b,None))
        b.face='face_dead'
        self.assertEqual(board_status(b),'lost')

if __name__=='__main__':
    unittest.main()
