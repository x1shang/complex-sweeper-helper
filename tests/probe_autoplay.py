"""Opt-in real Windows game test. Starts and closes only its own process.

python tests/probe_autoplay.py --exe _lab/complexweeper.exe
"""
import argparse
import ctypes
from ctypes import wintypes
from pathlib import Path
import subprocess
import sys
import threading
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from cshelper.controller import WindowSession, board_status, choose_action, choose_actions
from cshelper.capture import find_window, user32, grab_client
from cshelper.engine import obs_from_board
from cshelper.solver import analyze


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--exe',required=True)
    p.add_argument('--game-dir',default='../complexweeper')
    args=p.parse_args()
    if find_window():
        raise SystemExit('Close the existing game before running this isolated test.')
    process=subprocess.Popen([str(Path(args.exe).resolve()),'--zoom1'])
    try:
        deadline=time.monotonic()+5
        while not find_window() and time.monotonic()<deadline:
            time.sleep(.05)
        hwnd=find_window()
        assert hwnd,'No game window'
        send=user32.SendMessageTimeoutW
        send.argtypes=[wintypes.HWND,wintypes.UINT,wintypes.WPARAM,wintypes.LPARAM,wintypes.UINT,wintypes.UINT,ctypes.POINTER(ctypes.c_size_t)]
        send.restype=ctypes.c_size_t
        for mode,command in [('complex',101),('hyper',120)]:
            result=ctypes.c_size_t()
            assert send(hwnd,0x111,command,0,2,1000,ctypes.byref(result))
            time.sleep(.1)
            options=argparse.Namespace(game_dir=args.game_dir,window_class='ComplexSweeperMain',preset='beginner',mode=mode,w=None,h=None,zoom=1)
            session=WindowSession(options)
            b=session.read()
            assert board_status(b)=='ready',(b.face,b.counters,board_status(b))
            action=choose_action(b,None)
            stop=threading.Event(); stop.set()
            assert not session.act(b,action,stop)
            original=b.cells[0][0].val
            b.cells[0][0].val=99
            assert not session.act(b,action),'Stale action not rejected'
            b.cells[0][0].val=original
            clicks=0
            rounds=0
            for step in range(100):
                b=session.read()
                state=board_status(b)
                if state in ('won','lost'):
                    assert choose_action(b,None) is None
                    grab_client(hwnd).save('_lab/autoplay-'+mode+'.png')
                    print(mode,state,'clicks',clicks,'solve rounds',rounds,flush=True)
                    break
                assert state in ('ready','playing'),(state,b.face,b.counters)
                r=analyze(obs_from_board(b),time_budget=1) if state=='playing' else None
                actions=choose_actions(b,r)
                assert actions,(r.status,r.msg)
                sent=session.act_batch(b,actions)
                assert sent
                clicks+=sent
                rounds+=int(r is not None)
                time.sleep(.15)
            else:
                raise AssertionError('Game did not terminate')
    finally:
        process.terminate()
        process.wait(timeout=5)

if __name__=='__main__':
    main()
