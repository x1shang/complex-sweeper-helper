# 第三方组件

## 1. cshelper/vendor/wyc —— 界面外壳、背景资源、图标

来自 [wangyuanchuan2022/minesweeper_help](https://github.com/wangyuanchuan2022/minesweeper_help)（2026-10-09 快照），**MIT**，
`Copyright (c) wangyuanchuan2022`。本项目未修改其许可声明。

| 本仓库文件 | 上游路径 | 改动 |
|---|---|---|
| `vendor/wyc/window.py` | `ui/window.py` | `bg_rc` 改为包内相对导入；图标路径改用 `Path(__file__)` 定位 |
| `vendor/wyc/bg_rc.py` | `ui/bg_rc.py` | 无（逐字节相同） |
| `vendor/wyc/icons/*.png`、`icon.ico`（13 个） | `icons/*` | 无（逐字节相同） |

上游生成器标注（`pyuic5`、Resource Compiler）原样保留。

`bg_rc.py` 是约 10 MB 的 Qt 资源生成物，通常不入库。这里保留是因为上游仓库已停止维护，
而它是界面背景图的唯一来源（重新生成需要上游的 `ui/bg.qrc` 与 `background_*.bmp`）。

## 2. Yueqing-Chen/complexweeper-A-minesweeper-game —— 游戏本体（GPL-3.0）

- 本仓库**不包含、不链接、不嵌入**该仓库的任何代码或素材，也不随本项目分发。
- 运行期只从你本地的游戏目录读取 `素材/图集.json` 与 `素材/图集.png`，并通过 Win32 窗口消息读取客户区截图。
- 因此两者是彼此独立的程序，本项目不构成其衍生作品，可以采用 MIT。**一旦把游戏代码或素材搬进本仓库，此结论立即失效。**
- 原始扫雷图像素材的权利属于 Microsoft。

## 3. 运行期依赖与打包

`numpy`、`Pillow`、`z3-solver` 以源码形式使用，不受打包影响。**注意 `PyQt5` 采用 GPL-3.0（或商业许可）**：
以源码形式发布本项目不受影响；若日后打包独立 EXE 分发，需一并遵守 PyQt5 的许可条款。
