# -*- coding: utf-8 -*-
"""概率热力图覆盖层（Tkinter，零额外依赖）。

用 -transparentcolor 做"颜色键"透明：这些像素不但看不见，鼠标点击也会穿透，
所以覆盖层不会挡住游戏。窗口位置每次刷新时重新贴合客户区。
"""
import tkinter as tk

from .capture import client_origin
from .layout import Layout

MAGIC = "#ff00ff"          # 透明键色（游戏里不会出现的品红）


def color_for(p):
    if p <= 1e-12:
        return "#00c000"   # 已证明安全
    if p >= 1 - 1e-12:
        return "#d00000"   # 已证明有雷
    r = int(255 * min(1.0, p * 2))
    g = int(200 * (1 - min(1.0, p * 1.6)))
    return "#%02x%02x00" % (r, max(g, 0))


class Overlay:
    def __init__(self, hwnd):
        self.hwnd = hwnd
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:
            self.root.attributes("-transparentcolor", MAGIC)
        except tk.TclError:
            pass
        self.root.configure(bg=MAGIC)
        self.canvas = tk.Canvas(self.root, highlightthickness=0, bd=0, bg=MAGIC)
        self.canvas.pack(fill="both", expand=True)
        self.root.update()

    def update(self, board, obs, res):
        ox, oy = client_origin(self.hwnd)
        self.root.geometry("%dx%d+%d+%d" % (self.root.winfo_width() or 10,
                                            self.root.winfo_height() or 10, ox, oy))
        self.root.geometry("+%d+%d" % (ox, oy))
        self.canvas.delete("all")
        lay = Layout(board.w, board.h, board.z)
        self.root.geometry("%dx%d+%d+%d" % (lay.client_w, lay.client_h, ox, oy))
        for r in range(board.h):
            for c in range(board.w):
                k = board.cells[r][c]
                if k.kind != "closed":
                    continue
                p = res.prob.get((r, c))
                if p is None:
                    continue
                x, y, cw, ch = lay.cell_rect(r, c)
                col = color_for(p)
                self.canvas.create_rectangle(x + 1, y + 1, x + cw - 2, y + ch - 2,
                                             outline=col, width=max(1, board.z))
                if board.z >= 2 and cw >= 32:
                    self.canvas.create_text(x + cw // 2, y + ch // 2, text="%d" % round(p * 100),
                                            fill=col, font=("Consolas", max(7, 6 * board.z // 2)))
        self.root.update()

    def close(self):
        try:
            self.root.destroy()
        except tk.TclError:
            pass
