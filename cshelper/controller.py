"""Shared decision policy and guarded window adapter for GUI and CLI."""
from dataclasses import dataclass
from .engine import obs_from_board, recommend
from .solver import analyze


def fingerprint(b):
    face = 'active' if b.face in ('face_normal','face_scan') else b.face
    return (b.w,b.h,b.z,b.mode,b.counters,face,
            tuple((c.kind,c.val) for row in b.cells for c in row))


def board_status(b):
    kinds = [c.kind for row in b.cells for c in row]
    if b.face == 'face_dead' or 'boom' in kinds:
        return 'lost'
    if b.face == 'face_win':
        return 'won'
    if any(k in ('mine','flagmine','wrongblank') for k in kinds):
        return 'finished'
    if any(k == 'unknown' for k in kinds) or b.max_error > 5 or b.face not in ('face_normal','face_scan'):
        return 'unreadable'
    if b.counters is None:
        return 'ready' if all(k == 'closed' for k in kinds) and b.face == 'face_normal' else 'unreadable'
    totals = b.totals()
    if sum(k in ('closed','flag') for k in kinds) == sum(totals):
        return 'won'
    return 'playing'


@dataclass(frozen=True)
class Action:
    cell: tuple
    button: str
    reason: str
    risk: float = 0.0


def choose_action(b, res, allow_guess=True):
    state = board_status(b)
    if state == 'ready':
        return Action((b.h//2,b.w//2),'left','首次开局') if allow_guess else None
    if state != 'playing' or res is None or res.status != 'ok':
        return None
    rec = recommend(res.obs,res)
    safe = rec['safe']
    for rc in safe:
        cell = b.cells[rc[0]][rc[1]]
        if cell.kind == 'closed':
            return Action(rc,'left','已证明安全')
    for rc in safe:
        cell = b.cells[rc[0]][rc[1]]
        if cell.kind == 'flag':
            return Action(rc,'right','循环撤销安全格上的旗')
    if allow_guess:
        candidates = [(p,rc) for rc,p in res.prob.items() if b.cells[rc[0]][rc[1]].kind == 'closed' and rc not in getattr(res,'proven_mines',())]
        if candidates:
            p,rc = min(candidates,key=lambda x:(x[0],-len(res.obs.nbrs(*x[1])),x[1]))
            return Action(rc,'left','概率猜测' if res.exact.get(rc) else '估计猜测',p)
    return None


def choose_actions(b, res, allow_guess=True):
    """All proven-safe cells from one solve; opening/guessing stays single-step."""
    if board_status(b) == 'playing' and res is not None and res.status == 'ok':
        safe = recommend(res.obs, res)['safe']
        actions = [Action(rc, 'left', '批量已证明安全') for rc in safe
                   if b.cells[rc[0]][rc[1]].kind in ('closed', 'flag')]
        if actions:
            return actions
    action = choose_action(b, res, allow_guess)
    return [action] if action else []


def extends_board(before, after, action):
    """Opening cells preserves proofs; reset, changed clues or flags invalidate them."""
    if (before.w,before.h,before.z,before.mode,before.totals()) != (
            after.w,after.h,after.z,after.mode,after.totals()):
        return False
    for r in range(before.h):
        for c in range(before.w):
            old, new = before.cells[r][c], after.cells[r][c]
            if old.kind in ('num','blank') and (old.kind,old.val) != (new.kind,new.val):
                return False
            if action.button == 'right' and (r,c) == action.cell:
                val = (old.val + 1) % 5
                if (new.kind,new.val) != ('flag' if val else 'closed',val):
                    return False
            elif old.kind == 'flag' or new.kind == 'flag':
                if (old.kind,old.val) != (new.kind,new.val):
                    return False
    return True


class WindowSession:
    def __init__(self,args):
        from .capture import find_window
        from .atlas import default_atlas
        self.args = args
        self.hwnd = find_window(class_name=args.window_class)
        if not self.hwnd:
            raise RuntimeError('没找到复扫雷窗口，请先启动游戏')
        self.atlas = default_atlas(args.game_dir)

    def read(self):
        from .capture import grab_client, is_iconic, user32
        from .layout import fit_all, PRESETS
        from .recognize import read_board
        if not user32.IsWindow(self.hwnd) or is_iconic(self.hwnd):
            raise RuntimeError('目标窗口关闭或最小化，自动操作已停止')
        img = grab_client(self.hwnd)
        preset = PRESETS.get(self.args.preset)
        cands = fit_all(img.width,img.height,preset[0] if preset else self.args.w,preset[1] if preset else self.args.h)
        if self.args.zoom:
            cands = [x for x in cands if x[2] == self.args.zoom]
        boards = [read_board(img,self.atlas,*x,mode=self.args.mode,counter_thresh=5) for x in cands]
        if not boards:
            raise RuntimeError('窗口尺寸无法识别，请检查棋盘设置')
        boards.sort(key=lambda b:(sum(c.kind == 'unknown' for row in b.cells for c in row),b.quality))
        if len(boards)>1 and abs(boards[0].quality-boards[1].quality)<0.001:
            raise RuntimeError('棋盘尺寸有歧义，请在设置中指定难度或宽高')
        return boards[0]

    def act(self, expected, action, cancel=None):
        from .capture import click_message
        from .layout import Layout
        if cancel and cancel.is_set():
            return False
        current = self.read()
        if fingerprint(current) != fingerprint(expected):
            return False
        if cancel and cancel.is_set():
            return False
        try:
            click_message(self.hwnd,*Layout(current.w,current.h,current.z).cell_center(*action.cell),action.button)
        except OSError:
            # Winning may open the game's modal high-score message inside the
            # button-up handler, so SendMessageTimeout can expire after success.
            if board_status(self.read()) not in ('won','lost','finished'):
                raise
        return True

    def act_batch(self, expected, actions, cancel=None):
        """Execute one proof batch without solving between clicks.

        Re-read only to skip flood-opened cells and detect cancellation, terminal
        state or invalidation. Never reuse the old proof after a board reset.
        Returns number of mouse clicks actually sent.
        """
        from .capture import click_message
        from .layout import Layout
        if not actions or (cancel and cancel.is_set()):
            return 0
        current = self.read()
        if fingerprint(current) != fingerprint(expected):
            return 0
        clicks = 0
        for action in actions:
            # Up to four flag cycles followed by an open, without another solve.
            for _ in range(5):
                if cancel and cancel.is_set():
                    return clicks
                if board_status(current) not in ('ready','playing'):
                    return clicks
                cell = current.cells[action.cell[0]][action.cell[1]]
                if cell.kind in ('num','blank'):
                    break  # Already opened by flood fill.
                button = 'right' if cell.kind == 'flag' else action.button
                actual = Action(action.cell,button,action.reason,action.risk)
                try:
                    click_message(self.hwnd,*Layout(current.w,current.h,current.z).cell_center(*action.cell),button)
                except OSError:
                    if board_status(self.read()) in ('won','lost','finished'):
                        return clicks + 1
                    raise
                clicks += 1
                updated = self.read()
                if board_status(updated) not in ('ready','playing'):
                    return clicks
                # First opening draws the mine totals; it is always a singleton.
                if board_status(current) == 'ready':
                    return clicks
                if not extends_board(current,updated,actual):
                    return clicks
                if fingerprint(current) == fingerprint(updated):
                    return clicks  # Unacknowledged input: do not keep clicking.
                current = updated
                if button == 'left' or action.button == 'right':
                    break
        return clicks
