# 变更记录

## 0.1.0

- 复扫雷识别管线（图集驱动、棋盘尺寸与缩放自动反解）、五态约束引擎、Z3 全局求解器。
- 自动对局：证明安全后批量翻开，无安全格时按估计风险猜测，胜负后停止。
- Qt 界面外壳（来自 [wangyuanchuan2022/minesweeper_help](https://github.com/wangyuanchuan2022/minesweeper_help)）。
- 单元测试与 GitHub Actions CI。
- **许可证为 MIT**（见 `LICENSE`）。本仓库此前未发布过版本；早期提交曾标注 GPL-3.0。
- 第三方组件与适用范围见 `THIRD_PARTY.md`。
