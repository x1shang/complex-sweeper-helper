# -*- coding: utf-8 -*-
"""端到端验证：识别 -> 引擎 -> 与游戏真值对照。

demo-lose.png 里所有雷都画出来了（game over 会揭示），
所以可以拿它当"标准答案"，反查另一张图的识别与推理是否正确。

    python tests/probe_engine.py
"""
import os
import sys
import time

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cshelper.atlas import default_atlas                                  # noqa: E402
from cshelper.engine import analyze, obs_from_board, recommend, disp      # noqa: E402
from cshelper.layout import fit_zoom                                      # noqa: E402
from cshelper.recognize import BOOM, FLAGMINE, MINE, NUM, read_board       # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.environ.get("CS_GAME_DIR", os.path.join(os.path.dirname(ROOT), "complexweeper"))
LAB = os.path.join(ROOT, "_lab")
ATLAS = default_atlas(GAME)


def load(name, mode="complex"):
    img = Image.open(os.path.join(LAB, name))
    fit = fit_zoom(img.width, img.height)
    return read_board(img, ATLAS, fit[0], fit[1], fit[2], mode=mode)


def dump_totals(name):
    """读复扫雷 --dump 出来的真值（type_total）。"""
    p = os.path.join(LAB, name)
    if not os.path.exists(p):
        return None
    for line in open(p, encoding="utf-8"):
        if line.startswith("type_total"):
            return tuple(int(x) for x in line.split("=")[1].split())
    return None


def main():
    fails = []
    lose = load("demo-lose.png")
    w, h = lose.w, lose.h
    mine = [[0] * w for _ in range(h)]
    for r in range(h):
        for c in range(w):
            k = lose.cells[r][c]
            if k.kind in (MINE, BOOM, FLAGMINE) and 1 <= k.val <= 4:
                mine[r][c] = k.val
    cnt = tuple(sum(1 for r in range(h) for c in range(w) if mine[r][c] == t) for t in (1, 2, 3, 4))
    true_totals = dump_totals("demo-lose.txt")
    print("=" * 72)
    print("demo-lose 计雷器显示 =", lose.counters, " -> 按计数器反解四类总数 =", lose.totals())
    print("从揭示的雷贴图数出来的四类数量 =", cnt)
    print("--dump 真值 type_total =", true_totals,
          "（结算后'插在非雷上的旗'不携带类型，所以计数器反解在结算态会偏小，属正常）")
    if true_totals and cnt != true_totals:
        fails.append("揭示雷贴图数出的四类数量与真值不符")

    def clue(r, c):
        a = b = 0
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr or dc:
                    rr, cc = r + dr, c + dc
                    if 0 <= rr < h and 0 <= cc < w and mine[rr][cc]:
                        da, db = ((1, 0), (-1, 0), (0, 1), (0, -1))[mine[rr][cc] - 1]
                        a += da
                        b += db
        return disp(a, b, "complex")

    bad = checked = 0
    for r in range(h):
        for c in range(w):
            k = lose.cells[r][c]
            if k.kind == NUM:
                checked += 1
                if k.val != clue(r, c):
                    bad += 1
                    if bad <= 5:
                        print("  数字不符 (%d,%d): 识别 %s 真值 %s" % (r, c, k.val, clue(r, c)))
    print("demo-lose 已翻开数字格 %d 个，与真雷盘算出的线索不符 %d 个" % (checked, bad))
    if bad:
        fails.append("数字识别与真值不符")

    # ---------- 在 demo.png（未结束局面）上跑引擎 ----------
    mid = load("demo.png")
    obs = obs_from_board(mid)
    nopen = sum(1 for r in range(h) for c in range(w) if obs.value[r][c] is not None)
    true_mid = dump_totals("demo.txt")
    print()
    print("demo 局面：已翻开 %d 格，未翻开 %d 格，四类总数 %s（--dump 真值 %s）"
          % (nopen, h * w - nopen, obs.totals, true_mid))
    if true_mid and obs.totals != true_mid:
        fails.append("对局中按计数器反解的四类总数与真值不符")
    t0 = time.time()
    res = analyze(obs, verbose=True, time_budget=30)
    print("引擎：status=%s  用时 %.2fs  近似=%s  状态数=%d  %s"
          % (res.status, time.time() - t0, res.approx, res.n_states, res.msg))
    for i, ci in enumerate(res.comp_info):
        print("   分量%d: %d 格 / %d 约束 -> %s %s  %.2fs"
              % (i, ci["cells"], ci["cons"], ci["mode"], ci["info"], ci["sec"]))

    if res.status == "ok":
        for r in range(h):
            for c in range(w):
                if (r, c) not in res.prob:
                    continue
                p = res.prob[(r, c)]
                t = mine[r][c]
                if not res.exact.get((r, c), False):
                    continue          # MCMC 采样的格子不能当"必然"来判对错
                if t == 0 and p >= 1 - 1e-9:
                    fails.append("真值(非雷)被判成必然有雷 (%d,%d)" % (r, c))
                if t != 0 and p <= 1e-12:
                    fails.append("真值(雷)被判成必然无雷 (%d,%d)" % (r, c))
                if t != 0 and res.ptype[(r, c)][t - 1] <= 0:
                    fails.append("真值的雷型概率为 0 (%d,%d)" % (r, c))
        ex_cells = [rc for rc in res.prob if res.exact.get(rc)]
        safe = [rc for rc in ex_cells if res.prob[rc] <= 1e-12]
        sure = [rc for rc in ex_cells if res.prob[rc] >= 1 - 1e-12]
        ws = [rc for rc in safe if mine[rc[0]][rc[1]] != 0]
        wu = [rc for rc in sure if mine[rc[0]][rc[1]] == 0]
        print("引擎判定（仅精确分量 %d 格）：必然无雷 %d 个（真值是雷 %d 个）；"
              "必然有雷 %d 个（真值不是雷 %d 个）"
              % (len(ex_cells), len(safe), len(ws), len(sure), len(wu)))
        if ws or wu:
            fails.append("确定性判定与真值矛盾")

        # 近似分量：真值应当仍有非零概率（不能被采样的偏差完全排除）
        approx_bad = approx_n = 0
        for r in range(h):
            for c in range(w):
                if (r, c) in res.prob and mine[r][c] and not res.exact.get((r, c), False):
                    approx_n += 1
                    if res.ptype[(r, c)][mine[r][c] - 1] <= 0:
                        approx_bad += 1
        print("近似分量里真值雷型被排成 0 的数量 = %d / %d" % (approx_bad, approx_n))

        # 采样分量的"真值不能是 0 或 1"只做提示，不做失败判定
        sat = sum(1 for rc in res.prob if not res.exact.get(rc) and
                  (res.prob[rc] <= 1e-12 or res.prob[rc] >= 1 - 1e-12))
        print("近似分量里概率饱和到 0/1 的格子数 = %d" % sat)

        rec = recommend(obs, res)
        for r, c in rec['safe']:
            if mine[r][c] != 0:
                fails.append('Safety proof contradicts ground truth at %s' % ((r,c),))
        print()
        print("建议：")
        print("  可安全点开 %d 格 %s" % (len(rec["safe"]), sorted(rec["safe"])[:8]))
        print("  可安全展开（chord）%d 处 %s" % (len(rec["chords"]), [(a, len(b)) for a, b in rec["chords"]][:6]))
        if rec["flag_errors"]:
            print("  插错的旗：", rec["flag_errors"])
        if rec["guesses"]:
            print("  没有必安全格；最小概率候选：",
                  [("%s %.3f%s" % (rc, p, "" if ex else "*")) for rc, p, ex in rec["guesses"]])

    print()
    print("=" * 72)
    print("端到端验证：", "通过" if not fails else "失败 -> " + "; ".join(fails))
    return 0 if not fails else 1


if __name__ == "__main__":
    raise SystemExit(main())
