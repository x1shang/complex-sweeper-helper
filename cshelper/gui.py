"""wyc2022 Qt shell connected to the Complexweeper controller."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from PyQt5 import QtCore, QtGui, QtWidgets
from .vendor.wyc.window import Ui_MainWindow
from .controller import WindowSession, board_status, choose_actions, fingerprint
from .engine import obs_from_board, recommend
from .solver import analyze

ROOT = Path(__file__).resolve().parent.parent


def defaults():
    return dict(game_dir=os.environ.get('CS_GAME_DIR',str(ROOT.parent/'complexweeper')),
                window_class='ComplexSweeperMain',mode='complex',preset=None,
                w=None,h=None,zoom=None,budget=5.0,png=None,delay=0.25)


class Worker(QtCore.QThread):
    update = QtCore.pyqtSignal(object,object,str)
    message = QtCore.pyqtSignal(str)
    def __init__(self,args,operation,parent=None):
        super().__init__(parent)
        self.args,self.operation = args,operation
        self.stop_event = threading.Event()
    def run(self):
        try:
            session = None if self.args.png else WindowSession(self.args)
            last,unchanged = None,0
            for step in range(2000):
                if self.stop_event.is_set():
                    break
                if session:
                    board = session.read()
                else:
                    from .cli import load_board
                    board,_ = load_board(self.args)
                state = board_status(board)
                result = analyze(obs_from_board(board),time_budget=self.args.budget,cancel=self.stop_event) if state == 'playing' else None
                if self.stop_event.is_set():
                    break
                text = '第 %d 步 · %s' % (step+1,state)
                if result:
                    text += ' · %.2fs · %s' % (result.elapsed,result.msg)
                self.update.emit(board,result,text)
                if self.operation == 'scan' or session is None:
                    break
                if state in ('won','lost','finished','unreadable'):
                    self.message.emit('停止：'+state)
                    break
                actions = choose_actions(board,result,self.operation == 'auto')
                if not actions:
                    self.message.emit('停止：当前没有可执行动作；可增加求解预算后重试')
                    break
                key = fingerprint(board)
                unchanged = unchanged+1 if key == last else 0
                last = key
                if unchanged >= 3:
                    self.message.emit('停止：点击后棋盘没有变化')
                    break
                clicks = session.act_batch(board,actions,self.stop_event)
                if clicks:
                    self.message.emit('本轮执行 %d 次点击（%d 个目标），完成后重新计算' % (clicks,len(actions)))
                else:
                    self.message.emit('棋盘已改变或任务停止，丢弃旧动作')
                if self.stop_event.wait(self.args.delay):
                    break
            else:
                self.message.emit('已到达单次 2000 步上限')
        except (Exception,SystemExit) as exc:
            self.message.emit('停止：'+str(exc))


class MainWindow(QtWidgets.QMainWindow,Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)
        self.setWindowTitle('复扫雷 AI 助手 · wyc2022 界面')
        self.setWindowIcon(QtGui.QIcon(str(ROOT/'cshelper/vendor/wyc/icons/icon.ico')))
        self.worker = None
        self.config = defaults()
        self.config_path = ROOT/'settings.local.json'
        if self.config_path.exists():
            try:
                saved = json.loads(self.config_path.read_text(encoding='utf-8'))
                self.config.update({k:v for k,v in saved.items() if k in self.config})
            except (ValueError,OSError):
                pass
        self.plainTextEdit.setReadOnly(True)
        self.label_10.setText('·复扫雷：四类雷 +1、−1、+i、−i；支持圆复数与闵可夫斯基模式。')
        self.label_11.setText('·自动：首次开局 → 证明安全 → 无安全格时猜测 → 输赢后停止。')
        self.label_12.setText('·帮助人类：读取当前游戏，展示每格雷概率；带 * 为有界模型估计。')
        self.label_15.setText('·设置中选择游戏素材目录、规则模式和棋盘尺寸，必须与游戏一致。')
        self.label_13.setText('·截图帮助：读取客户区 PNG；离线截图不会发送点击。')
        self.label_14.setText('·猜测可能踩雷；蓝框安全格经过证明，采样或模型估计为 0 不代表安全。')
        self.label_16.setText('·点击“停止”或按 Esc 可取消；动作前重读棋盘，窗口关闭自动停止。')
        self.label_2.setText('复扫雷概率图：格内为雷概率；* 表示估计，蓝框表示已证明安全。')
        self.label_3.setText('红色：雷概率高')
        self.label_5.setText('绿色：低')
        self.label_7.setText('线索显示平方值 D；旗不作为已知雷参与约束。')
        self.label_8.setText('每轮批量翻开全部已证明安全的格子，再统一重新求解。')
        self.label_9.setText('鼠标悬停查看四类雷概率与证明状态。')
        self.label_17.setText('“点击确定方格”只执行证明安全的动作；全自动允许猜测。')
        self.label_18.setText('蓝框仅表示安全证明，不表示该格的四类边际均已精确求出。')
        self.end_auto_play_thread.setText('停止 (Esc)')
        self.end_help_thread.setText('停止 (Esc)')
        self.pgb.setValue(0)
        self.pgb_p3.setValue(0)
        self.table = QtWidgets.QTableWidget()
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.setStyleSheet('QTableWidget {background:white;color:black;}')
        self.label_p3.hide()
        layout = QtWidgets.QVBoxLayout(self.frame_2)
        layout.setContentsMargins(0,0,0,0)
        layout.addWidget(self.table)
        self.frame_2.setMinimumHeight(220)
        self.launch_button = QtWidgets.QPushButton('启动复扫雷')
        self.verticalLayout_4.addWidget(self.launch_button)
        self.launch_button.clicked.connect(self.launch_game)
        self.auto_play.clicked.connect(lambda:self.start('auto'))
        self.help_human.clicked.connect(lambda:self.start('scan'))
        self.screenshot_help.clicked.connect(self.open_png)
        self.setting_2.clicked.connect(self.settings)
        self.click_all.clicked.connect(lambda:self.start('safe'))
        self.end_auto_play_thread.clicked.connect(self.stop)
        self.end_help_thread.clicked.connect(self.stop)
        self.return_to_main_page.clicked.connect(lambda:self.stackedWidget.setCurrentIndex(0))
        self.return_to_main_p3.clicked.connect(lambda:self.stackedWidget.setCurrentIndex(0))
        self.escape = QtWidgets.QShortcut(QtGui.QKeySequence('Esc'),self,activated=self.stop)
        self.statusBar().showMessage('就绪：先设置模式与棋盘尺寸，再启动游戏')
        self.offline = False

    def log(self,text):
        self.plainTextEdit.appendPlainText(text)
        self.statusBar().showMessage(text)

    def start(self,operation,png=None):
        if self.worker and self.worker.isRunning():
            self.log('请先停止当前任务')
            return
        self.offline = bool(png)
        args = argparse.Namespace(**self.config)
        args.png = png
        self.stackedWidget.setCurrentIndex(1 if operation == 'auto' else 2)
        self.worker = Worker(args,operation,self)
        self.worker.update.connect(self.render)
        self.worker.message.connect(self.log)
        self.worker.finished.connect(self.finished)
        self.pgb.setRange(0,0)
        self.pgb_p3.setRange(0,0)
        for button in (self.auto_play,self.help_human,self.screenshot_help,self.setting_2,self.click_all,self.launch_button):
            button.setEnabled(False)
        self.log('正在识别与求解…')
        self.worker.start()

    def stop(self):
        if self.worker:
            self.worker.stop_event.set()
            self.log('正在停止；不会再发送下一次点击')

    def finished(self):
        for progress in (self.pgb,self.pgb_p3):
            progress.setRange(0,100)
            progress.setValue(100)
            progress.setFormat('完成')
        for button in (self.auto_play,self.help_human,self.screenshot_help,self.setting_2,self.launch_button):
            button.setEnabled(True)
        self.click_all.setEnabled(not self.offline)

    def render(self,b,res,text):
        self.log(text)
        self.table.clear()
        # clear() retains cell widgets; reset dimensions to remove old proofs.
        self.table.setRowCount(0)
        self.table.setRowCount(b.h)
        self.table.setColumnCount(b.w)
        self.table.horizontalHeader().setDefaultSectionSize(42)
        self.table.verticalHeader().setDefaultSectionSize(30)
        safe = set(recommend(res.obs,res)['safe']) if res else set()
        for r in range(b.h):
            for c in range(b.w):
                cell = b.cells[r][c]
                rc = (r,c)
                p = res.prob.get(rc) if res else None
                label = '.' if cell.kind == 'blank' else str(cell.val) if cell.kind == 'num' else 'F%d'%cell.val if cell.kind == 'flag' else '#' if cell.kind == 'closed' else cell.kind
                item = QtWidgets.QTableWidgetItem(label)
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                if p is not None:
                    exact = res.exact.get(rc,False)
                    item.setText(('%d'%round(p*100))+('' if exact else '*'))
                    item.setBackground(QtGui.QColor(round(255*p),round(210*(1-p)),70))
                    item.setForeground(QtGui.QColor('black'))
                    units = '+1 / −1 / +j / −j' if b.mode == 'hyper' else '+1 / −1 / +i / −i'
                    item.setToolTip('雷概率 %.3f%%\n%s\n%s: %s' % (p*100,'已证明安全' if rc in safe else '精确边际' if exact else '估计：不是均匀抽样',units,', '.join('%.3f'%x for x in res.ptype[rc])))
                self.table.setItem(r,c,item)
                if rc in safe:
                    label_widget = QtWidgets.QLabel(item.text())
                    label_widget.setAlignment(QtCore.Qt.AlignCenter)
                    label_widget.setStyleSheet('border:2px solid blue;background:#7ce38b;color:black;')
                    label_widget.setToolTip(item.toolTip())
                    self.table.setCellWidget(r,c,label_widget)

    def open_png(self):
        path,_ = QtWidgets.QFileDialog.getOpenFileName(self,'打开客户区截图',str(ROOT/'_lab'),'PNG (*.png)')
        if path:
            self.start('scan',path)

    def settings(self):
        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle('复扫雷设置')
        form = QtWidgets.QFormLayout(dlg)
        path = QtWidgets.QLineEdit(self.config['game_dir'])
        form.addRow('素材所在游戏目录',path)
        mode = QtWidgets.QComboBox()
        mode.addItems(['complex','hyper'])
        mode.setCurrentText(self.config['mode'])
        form.addRow('规则模式',mode)
        preset = QtWidgets.QComboBox()
        preset.addItems(['auto','beginner','intermediate','expert','custom'])
        preset.setCurrentText(self.config['preset'] or ('custom' if self.config['w'] else 'auto'))
        form.addRow('棋盘难度',preset)
        width,height = QtWidgets.QSpinBox(),QtWidgets.QSpinBox()
        width.setRange(9,40); height.setRange(9,30)
        width.setValue(self.config['w'] or 16); height.setValue(self.config['h'] or 16)
        form.addRow('自定义宽',width); form.addRow('自定义高',height)
        budget = QtWidgets.QDoubleSpinBox()
        budget.setRange(0.1,120)
        budget.setValue(self.config['budget'])
        form.addRow('每步求解预算（秒）',budget)
        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok|QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept); buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        if dlg.exec_():
            custom = preset.currentText() == 'custom'
            self.config.update(game_dir=path.text(),mode=mode.currentText(),preset=None if preset.currentText() in ('auto','custom') else preset.currentText(),w=width.value() if custom else None,h=height.value() if custom else None,budget=budget.value())
            self.config_path.write_text(json.dumps(self.config,ensure_ascii=False,indent=2),encoding='utf-8')

    def launch_game(self):
        root = Path(self.config['game_dir'])
        candidates = [ROOT/'_lab'/'complexweeper.exe'] + list(root.glob('**/*.exe'))
        executable = next((p for p in candidates if p.is_file() and ('complexweeper' in p.name.lower() or '复扫雷' in p.name)),None)
        if not executable:
            name,_ = QtWidgets.QFileDialog.getOpenFileName(self,'选择复扫雷程序',str(root),'游戏 (*.exe)')
            executable = Path(name) if name else None
        if executable:
            subprocess.Popen([str(executable)],cwd=ROOT)

    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            self.stop()
            event.ignore()
            self.worker.finished.connect(self.close)
        else:
            event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec_()

if __name__ == '__main__':
    raise SystemExit(main())
