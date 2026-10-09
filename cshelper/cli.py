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
from .engine import obs_from_board, recommend
from .solver import analyze
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
    from .controller import board_status
    state = board_status(b)
    if state != 'playing':
        print('棋盘状态:', state, '（不生成对局动作）')
        return 1 if state == 'unreadable' else 0
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
        print("没有可证明安全的格子，最小概率候选（星号 = 模型估计）：")
        for rc, p, ex in rec["guesses"]:
            print("   %s  P(雷)=%.4f%s" % (rc, p, "" if ex else "  *"))
    if rec["approx_cells"]:
        print("注意：%d 格落在模型估计分量里，概率仅供参考。" % len(rec["approx_cells"]))
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
    from .controller import WindowSession, board_status, choose_actions, fingerprint
    if args.png and (args.auto_safe or args.auto):
        raise SystemExit("离线截图不能自动点击")
    if args.auto_safe and args.auto:
        raise SystemExit("请选择 --auto 或 --auto-safe 之一")
    session = None if args.png else WindowSession(args)
    overlay = None
    if args.overlay and session:
        from .overlay import Overlay
        overlay = Overlay(session.hwnd)
    last, repeated, clicks = None, 0, 0
    try:
        while True:
            b = session.read() if session else load_board(args)[0]
            state = board_status(b)
            res = analyze(obs_from_board(b),time_budget=args.budget) if state == 'playing' else None
            print("状态:",state,"求解:",res.msg if res else "—",flush=True)
            if res:
                print_board_hint(b,res.obs,res)
                if overlay:
                    overlay.update(b,res.obs,res)
            if state in ('won','lost','finished','unreadable'):
                break
            if args.auto_safe or args.auto:
                actions = choose_actions(b,res,args.auto)
                if not actions:
                    print("没有可执行动作，停止")
                    break
                key = fingerprint(b)
                repeated = repeated+1 if key == last else 0
                last = key
                if repeated >= 3:
                    print("点击后棋盘未改变，停止")
                    break
                sent = session.act_batch(b,actions)
                clicks += sent
                print("本轮点击 %d 次，目标 %d 格" % (sent,len(actions)),flush=True)
                time.sleep(args.settle)
            else:
                if args.png:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("已停止，自动点击 %d 次" % clicks)
    finally:
        if overlay:
            overlay.close()
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="cshelper", description="复扫雷 AI 助手（辅助，不改游戏）")
    p.add_argument("cmd", choices=["scan", "solve", "live", "screenshot", "gui"])
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
    p.add_argument("--auto", action="store_true", help="live: 全自动开局、安全点击和猜测")
    args = p.parse_args(argv)
    if args.budget <= 0 or min(args.interval,args.delay,args.settle) < 0:
        p.error('预算必须大于 0，等待间隔不能为负数')
    if args.cmd == "gui":
        from .gui import main as gui_main
        return gui_main()
    return {"scan": cmd_scan, "solve": cmd_solve, "live": cmd_live,
            "screenshot": cmd_screenshot}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
