# 复扫雷 AI 助手

[复扫雷](https://github.com/Yueqing-Chen/complexweeper-A-minesweeper-game)的外部助手：识别窗口 → 证明安全并点击 → 无安全格时按估计风险猜测 → 胜负后停止。**不修改游戏本体。**

## 上游路标

| 项目 | 仓库 | 许可 | 与本项目的关系 |
|---|---|---|---|
| 游戏本体 | [Yueqing-Chen/complexweeper-A-minesweeper-game](https://github.com/Yueqing-Chen/complexweeper-A-minesweeper-game) | GPL-3.0 | 本助手服务的对象。不随本项目分发 |
| 界面外壳 | [wangyuanchuan2022/minesweeper_help](https://github.com/wangyuanchuan2022/minesweeper_help) | MIT | `cshelper/vendor/wyc/` 的来源。上游已停止维护，本项目保留快照 |
| 本仓库 | [x1shang/complex-sweeper-helper](https://github.com/x1shang/complex-sweeper-helper) | MIT | 见 [授权](#授权) |

## 启动

Windows + Python 3.10 或以上。先装一次依赖：

```powershell
setup.bat                                 # 装到项目内的 .deps
# 或：python -m pip install -r requirements.txt
```

装好后双击 `launch.bat`，或：

```powershell
python -m cshelper.gui
```

1. 在“设置”中指定含 `素材/图集.json`、`素材/图集.png` 的复扫雷目录。默认 `../complexweeper`，也可用环境变量 `CS_GAME_DIR`。
2. 选择与游戏一致的 `complex`（圆复数）或 `hyper`（闵可夫斯基）模式。棋盘尺寸可自动识别；窄棋盘有歧义时手动指定难度或宽高。
3. 点“启动复扫雷”，或自行运行游戏。优先使用 `_lab/complexweeper.exe`，其次在设置目录中寻找游戏程序。
4. “自动”完成一局；“帮助人类”显示概率图；“截图帮助”读取客户区 PNG；“点击确定方格”只执行已证明安全的动作，遇到需要猜测时停止。
5. “停止”或 Esc 取消。求解在工作线程中运行，停止后不再排队点击。

自动模式允许猜雷，**不保证通关或胜率**。概率旁的 `*` 表示有界模型估计，不是精确概率；蓝框格经过安全证明。

## 命令行

```powershell
python -m cshelper.cli scan
python -m cshelper.cli solve --png _lab/demo.png --budget 5
python -m cshelper.cli live --auto --preset beginner --budget 5
python -m cshelper.cli live --auto --mode hyper --preset beginner
python -m cshelper.cli live --auto-safe
python -m cshelper.cli live --overlay
python -m cshelper.cli screenshot --out board.png
```

通用参数：`--game-dir`、`--mode complex|hyper`、`--preset beginner|intermediate|expert`、`--w/--h`、`--zoom 1|2|3`、`--budget 秒`。离线截图不能启用自动点击；命令行 Ctrl+C 停止。

## 内核

入口 `engine.analyze()` 转到 `solver.py`，用 Z3 求解布尔与整数约束。

- 每格五态：空、+1、−1、+i、−i。双曲模式用 +j、−j，数值约束改为 `a²−b²`。
- 已开数字的内部值是模长的平方 D。空白严格要求邻居全空；数字 0 要求邻居存在雷，不能与空白混同。
- 四类全局总数 = LED 剩余数量 + 对应旗帜数量。旗不作为真雷约束，允许发现错旗。
- 小局面枚举全部边界赋值；无约束格用整数多项式组合数积分，避免枚举自由区域与浮点溢出。
- 大局面受时间与 2048 个模型上限约束，其频率仅用于猜测排序，并用少量全局先验平滑，避免把未观察到的状态当成不可能。
- 安全证明单独查询“这些候选格中至少一个是雷”是否不可满足。只有 UNSAT 或完整计数的零支持才产生安全格；超时、近似 0、总数矛盾都不会生成安全证明。
- 每轮先翻开所有已证明安全的格子，再统一重新求解。

`engine.analyze_legacy()` 是早期的枚举/MCMC 实现，**当前没有任何调用者**，自动对局不使用。

## 代码结构

| 文件 | 职责 |
|---|---|
| `controller.py` | GUI 与 CLI 共用的状态机、动作选择、窗口会话 |
| `capture.py` | Win64 句柄声明、PrintWindow 客户区截图、向固定 HWND 发送鼠标消息（不移动系统鼠标） |
| `recognize.py` / `atlas.py` / `layout.py` | 图集读取、贴图识别、棋盘尺寸与缩放反解 |
| `solver.py` / `engine.py` | Z3 求解与五态约束模型 |
| `gui.py` / `cli.py` / `overlay.py` | Qt 界面（含原外壳适配）、命令行、概率热力图覆盖层 |
| `vendor/wyc/` | 界面外壳、背景资源、图标（第三方，见 `THIRD_PARTY.md`） |

批次开始前核对棋盘；批内允许正常翻开与空白展开，线索、总数或尺寸变化则丢弃剩余动作；窗口关闭/最小化、识别异常、点击无变化都会停止。

## 验证

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -p "test_*.py" -v
```

覆盖：与独立五态穷举的逐格逐类型概率比对、有界模型路径的安全证明、空白与数字 0、错旗、取消、1200 格自由区域组合权重、动作状态门控。

以下脚本需要本地游戏与不入库的 `_lab/` 夹具，只能在开发机上运行，不作为对外证据：

```powershell
python tests/probe_offline.py                                  # 截图识别回归
python tests/probe_engine.py                                   # 识别→引擎→与真值对照
python tests/probe_autoplay.py --exe _lab/complexweeper.exe    # 真实窗口自动对局（先关闭已有游戏）
```

## 已知限制

- 功能回归，不是胜率统计。复杂中高级局面的估计仍有偏差；预算不足时可能找不到合法模型而停止。
- 暂未实现：最优胜率搜索、连续多局刷局、独立 EXE 打包。
- 识别依赖游戏的固定图集；游戏改版素材后需重新核对图集坐标。
- 仅支持 Windows（`capture.py` 直接调用 `user32`）。

游戏与图集是外部输入，不随本项目分发；`_lab/` 为本地验证产物，已被 `.gitignore` 排除。

## 授权

本项目采用 **MIT**，见 `LICENSE`。`cshelper/vendor/wyc/*` 来自 minesweeper_help（MIT），版权归原作者。

复扫雷本体采用 GPL-3.0。本项目**不含、不链接、不嵌入**其代码与素材，运行期只从你本地的游戏目录读取图集文件、并通过窗口消息读取截图，两者是独立程序，因此本项目可以采用 MIT。**若把游戏代码或素材搬进本仓库，此结论立即失效。**

第三方组件的完整清单见 `THIRD_PARTY.md`。
