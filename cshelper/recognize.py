# -*- coding: utf-8 -*-
"""识别：客户区截图 -> 棋盘状态 + 四个计雷器的数值。

坐标全部来自 layout.Layout（= main.zig 的 layout()），
贴图全部来自 素材/图集.png，所以是"按已知几何精确取像素 + 最近邻匹配"，
不是模糊找图。
"""
import numpy as np

from .atlas import complex_names, hyper_names

# 格子状态
CLOSED, BLANK, NUM, FLAG, MINE, BOOM, UNKNOWN = "closed", "blank", "num", "flag", "mine", "boom", "unknown"
# 结算时才出现：插在雷上的旗（right_*/wrong_* 贴图）。它同时是"旗"和"雷"，
# 漏掉这一条会让"按计数器反推四类雷总数"少数几个（插旗的雷不再算成旗）。
FLAGMINE = "flagmine"


class Cell:
    __slots__ = ("kind", "val")

    def __init__(self, kind, val=0):
        self.kind, self.val = kind, val

    def __repr__(self):
        return "%s%s" % (self.kind, "" if self.val in (0, None) else ":%s" % self.val)


def _candidates(atlas, z, mode):
    """(名字, 像素数组, kind, val) 列表。"""
    out = []

    def add(name, kind, val):
        if atlas.has(name):
            out.append((name, atlas.rgb(name, z), kind, val))

    add("closed", CLOSED, 0)
    add("blank", BLANK, 0)
    if mode == "complex":
        for d in (0, 1, 2, 4, 5, 8, 9, 10, 13, 16, 17, 18, 20, 25, 26, 29, 32, 34, 36, 37, 40, 49, 50, 64):
            add("num_%d" % d, NUM, d)
    else:
        for d, nm in sorted(hyper_names().items()):
            add(nm, NUM, d)
    for t in (1, 2, 3, 4):
        add("flag_%d" % t, FLAG, t)
        add("mine_%d" % t, MINE, t)
        add("boom_%d" % t, BOOM, t)
        add("right_%d" % t, FLAGMINE, t)
        add("wrong_%d" % t, FLAGMINE, t)
        add("rightflag_%d" % t, FLAG, t)
        add("wrongflag_%d" % t, FLAG, t)
        if mode == "hyper":
            for pre, kind in (("hflag", FLAG), ("hmine", MINE), ("hboom", BOOM),
                              ("hright", FLAGMINE), ("hwrong", FLAGMINE),
                              ("hrightflag", FLAG), ("hwrongflag", FLAG)):
                add("%s_%d" % (pre, t), kind, t)
    add("wrongblank", "wrongblank", 0)
    return out


LED_NAMES = ["led_%d" % i for i in range(10)] + ["led_minus", "led_blank", "led_i", "led_j"]


def _led_candidates(atlas, z):
    return [(nm, atlas.rgb(nm, z)) for nm in LED_NAMES if atlas.has(nm)]


def _classify(patch, cands, thresh):
    """返回 (kind, val, name, 平均绝对差)。"""
    v = patch.astype(np.int16)
    best = (None, 0, None, 1e9)
    for name, arr, kind, val in cands:
        if arr.shape != v.shape:
            continue
        d = float(np.abs(arr - v).mean())
        if d < best[3]:
            best = (kind, val, name, d)
    if best[3] > thresh:
        return (UNKNOWN, 0, best[2], best[3])
    return best


class Board:
    def __init__(self, w, h, z, mode):
        self.w, self.h, self.z, self.mode = w, h, z, mode
        self.cells = [[Cell(UNKNOWN) for _ in range(w)] for _ in range(h)]
        self.counters = None      # 四个计雷器显示值（未标数），未开局为 None
        self.counter_cells = ()   # 每块面板占几格（调试用）
        self.quality = 0.0        # 平均匹配误差
        self.face = None
        self.max_error = 0.0

    # ---- 便捷访问 ----
    def flags_on_board(self):
        f = [0, 0, 0, 0]
        for row in self.cells:
            for c in row:
                if c.kind in (FLAG, FLAGMINE) and 1 <= c.val <= 4:
                    f[c.val - 1] += 1
        return f

    def totals(self):
        """四类雷总数 = 计雷器显示值 + 棋盘上已插的旗。

        注意符号：游戏里第 2、4 个计雷器（负实雷 / 负虚雷）显示的是
        counterValue = -unmarked（main.zig:149-155），
        所以要把显示值取反才是"还没标的数量"。
        """
        if self.counters is None:
            return None
        f = self.flags_on_board()
        unmarked = [self.counters[0], -self.counters[1],
                    self.counters[2], -self.counters[3]]
        return tuple(unmarked[i] + f[i] for i in range(4))

    def render(self):
        """打印成文本：未开 = #，空白 = .，数字 = 值，旗 = a/b/c/d，雷 = A/B/C/D"""
        fs = " abcd"
        ms = " ABCD"
        out = []
        for r in range(self.h):
            row = []
            for c in range(self.w):
                cell = self.cells[r][c]
                if cell.kind == CLOSED:
                    row.append("  #")
                elif cell.kind == BLANK:
                    row.append("  .")
                elif cell.kind == NUM:
                    row.append("%3s" % cell.val)
                elif cell.kind == FLAG:
                    row.append("%3s" % (fs[cell.val] if cell.val else "?"))
                elif cell.kind in (MINE, BOOM):
                    row.append("%3s" % ms[cell.val].lower())
                elif cell.kind == FLAGMINE:
                    row.append("%3s" % (fs[cell.val].upper() if cell.val else "?"))
                else:
                    row.append("  ?")
            out.append("".join(row))
        return "\n".join(out)


def read_board(img, atlas, w, h, z, mode="complex", thresh=40.0, counter_thresh=40.0):
    from .layout import Layout
    lay = Layout(w, h, z)
    arr = np.asarray(img.convert("RGB"), dtype=np.int16)
    b = Board(w, h, z, mode)
    cands = _candidates(atlas, z, mode)
    tot = 0.0
    n = 0
    for r in range(h):
        for c in range(w):
            x, y, cw, ch = lay.cell_rect(r, c)
            patch = arr[y:y + ch, x:x + cw]
            if patch.shape[:2] != (ch, cw):
                b.cells[r][c] = Cell(UNKNOWN)
                continue
            kind, val, name, d = _classify(patch, cands, thresh)
            b.cells[r][c] = Cell(kind, val)
            b.max_error = max(b.max_error, d)
            tot += d
            n += 1
    b.quality = tot / max(n, 1)
    b.counters, b.counter_cells = read_counters(arr, atlas, lay, counter_thresh, mode)
    # Locate the face exactly as main.zig faceLeft/faceTop do.
    size = 24*z
    end = lay.counters_x + lay._counter_width(z, max(4, max(b.counter_cells, default=4)))
    timer = lay.header_x + lay.header_w - 4*z - lay._timer_width(z)
    fx = max(lay.header_x + lay.header_w//2 - size//2, end + 6*z)
    fx = max(lay.header_x, min(fx, timer - 6*z - size)) - 2
    fy = lay.header_y + (lay.header_h-size)//2 - 2
    faces = [(name, atlas.rgb(name,z), name, 0) for name in
             ('face_normal','face_down','face_scan','face_dead','face_win') if atlas.has(name)]
    if faces:
        b.face = _classify(arr[fy:fy+size,fx:fx+size],faces,5.0)[0]
    return b


def read_counters(arr, atlas, lay, thresh=40.0, mode='complex'):
    """读四个计雷器。返回 (值列表 或 None, 每块占几格)。"""
    z = lay.z
    led = _led_candidates(atlas, z)
    lw, lh = 13 * z, 23 * z
    led_x = lay.counters_x + z + 2 * z + 16 * z
    vals, cells_used = [], []
    for idx in range(4):
        _, row_y, _ = lay.counter_row(idx)
        led_y = row_y + (26 * z - 23 * z) // 2
        glyphs = []
        for k in range(6):
            x = led_x + k * lw
            patch = arr[led_y:led_y + lh, x:x + lw]
            if patch.shape[:2] != (lh, lw):
                break
            best, bd = None, 1e9
            for name, carr in led:
                if carr.shape != patch.shape:
                    continue
                d = float(np.abs(carr - patch).mean())
                if d < bd:
                    best, bd = name, d
            if best is None or bd > thresh:
                break
            if best == "led_blank":
                break
            glyphs.append(best)
        cells_used.append(len(glyphs))
        expected_unit = 'led_i' if mode == 'complex' else 'led_j'
        valid = len(glyphs) >= 4
        if idx >= 2:
            valid = valid and glyphs[-1] == expected_unit
        else:
            valid = valid and all(g[4:].isdigit() for g in glyphs[(1 if glyphs and glyphs[0] == 'led_minus' else 0):])
        vals.append(_parse_led(glyphs) if valid else None)
    if any(v is None for v in vals):
        return None, tuple(cells_used)
    return tuple(vals), tuple(cells_used)


def _parse_led(glyphs):
    if not glyphs:
        return None
    neg = False
    i = 0
    if glyphs[0] == "led_minus":
        neg = True
        i = 1
    digits = ""
    while i < len(glyphs) and glyphs[i].startswith("led_") and glyphs[i][4:].isdigit():
        digits += glyphs[i][4:]
        i += 1
    unit = glyphs[i] if i < len(glyphs) else None
    if not digits:
        return None
    v = int(digits)
    if neg:
        v = -v
    return v
