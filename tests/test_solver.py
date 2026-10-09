import itertools
import random
import threading
import unittest
from cshelper.engine import Obs, disp, TYPES, recommend
from cshelper.solver import analyze
from cshelper.controller import board_status, choose_action
from cshelper.recognize import Board, Cell


# ---------------------------------------------------------------------------
# 独立参照：穷举校验器**故意不使用** cshelper.engine 的 disp/TYPES。
# 若与被测引擎共用同一个值函数，值函数改错时两边会一起错、比对永远一致。
# 这里的实现由 DispReferenceTests 用手算常数表与 atlas 的可达值清单钉住。
#
# 已知边界：改坏"完整计数零支持"分支、或改坏 approx 平滑系数（0.9/0.1）都不会让本套件
# 变红。前者与候选集证明在完整枚举下语义等价（冗余）；后者是无文档规定的启发式常数，
# 若要保护它，请先在 README 写明该权重。
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# 独立参照：穷举校验器**故意不使用** cshelper.engine 的 disp/TYPES。
#
# 理由：如果校验器和被测引擎共用同一个值函数，那么值函数改错时两边会一起错，
# 穷举比对永远一致——实测把 a^2+b^2 与 a^2-b^2 对调，旧版本不会有任何测试变红。
# 这里复制一份独立实现，并由 test_disp_reference_matches_hand_values 用手算常数表
# 与 atlas 的可达值清单把它钉住。
# ---------------------------------------------------------------------------
REF_TYPES = ((1, 0), (-1, 0), (0, 1), (0, -1))


def ref_disp(a, b, mode):
    return a * a + b * b if mode == "complex" else a * a - b * b


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
                a=sum(REF_TYPES[t-1][0] for t in ns if t)
                b=sum(REF_TYPES[t-1][1] for t in ns if t)
                if o.blank[r][c]:
                    valid &= not any(ns)
                else:
                    valid &= any(ns) and ref_disp(a,b,o.mode)==o.value[r][c]
        if valid:
            worlds.append(d)
    return worlds


class DispReferenceTests(unittest.TestCase):
    """把值函数钉在"手算值 + 游戏图集清单"这两个外部参照上。"""

    def test_disp_reference_matches_hand_values(self):
        # (a, b) 由五态计数直接手算：a = #(+1)-#(-1)，b = #(+i)-#(-i)
        cases = [
            (1, 0, 'complex', 1), (2, 1, 'complex', 5), (3, 2, 'complex', 13),
            (5, 3, 'complex', 34), (7, 1, 'complex', 50), (8, 0, 'complex', 64),
            (1, 0, 'hyper', 1), (2, 1, 'hyper', 3), (3, 2, 'hyper', 5),
            (7, 1, 'hyper', 48), (0, 0, 'hyper', 0),
        ]
        for a, b, mode, want in cases:
            self.assertEqual(ref_disp(a, b, mode), want, (a, b, mode))
            self.assertEqual(disp(a, b, mode), want, "被测 disp 与手算值不符: %s" % ((a, b, mode),))

    def test_disp_values_agree_with_atlas_lists(self):
        # 第二个外部参照：游戏图集里真正存在的贴图名。
        from cshelper.atlas import complex_names, HYPER_ONLY, HYPER_POS
        complex_reachable = {int(n.split('_')[1]) for n in complex_names()}
        self.assertEqual(complex_reachable, {
            ref_disp(a, b, 'complex')
            for a in range(-8, 9) for b in range(-8, 9) if abs(a) + abs(b) <= 8})
        self.assertEqual(set(HYPER_ONLY), set(HYPER_POS) - complex_reachable)
        # 只有 HYPER_ONLY 里的值才是双曲模式独有的（如 3、48）；5 之类两边共有
        for a, b in ((2, 1), (7, 1)):
            self.assertNotIn(ref_disp(a, b, 'hyper'), complex_reachable)


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

    def test_bounded_path_proves_blank_neighbours(self):
        """有界（approx）路径：真实 16x16 局面走的就是这条，安全证明必须仍然成立。

        构造：一个空白格（8 邻居被强制为无雷）+ 远处一个宽松线索 + 足够大的四类总数，
        使模型枚举跑不完（complete=False）。此时完整计数的"零支持"分支不会生效，
        安全格只能来自"候选集不可满足"证明——把它改坏必须让本测试变红。
        """
        o=Obs(20,20,'complex')
        o.started=True
        o.value[2][2],o.blank[2][2]=0,True
        o.value[15][15]=1
        o.totals=(2,2,2,2)
        forced={(2+dr,2+dc) for dr in (-1,0,1) for dc in (-1,0,1) if dr or dc}
        loose={(15+dr,15+dc) for dr in (-1,0,1) for dc in (-1,0,1) if dr or dc}
        r=analyze(o,time_budget=6)
        self.assertEqual(r.status,'ok',r.msg)
        self.assertTrue(r.approx,'未走到有界路径，本测试失去意义')
        # 下界：空白格的邻居在**任何**局面里都必须无雷，安全证明必须找到它们。
        self.assertTrue(forced <= r.proven_safe,
                        '有界路径下空白格邻居未被证明安全: %s' % sorted(forced-r.proven_safe))
        # 上界：宽松线索的每个邻居都能在某个合法局面里当雷（例如它就是那颗唯一的 +1，
        # 其余雷放进自由区），所以它们**永远不可能**被证明安全。任何把它们算进
        # proven_safe 的实现都是错的——这一条专门抓"证明循环提前退出/判据写反"。
        self.assertEqual(r.proven_safe & loose, set(),
                         '不该被证明安全的格子进了 proven_safe: %s' % sorted(r.proven_safe & loose))
        for q in r.proven_safe:
            self.assertEqual(r.prob[q],0.0,q)
            self.assertEqual(r.ptype[q],[0.0]*4,q)
        for q,exact in r.exact.items():
            if q not in r.proven_safe:
                self.assertFalse(exact,'有界路径下非证明格不得标为精确: %s' % (q,))
        for q,p in r.prob.items():
            self.assertTrue(0.0<=p<=1.0,(q,p))

    def test_free_cells_proof_on_fully_loaded_frontier(self):
        """所有雷都被迫落在边界上时，自由格必须被证明安全（不可满足性证明）。"""
        o=Obs(3,3,'complex')
        o.started=True
        o.value[0][0]=9            # 三个 +1 邻居 => a=3,b=0 => D=9
        o.totals=(3,0,0,0)         # 雷数正好被边界吃满
        r=analyze(o,time_budget=3)
        self.assertEqual(r.status,'ok',r.msg)
        free={(0,2),(1,2),(2,0),(2,1),(2,2)}
        self.assertTrue(free <= r.proven_safe, sorted(free-r.proven_safe))
        for q in free:
            self.assertEqual(r.prob[q],0.0,q)

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
