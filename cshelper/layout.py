# -*- coding: utf-8 -*-
"""界面几何：把 main.zig 的 layout() 逐行抄成 Python。

复扫雷客户区的一切坐标都由 (棋盘宽高 w,h, 缩放 z) 唯一决定，
所以只要拿到客户区尺寸，就能反解出 z（甚至 w/h），再算出每个格子和
四个计数器的精确像素矩形——比"找图定位"稳得多。
"""


class Layout:
    def __init__(self, w, h, z):
        self.w, self.h, self.z = w, h, z
        frame, pad, gap, box = 3 * z, 6 * z, 6 * z, 3 * z
        cell = 16 * z
        self.frame, self.pad, self.gap, self.box, self.cell = frame, pad, gap, box, cell
        board_w = w * cell + 2 * box
        hw = self._header_content_width(z)
        inner_w = max(board_w, hw)
        self.inner_w, self.board_w, self.hw_min = inner_w, board_w, hw
        self.client_w = inner_w + 2 * (frame + pad)
        counters_h = 4 * (26 * z) + 3 * (2 * z)
        self.header_h = 2 * (2 * z) + 2 * (3 * z) + counters_h
        self.client_h = 2 * (frame + pad) + self.header_h + gap + h * cell + 2 * box
        self.board_x = frame + pad + (inner_w - board_w) // 2 + box
        self.board_y = frame + pad + self.header_h + gap + box
        self.header_x = frame + pad
        self.header_y = frame + pad
        self.header_w = inner_w

    # ---- 与 main.zig 对应的小函数 ----
    @staticmethod
    def _counter_width(z, digits):
        return 16 * z + 2 * z + digits * 13 * z + 2 * z

    @staticmethod
    def _timer_width(z):
        return 4 * 13 * z + 2 * z

    def _header_content_width(self, z):
        col = self._counter_width(z, 4)
        return 4 * z + col + 8 * z + 24 * z + 8 * z + self._timer_width(z) + 4 * z

    @property
    def counters_x(self):
        return self.header_x + 4 * self.z

    @property
    def counters_y(self):
        return self.header_y + 2 * self.z + 3 * self.z

    def counter_row(self, idx):
        """第 idx(0..3) 个计雷器的行矩形 (x, y, h)。"""
        z = self.z
        y = self.counters_y + idx * (26 * z + 2 * z)
        return self.counters_x, y, 26 * z

    def cell_rect(self, r, c):
        z = self.z
        return (self.board_x + c * 16 * z, self.board_y + r * 16 * z, 16 * z, 16 * z)

    def cell_center(self, r, c):
        x, y, w, h = self.cell_rect(r, c)
        return x + w // 2, y + h // 2


def fit_all(client_w, client_h, w=None, h=None):
    """列出所有与客户区尺寸相容的 (w, h, z)。

    高度永远能唯一定出 (h, z)；宽度在"棋盘比表头窄"时有多个解
    （例如 9×9 与 10×9 在 z=1 下客户区一样宽），所以要靠识别质量再筛一遍。
    """
    out = []
    for z in (1, 2, 3):
        dh = client_h - 150 * z
        if dh <= 0 or dh % (16 * z):
            continue
        hh = dh // (16 * z)
        if not (9 <= hh <= 30):
            continue
        if h is not None and hh != h:
            continue
        if w is not None:
            if Layout(w, hh, z).client_w == client_w:
                out.append((w, hh, z))
            continue
        for ww in range(9, 41):
            if Layout(ww, hh, z).client_w == client_w:
                out.append((ww, hh, z))
    return out


def fit_zoom(client_w, client_h, w=None, h=None):
    """反解缩放级别，返回 (w, h, z) 或 None（只取第一个解）。"""
    c = fit_all(client_w, client_h, w, h)
    return c[0] if c else None


PRESETS = {"beginner": (9, 9), "intermediate": (16, 16), "expert": (30, 16)}
