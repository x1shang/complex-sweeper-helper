# -*- coding: utf-8 -*-
"""图集访问：从 素材/图集.json + 图集.png 取任意槽位的像素。

复扫雷的素材是纯像素画，且程序用 StretchBlt(COLORONCOLOR) 做整数倍放大，
所以在 zoom=1/2/3 下屏幕上的贴图就是原图的最近邻放大。
"""
import json
import os

import numpy as np
from PIL import Image


class Atlas:
    def __init__(self, json_path, png_path):
        with open(json_path, encoding="utf-8") as f:
            meta = json.load(f)
        self.meta = meta
        self.img = Image.open(png_path).convert("RGB")
        self.slots = {s["name"]: (s["x"], s["y"], s["w"], s["h"]) for s in meta["slots"]}
        self._cache = {}

    def has(self, name):
        return name in self.slots

    def rgb(self, name, z=1):
        """取槽位像素（放大 z 倍，最近邻）。"""
        key = (name, z)
        if key in self._cache:
            return self._cache[key]
        if name not in self.slots:
            raise KeyError(name)
        x, y, w, h = self.slots[name]
        im = self.img.crop((x, y, x + w, y + h))
        if z != 1:
            im = im.resize((w * z, h * z), Image.NEAREST)
        a = np.asarray(im, dtype=np.int16)
        self._cache[key] = a
        return a


# 圆复数模式：24 个可达显示值，贴图名就是 num_<值>
def complex_names():
    return ["num_%d" % d for d in
            (0, 1, 2, 4, 5, 8, 9, 10, 13, 16, 17, 18, 20, 25, 26, 29, 32, 34, 36, 37, 40, 49, 50, 64)]


# 闵可夫斯基模式：39 个可达显示值 D = a^2-b^2（含 0）。
# 正数里只有 3/7/12/15/21/24/35/48 不在圆复数模式的 24 个值里，所以那 8 个才是独立的 hnum_*；
# 其余正数复用 num_*；负数一律用 hnum_<|D|>_i（贴图里带 i 单位）。
HYPER_POS = (1, 3, 4, 5, 7, 8, 9, 12, 15, 16, 21, 24, 25, 32, 35, 36, 48, 49, 64)
HYPER_ONLY = (3, 7, 12, 15, 21, 24, 35, 48)


def hyper_names():
    names = {}
    for d in HYPER_POS:
        names[d] = ("hnum_%d" % d) if d in HYPER_ONLY else ("num_%d" % d)
    for d in HYPER_POS:
        names[-d] = "hnum_%d_i" % d
    names[0] = "num_0"
    return names


def default_atlas(root):
    return Atlas(os.path.join(root, "素材", "图集.json"),
                 os.path.join(root, "素材", "图集.png"))
