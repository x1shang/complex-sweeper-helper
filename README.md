# 复扫雷 AI 助手

适配 [Yueqing-Chen/Complexweeper](https://github.com/Yueqing-Chen/complexweeper-A-minesweeper-game) 的外部助手，使用 [wangyuanchuan2022/minesweeper_help](https://github.com/wangyuanchuan2022/minesweeper_help) 的 Qt 界面外壳。

支持 **完整自动对局**：识别窗口 → 首次开局 → 证明安全并点击 → 无安全格时按估计风险猜测 → 胜利或失败停止。游戏本体无需修改。

## 启动

Windows + Python 3.10 或以上。当前工作目录已安装项目内依赖 `.deps`，直接双击 **`launch.bat`**，或：

```powershell
python -m cshelper.gui
```

换电脑后先运行 `setup.bat`，或 `python -m pip install -r requirements.txt`。

1. 在“设置”中指定含 `素材/图集.json`、`素材/图集.png` 的复扫雷目录。默认使用旁边的 `../complexweeper`，也可设置 `CS_GAME_DIR`。
2. 选择与游戏一致的 `complex`（圆复数）或 `hyper`（闵可夫斯基）。棋盘尺寸支持自动识别；窄棋盘存在尺寸歧义时选择具体难度或自定义宽高。
3. 点击“启动复扫雷”，或自行运行游戏。按钮优先使用本项目 `_lab/complexweeper.exe`，其次寻找设置目录中的游戏程序。
4. “自动”完成一局；“帮助人类”显示概率图；“截图帮助”读取客户区 PNG；“点击确定方格”连续执行安全动作，遇到需要猜测时停止。
5. “停止”或助手窗口内的 Esc 取消当前任务。GUI 求解在工作线程中运行；停止后不会排队执行后续点击。

自动模式允许猜雷，**不保证通关或特定胜率**。概率旁的 `*` 是有界模型估计，不是精确概率。蓝框格经过独立安全证明。

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

默认入口 `engine.analyze()` 转到 `solver.py`，使用 Z3 的布尔与整数约束。旧枚举/MCMC 后端保留为 `engine.analyze_legacy()`，仅供实验和旧诊断脚本参考，自动对局不使用它。

- 每格五态：空、+1、−1、+i、−i。双曲模式用 +j、−j，数值约束改为 `a²−b²`。
- 已开数字的内部值是模长的平方 D。空白严格要求邻居全空；数字 0 要求邻居存在雷，不能与空白混同。
- 四类全局总数 = LED 剩余数量 + 对应旗帜数量。旗本身不作为真雷约束，允许发现错旗。
- 小局面枚举所有边界赋值。无约束格用整数多项式组合数积分，避免枚举自由区域，也避免浮点 `exp` 溢出。
- 大局面受时间和 2048 个模型上限约束。模型枚举不是均匀抽样，其频率仅作为猜测排序；使用少量全局先验平滑，避免把未观察到的状态当成不可能。
- 安全证明单独查询“这些候选格中至少一个是雷”是否不可满足。只有 UNSAT 或完整计数的零支持才产生安全格；超时、近似 0、四类总数矛盾均不会生成安全证明。
- 每轮连续翻开所有已证明安全的格子，再统一求解。批内只做识别核对，跳过自动展开的格子；遇到安全格上的错旗连续右键撤旗后翻开。自动流程无需猜测旗的具体类型，也不依赖展开动作。

## 窗口与界面

- `controller.py`：GUI 与 CLI 共用的状态机、动作选择与窗口会话。
- `capture.py`：完整 Win64 句柄声明，PrintWindow 客户区截图，向固定游戏 HWND 发送成对鼠标消息，不移动系统鼠标。
- 批次开始前核对棋盘；批内允许正常翻开和空白展开，原有线索、总数或棋盘尺寸变化则丢弃剩余动作；窗口关闭/最小化、识别异常、点击无变化都会停止。
- 识别未知格、LED 部分缺失、模式单位不匹配及终局贴图，不把这些情况当成正常未开格。
- `gui.py`：原 Qt 外壳适配；设置、自动日志、概率表格、四类概率悬停提示、截图分析和取消。
- `cshelper/vendor/wyc`：来自本地 `mshelp` 的原界面、背景与图标。来源与权利说明见 `THIRD_PARTY.md`。不依赖 `mshelp` 的求解器、配置或当前工作目录。

## 验证

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
python tests/probe_offline.py
python tests/probe_engine.py
# 先关闭已有游戏；此测试仅启动并关闭它自己创建的游戏进程
python tests/probe_autoplay.py --exe _lab/complexweeper.exe
```

2026-10-09 当前环境实测：

- 40 个随机小棋盘（两种模式）与独立五态穷举的逐格、逐类型概率一致。
- 数字 0 / 空白、错旗、取消、1200 格自由区域组合权重、自动动作状态门控测试通过。
- 4 张已有截图（z=1/2/3 与 hyper）识别回归通过。
- `demo.png` 的 13 个安全证明与揭示雷盘真值一致。
- 真实初级窗口：圆复数自动胜利（13 次点击）、hyper 自动胜利（14 次点击）；高级测试局自动踩雷后停止。
- 真实窗口验证过取消和过期棋盘拒绝；GUI 工作线程、概率表渲染和离线禁点验证通过。

以上是功能回归，不是胜率统计。复杂中高级局面的估计仍有偏差；预算不足时可能找不到合法模型而停止。暂未实现最优胜率搜索、连续多局刷局和独立 EXE 打包。

游戏与图集作为外部输入，不随本项目源码发布。`_lab` 中的截图、日志和测试程序属于本地验证产物。
