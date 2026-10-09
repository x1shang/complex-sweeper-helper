# -*- coding: utf-8 -*-
"""复扫雷 AI 助手（辅助，不修改游戏本体）。"""
__version__ = "0.1.0"

# Optional project-local dependencies installed by setup.bat.
import sys
from pathlib import Path
_deps = Path(__file__).resolve().parent.parent / '.deps'
if _deps.is_dir():
    sys.path.insert(0, str(_deps))
