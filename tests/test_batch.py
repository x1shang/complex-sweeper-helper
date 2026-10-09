import copy
import threading
import unittest
from unittest.mock import patch
from cshelper.controller import WindowSession, Action, choose_actions
from cshelper.engine import Obs, Result
from cshelper.recognize import Board, Cell

class BatchTests(unittest.TestCase):
    def board(self):
        b=Board(5,1,1,'complex')
        b.face='face_normal'; b.counters=(1,0,0,0)
        b.cells=[[Cell('closed') for _ in range(5)]]
        return b

    def session(self,boards):
        session=WindowSession.__new__(WindowSession)
        session.hwnd=123
        session.read=lambda: copy.deepcopy(next(boards))
        return session

    def test_batch_skips_flood_without_solve(self):
        initial=self.board()
        first=copy.deepcopy(initial)
        first.cells[0][0]=Cell('blank');first.cells[0][1]=Cell('num',1)
        final=copy.deepcopy(first);final.cells[0][2]=Cell('num',1)
        session=self.session(iter([initial,first,final]))
        actions=[Action((0,c),'left','safe') for c in (0,1,2)]
        with patch('cshelper.capture.click_message') as click:
            self.assertEqual(session.act_batch(initial,actions),2)
            self.assertEqual(click.call_count,2)

    def test_cancel_mid_batch(self):
        initial=self.board(); after=copy.deepcopy(initial);after.cells[0][0]=Cell('num',1)
        session=self.session(iter([initial,after])); stop=threading.Event()
        with patch('cshelper.capture.click_message',side_effect=lambda *args:stop.set()) as click:
            self.assertEqual(session.act_batch(initial,[Action((0,c),'left','safe') for c in (0,1)],stop),1)
            self.assertEqual(click.call_count,1)

    def test_reset_invalidates_remaining(self):
        initial=self.board();initial.cells[0][4]=Cell('num',1)
        reset=self.board()
        session=self.session(iter([initial,reset]))
        with patch('cshelper.capture.click_message') as click:
            self.assertEqual(session.act_batch(initial,[Action((0,c),'left','safe') for c in (0,1)]),1)
            self.assertEqual(click.call_count,1)

    def test_only_proven_zero_is_batched(self):
        b=self.board();o=Obs(5,1,'complex');r=Result(o)
        r.prob={(0,0):0,(0,1):0,(0,2):0}
        r.proven_safe={(0,0),(0,2)}
        self.assertEqual([a.cell for a in choose_actions(b,r)],[(0,0),(0,2)])

    def test_flags_cleared_without_solving(self):
        initial=self.board();initial.cells[0][0]=Cell('flag',3);initial.counters=(1,0,-1,0)
        flag4=copy.deepcopy(initial);flag4.cells[0][0]=Cell('flag',4);flag4.counters=(1,0,0,1)
        cleared=self.board();opened=copy.deepcopy(cleared);opened.cells[0][0]=Cell('num',1)
        session=self.session(iter([initial,flag4,cleared,opened]))
        with patch('cshelper.capture.click_message') as click:
            self.assertEqual(session.act_batch(initial,[Action((0,0),'left','safe')]),3)
            self.assertEqual([c.args[-1] for c in click.call_args_list],['right','right','left'])

if __name__=='__main__': unittest.main()
