# -*- coding: utf-8 -*-
"""离线自检：用复扫雷 EXE 的 --shot 渲染图验证识别管线。

    python tests/probe_offline.py
"""
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cshelper.atlas import default_atlas                      # noqa: E402
from cshelper.layout import fit_zoom                          # noqa: E402
from cshelper.recognize import read_board                     # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GAME = os.environ.get("CS_GAME_DIR",
                      os.path.join(os.path.dirname(ROOT), "complexweeper"))
LAB = os.path.join(ROOT, "_lab")

CASES = [
    ("z1.png", "complex", 16, 16, 1),
    ("z2.png", "complex", 16, 16, 2),
    ("z3.png", "complex", 16, 16, 3),
    ("hyper.png", "hyper", 16, 16, 2),
]


def main():
    atlas = default_atlas(GAME)
    ok_all = True
    for fname, mode, w, h, z in CASES:
        path = os.path.join(LAB, fname)
        if not os.path.exists(path):
            # 缺夹具必须算失败：跳过等于没验证，不能让脚本打印"通过"。
            print("!! 缺夹具（不能跳过）:", path)
            ok_all = False
            continue
        img = Image.open(path)
        fit = fit_zoom(img.width, img.height)          # 不给 w/h，纯自动反解
        print("=" * 72)
        print("%s  %dx%d 像素  真值 (w=%d,h=%d,z=%d)  自动反解 = %s"
              % (fname, img.width, img.height, w, h, z, fit))
        if fit is None:
            print("  !! 反解缩放失败")
            ok_all = False
            continue
        ww, hh, zz = fit
        if (ww, hh, zz) != (w, h, z):
            print("  !! 反解结果与真值不符")
            ok_all = False
        b = read_board(img, atlas, ww, hh, zz, mode=mode)
        unknown = sum(1 for r in b.cells for c in r if c.kind == "unknown")
        print("  识别质量（平均匹配误差）= %.2f  未知格 = %d" % (b.quality, unknown))
        print("  计雷器显示 = %s   各面板格数 = %s" % (b.counters, b.counter_cells))
        print("  四类雷总数 = %s" % (b.totals(),))
        print(b.render())
        if unknown:
            ok_all = False
    print("=" * 72)
    print("离线识别自检:", "通过" if ok_all else "有未知格/失败")
    return 0 if ok_all else 1


if __name__ == "__main__":
    raise SystemExit(main())
