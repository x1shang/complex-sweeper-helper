# Third-party interface

cshelper/vendor/wyc/window.py and bg_rc.py are copied from the locally available
wangyuanchuan2022/minesweeper_help checkout (../mshelp/ui), on 2026-10-09.
Source: https://github.com/wangyuanchuan2022/minesweeper_help
Adjustments to window.py: package-relative bg_rc import and absolute icon paths.
The PNG/ICO icons are copied from ../mshelp/icons.
Original generated-file notices are retained. The game-specific controller,
solver and labels are implemented separately in cshelper.

No upstream license file was present in that local mshelp checkout. These files
and bundled background images retain their upstream rights; this project's GPL
notice does not purport to relicense them. Confirm upstream redistribution terms
before publishing a distribution containing these assets.

Complexweeper source and atlas remain external runtime inputs:
https://github.com/Yueqing-Chen/complexweeper-A-minesweeper-game
See that project's LICENSE and 素材说明.md for its code and artwork terms.
