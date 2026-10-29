"""Stop/start must join a capture worker before releasing or replacing it."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import threading
import time
import chess
from PySide6.QtCore import QThread
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from chessstream.capture import RecordingWorker
from chessstream.domain import Region,utcnow


def until(app,predicate):
    deadline=time.monotonic()+4
    while not predicate() and time.monotonic()<deadline:
        app.processEvents();QTest.qWait(10)
    assert predicate()


def test_stop_immediate_start_waits_for_cleanup_and_preserves_saved_game(tmp_path,monkeypatch):
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    workers=[]
    class DelayedWorker(RecordingWorker):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.entered=threading.Event()
            self.cleaning=threading.Event();self.release=threading.Event();workers.append(self)
        def run(self):
            self.entered.set();self.stopping.wait(4);self.cleaning.set();self.release.wait(4)
            if not self.preview_only:
                self.manager.finish();self.manager.store.finish_session(self.manager.session_id)
    monkeypatch.setattr(gui,'RecordingWorker',DelayedWorker)
    monkeypatch.setattr(gui,'windows',lambda:[])
    win=gui.MainWindow(tmp_path);win.region=Region(0,0,500,500);win._auto_window_enabled=False
    win.manager._create(chess.Board(),utcnow());win.manager.correct_line('e4 e5')
    gid=win.manager.current_id;old_manager=win.manager
    win.toggle_start();until(app,lambda:workers[0].entered.is_set());old=workers[0]
    win.stop();until(app,lambda:old.cleaning.is_set())
    win.toggle_start();win.toggle_start()  # Hotkey / rapid repeated Start requests.
    assert win.worker is old and len(workers)==1 and not win.start_button.isEnabled()
    old.finished.emit()  # A finished notification cannot substitute for wait().
    app.processEvents();assert win.worker is old and len(workers)==1
    old.update.emit({'status':'obsolete frame','game_id':'obsolete','moves':[]})
    app.processEvents();assert win.snapshot.get('game_id')!='obsolete'
    old.release.set()
    until(app,lambda:len(workers)==2 and workers[1].entered.is_set())
    assert win.manager is not old_manager and win.worker is workers[1]
    assert not win._worker_stopping and not win.start_button.isEnabled()
    assert win.store.game(gid)['plies']==2 and win.store.game(gid)['ended']
    # More ordinary Stop/Start cycles retain the old worker until it is joined.
    for _ in range(3):
        current=win.worker;win.stop();current.release.set()
        until(app,lambda:win.worker is None)
        assert win.start_button.isEnabled() and not win.pause_button.isEnabled()
        win.toggle_start();until(app,lambda:win.worker is not None and win.worker.entered.is_set())
    current=win.worker;current.release.set();win.stop();until(app,lambda:win.worker is None)
    win.close();win.deleteLater();app.processEvents()


def test_finished_from_old_worker_does_not_reset_new_worker_controls(tmp_path,monkeypatch):
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    win=gui.MainWindow(tmp_path)
    old=RecordingWorker(win.manager,Region(0,0,100,100))
    current=RecordingWorker(win.manager,Region(0,0,100,100));win.worker=current
    old.finished.connect(win.worker_finished);old.update.connect(win.on_update)
    old.region_changed.connect(win.auto_region)
    win.start_button.setEnabled(False);win.pause_button.setEnabled(True)
    old.finished.emit();old.update.emit({'game_id':'obsolete'})
    old.region_changed.emit(Region(5,5,200,200))
    assert win.worker is current and not win.start_button.isEnabled()
    assert win.pause_button.isEnabled() and win.region is None
    assert win.snapshot.get('game_id')!='obsolete'
    win.worker=None;win.close();win.deleteLater();app.processEvents()


def test_native_ocr_owner_is_released_inside_capture_thread(tmp_path,monkeypatch):
    import contextlib
    import mss
    import chessstream.capture as capture
    from chessstream.games import GameManager
    from chessstream.domain import Settings
    from chessstream.storage import Store
    app=QApplication.instance() or QApplication([])
    created=[];released=[]
    class Detector:
        def __init__(self):created.append(threading.get_ident())
        def __del__(self):released.append(threading.get_ident())
    monkeypatch.setattr(capture,'EndMessageDetector',Detector)
    monkeypatch.setattr(mss,'mss',lambda:contextlib.nullcontext(object()))
    store=Store(tmp_path);manager=GameManager(store,Settings())
    worker=RecordingWorker(manager,Region(0,0,100,100),preview_only=True)
    worker.stop();worker.start()
    assert worker.wait(4000)
    assert created and released==created and created[0]!=threading.get_ident()
    assert worker._text_detector is None and worker.audio is None
    store.close()
