# -*- coding: utf-8 -*-
"""命令行入口。

    python -m cshelper.cli scan                     # 读当前窗口，打印棋盘
    python -m cshelper.cli solve                    # 读窗口 + 解 + 给建议
    python -m cshelper.cli solve --png shot.png     # 离线解一张截图
    python -m cshelper.cli screenshot --out a.png   # 存一张客户区截图（调试用）
    python -m cshelper.cli live --auto-safe          # 循环辅助；只自动点"可证明安全"的格
    python -m cshelper.cli live --overlay            # 在棋盘上叠概率热力图
"""
import argparse
import os
import sys
import time

from .atlas import default_atlas
from .capture import client_rect, find_window, grab_client
from .engine import analyze, obs_from_board, recommend
from .layout import PRESETS, Layout, fit_all, fit_zoom
from .recognize import read_board

DEF_GAME = os.environ.get("CS_GAME_DIR",
                          os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                       "..", "complexweeper"))


def get_atlas(args):
    return default_atlas(args.game_dir)


def load_board(args):
    """返回 (Board, 来源说明)。args.png 给定时读文件，否则抓窗口。"""
    atlas = get_atlas(args)
    if args.png:
        from PIL import Image
        img = Image.open(args.png)
        src = args.png
    else:
        hwnd = find_window(class_name=args.window_class)
        if not hwnd:
            raise SystemExit("没找到复扫雷窗口（类名 %s）。先打开游戏，或用 --png 解一张截图。"
                             % args.window_class)
        if args.zoom is None or args.w is None:
            cw, ch = client_rect(hwnd)
        img = grab_client(hwnd)
        src = "窗口 %s 客户区 %dx%d" % (hex(hwnd), img.width, img.height)
    if args.w and args.h and args.zoom:
        w, h, z = args.w, args.h, args.zoom
        return read_board(img, atlas, w, h, z, mode=args.mode), src
    preset = PRESETS.get(args.preset)
    cands = fit_all(img.width, img.height,
                    preset[0] if preset else args.w,
                    preset[1] if preset else args.h)
    if not cands:
        raise SystemExit("反解不出 (宽,高,缩放)：图 %dx%d。请用 --preset/--w --h --zoom 指定。"
                         % (img.width, img.height))
    if len(cands) == 1:
        w, h, z = cands[0]
        return read_board(img, atlas, w, h, z, mode=args.mode), src
    # 多个候选（小棋盘 + 小缩放时客户区一样宽）：按识别质量挑
    best, best_board = None, None
    for (ww, hh, zz) in cands:
        bb = read_board(img, atlas, ww, hh, zz, mode=args.mode)
        unk = sum(1 for r in bb.cells for c in r if c.kind == "unknown")
        score = (unk, bb.quality)
        if best is None or score < best:
            best, best_board = score, bb
    return best_board, src + "（候选 %s，按识别质量选中 %d×%d z=%d）" % (
        cands, best_board.w, best_board.h, best_board.z)


def cmd_scan(args):
    b, src = load_board(args)
    print("来源:", src)
    print("棋盘 %d×%d  缩放 %d  识别质量(平均误差) %.2f" % (b.w, b.h, b.z, b.quality))
    print("计雷器显示:", b.counters)
    print("四类雷总数(计数器+已插旗):", b.totals())
    print(b.render())
    unk = sum(1 for r in b.cells for c in r if c.kind == "unknown")
    if unk:
        print("!! 有 %d 格没认出来（贴图可能被遮挡或版本不一致）" % unk)
    return 0


def cmd_screenshot(args):
    hwnd = find_window(class_name=args.window_class)
    if not hwnd:
        raise SystemExit("没找到窗口")
    img = grab_client(hwnd)
    img.save(args.out)
    print("已保存 %s (%dx%d)" % (args.out, img.width, img.height))
    return 0


def cmd_solve(args):
    b, src = load_board(args)
    obs = obs_from_board(b)
    print("来源: %s" % src)
    print("棋盘 %d×%d  质量 %.2f  四类总数 %s" % (b.w, b.h, b.quality, obs.totals))
    t0 = time.time()
    res = analyze(obs, verbose=args.verbose, time_budget=args.budget)
    print("求解: status=%s  用时 %.2fs  近似=%s  %s" % (res.status, time.time() - t0,
                                                        res.approx, res.msg))
    for ci in res.comp_info:
        print("   分量 %d 格 / %d 约束 -> %s %s %.2fs"
              % (ci["cells"], ci["cons"], ci["mode"], ci["info"], ci["sec"]))
    rec = recommend(obs, res)
    print_board_hint(b, obs, res)
    print()
    if rec["safe"]:
        print("可以安全点开 %d 格（已证明无雷）：%s" % (len(rec["safe"]), rec["safe"]))
    if rec["chords"]:
        print("可以安全展开（chord）%d 处：%s" % (len(rec["chords"]), rec["chords"]))
    if rec["flag_errors"]:
        print("!! 插错/多余的旗：", rec["flag_errors"])
    if rec["guesses"]:
        print("没有可证明安全的格子，最小概率候选（星号 = 采样近似）：")
        for rc, p, ex in rec["guesses"]:
            print("   %s  P(雷)=%.4f%s" % (rc, p, "" if ex else "  *"))
    if rec["approx_cells"]:
        print("注意：%d 格落在采样近似分量里，概率仅供参考。" % len(rec["approx_cells"]))
    return 0


def print_board_hint(b, obs, res):
    """打印带概率的棋盘（只显示未翻开格的概率）。"""
    for r in range(b.h):
        row = []
        for c in range(b.w):
            k = b.cells[r][c]
            if k.kind == "num":
                row.append("%4s" % k.val)
            elif k.kind == "blank":
                row.append("   .")
            elif k.kind in ("flag", "flagmine"):
                row.append("  f%d" % k.val)
            elif k.kind == "closed" and (r, c) in res.prob:
                p = res.prob[(r, c)]
                mark = "" if res.exact.get((r, c), False) else "*"
                row.append("%3d%s" % (round(p * 100), mark))
            else:
                row.append("  ??")
        print("".join(row))


def cmd_live(args):
    from .capture import click
    hwnd = find_window(class_name=args.window_class) if not args.png else None
    if not args.png and not hwnd:
        raise SystemExit("没找到复扫雷窗口")
    overlay = None
    if args.overlay:
        from .overlay import Overlay
        overlay = Overlay(hwnd)
    clicks_done = 0
    try:
        while True:
            b, src = load_board(args)
            obs = obs_from_board(b)
            res = analyze(obs, time_budget=args.budget)
            rec = recommend(obs, res)
            os.system("cls" if os.name == "nt" else "clear")
            print("四类总数 %s   求解 %s  近似 %s" % (obs.totals, res.status, res.approx))
            print_board_hint(b, obs, res)
            if rec["safe"]:
                print("可安全点开 %d 格" % len(rec["safe"]))
            if rec["chords"]:
                print("可安全展开 %d 处" % len(rec["chords"]))
            if rec["flag_errors"]:
                print("!! 旗插错了：", rec["flag_errors"])
            if rec["guesses"] and not rec["safe"]:
                print("只能猜：", [(rc, round(p, 3)) for rc, p, _ in rec["guesses"]])
            if overlay:
                overlay.update(b, obs, res)
            if args.auto_safe and hwnd:
                acted = False
                for rc in rec["safe"]:
                    x, y, cw, ch = Layout(b.w, b.h, b.z).cell_rect(*rc)
                    click(hwnd, x + cw // 2, y + ch // 2, "left")
                    clicks_done += 1
                    acted = True
                    time.sleep(args.delay)
                if acted:
                    time.sleep(args.settle)
                    continue
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n已停止（本轮自动点了 %d 格）" % clicks_done)
    finally:
        if overlay:
            overlay.close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="cshelper", description="复扫雷 AI 助手（辅助，不改游戏）")
    p.add_argument("cmd", choices=["scan", "solve", "live", "screenshot"])
    p.add_argument("--png", help="离线解一张截图")
    p.add_argument("--out", default="shot.png", help="screenshot 的输出路径")
    p.add_argument("--window-class", default="ComplexSweeperMain")
    p.add_argument("--game-dir", default=os.path.normpath(DEF_GAME),
                   help="复扫雷仓库目录（含 素材/图集.png）")
    p.add_argument("--mode", default="complex", choices=["complex", "hyper"])
    p.add_argument("--preset", default=None, choices=list(PRESETS))
    p.add_argument("--w", type=int, default=None)
    p.add_argument("--h", type=int, default=None)
    p.add_argument("--zoom", type=int, default=None, choices=[1, 2, 3])
    p.add_argument("--budget", type=float, default=20.0)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--overlay", action="store_true", help="live: 叠概率热力图")
    p.add_argument("--auto-safe", action="store_true", help="live: 自动点开已证明安全的格")
    p.add_argument("--interval", type=float, default=1.5)
    p.add_argument("--delay", type=float, default=0.05)
    p.add_argument("--settle", type=float, default=0.4)
    args = p.parse_args(argv)
    return {"scan": cmd_scan, "solve": cmd_solve, "live": cmd_live,
            "screenshot": cmd_screenshot}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
