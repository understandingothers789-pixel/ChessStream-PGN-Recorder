"""One real-image check per recognizer and one useful desktop integration."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import chess
import cv2
from chessstream.domain import Region,Observation
from chessstream.vision import BoardDetector,ScreenshotRecognizer,choose_orientation
from chessstream.results import LocalTextReader,extract_context,parse_end_message
from chessstream.capture import rank_capture_windows,rank_youtube_windows

FIXTURES=Path(__file__).parent/'fixtures'


def test_actual_board_page_detection_piece_recognition_and_board_flip():
    recognizer=ScreenshotRecognizer()
    for filename in ['results/native-bot-start.png','real/lichess-start-page.png']:
        image=cv2.imread(str(FIXTURES/filename));rect,_=BoardDetector().detect(image)
        assert rect is not None
        x,y,w,h=rect;board=image[y:y+h,x:x+w]
        assert recognizer.recognize(board).placement()==chess.Board().board_fen()
    # This retained browser capture actually has Black at the bottom; the
    # pieces themselves remain upright, as they do during a real board flip.
    flipped=recognizer.recognize(cv2.imread(str(FIXTURES/'themes/chesscom-ocean-00.png')))
    assert choose_orientation(flipped,chess.Board()).placement()==chess.Board().board_fen()


def test_native_ocr_still_reads_names_clocks_and_game_end():
    image=cv2.imread(str(FIXTURES/'results/native-bot-resigned.png'))
    reader=LocalTextReader();lines=reader.read(image)
    context=extract_context(lines,(108,66,568,568),'white')
    assert context['names']=={'black':'Martinfoot','white':'Guest'}
    assert all(500<=time<=600 for time in context['clocks'].values())
    message=parse_end_message(lines,'white',context['names'])
    assert message and message.result=='0-1'
    # Exercise the native board-focused retry with the actual offline OCR model.
    from chessstream.results import EndMessageDetector
    class BoardReader:
        def read(self,tile):
            return [] if tile.shape==image.shape else reader.read(tile)
    now=[0.];detector=EndMessageDetector(BoardReader(),lambda:now[0])
    assert detector.scan(image,'white',(108,66,568,568),context['names']) is None
    now[0]=1.;end=detector.scan(image,'white',(108,66,568,568),context['names'])
    assert end and end.result=='0-1' and end.reason=='resignation'


def test_desktop_autoselection_provisional_board_and_library_actions(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    options=[(1,'ChessStream-PGN-Recorder-main - File Explorer'),
             (2,'understandingothers789-pixel/ChessStream-PGN-Recorder - Brave'),
             (3,'Music - YouTube - Brave'),
             (4,'MASTER SLOWKARU RAPID EDUCATIONAL SPEEDRUN 1 - YouTube - Brave')]
    monkeypatch.setattr(gui,'windows',lambda:options)
    monkeypatch.setattr(gui,'window_client',lambda hwnd:Region(0,0,1200,800,window=hwnd))
    monkeypatch.setattr(gui.MainWindow,'start_preview',lambda self:setattr(self,'preview_started',True))
    window=gui.MainWindow(tmp_path);assert window.region.window==4
    selected_during_switch=[]
    window.stack.currentChanged.connect(lambda index:selected_during_switch.append(
        [i for i,button in enumerate(window.nav) if button.isChecked()]))
    window.nav[1].click();assert selected_during_switch[-1]==[1]
    window.nav[0].click();assert selected_during_switch[-1]==[0]
    assert window.preview_started
    assert window.settings.save_screenshots is False
    # The common correction actions operate inline, without the old SAN dialog.
    actions=[]
    with monkeypatch.context() as action_patch:
        action_patch.setattr(window.manager,'repair_current',lambda:actions.append('repair'))
        action_patch.setattr(window.manager,'join_previous_recording',lambda **kwargs:actions.append('join'))
        window.repair_pgn_button.click();window.join_previous_button.click()
    assert actions==['repair','join']
    from PySide6.QtWidgets import QPushButton
    assert any(b.text()=='Combine selected PGNs' for b in window.findChildren(QPushButton))
    assert not window.save_screenshots.isChecked()
    assert rank_capture_windows(options)[0][0]==4
    assert rank_youtube_windows(options)[0][0]==4
    window.on_update({'preview_fen':chess.Board().fen(),'preview_moves':[],'confidence':.95,
                      'weakest_confidence':.9,'uncertain_squares':[],'moves':[],
                      'initial_fen':chess.STARTING_FEN,'orientation':'white',
                      'status':'Previewing selected window'})
    assert window.live_board.fen==chess.Board().fen()
    board=chess.Board();window.manager.process(Observation.from_board(board));board.push_san('e4')
    window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.live_board.fen==board.fen() and window.snapshot['pending_moves']==['e4']
    window._preview_active=True
    window.on_update({**window.snapshot,'recording_started_automatically':True})
    assert not window._preview_active and not window.start_button.isEnabled()
    assert window.pause_button.isEnabled() and window.stop_button.isEnabled()
    window.update_move_table(['e4'],chess.STARTING_FEN,guessed=[1])
    assert window.move_table.item(0,1).text()=='≈ e4'
    assert '1. e4' not in window.store.game(window.manager.current_id)['pgn']
    window.manager.force_new();window.navigate(1);window.game_table.selectAll()
    actions={action.text():action for action in window.game_row_menu().actions()}
    assert 'Remove saved .pgn copies…' in actions
    assert 'Delete game(s) from library…' in actions
    assert actions['Join selected recordings…'].isEnabled()
    # Older saved PGNs can be combined during capture without recovering the
    # combined record into the manager that the capture worker is using.
    window.manager.force_new();window.refresh_library()
    class ActiveWorker:
        running=True
        def isRunning(self):return True
        def stop(self):self.running=False
        def wait(self,_timeout):return True
    window.worker=ActiveWorker();older=[g for g in window.game_rows if g['id']!=window.manager.current_id]
    assert len(older)>=2
    errors=[];combined=[]
    monkeypatch.setattr(window,'error',errors.append)
    monkeypatch.setattr(window,'selected_games',lambda:[window.store.game(window.manager.current_id),older[0]])
    monkeypatch.setattr(window,'background',lambda fn,done:combined.append(('unexpected',None)))
    window.join_selected()
    assert errors and not combined
    monkeypatch.setattr(window,'selected_games',lambda:older[:2])
    monkeypatch.setattr(window.manager,'combine_games',lambda rows,pgn,*,activate:
                        combined.append((rows,activate)))
    monkeypatch.setattr(window,'background',lambda fn,done:done('combined PGN'))
    window.join_selected()
    assert len(combined)==1 and combined[0][1] is False
    assert window.stack.currentIndex()==1
    window.close();window.deleteLater();app.processEvents()


def test_screenshot_browser_supports_extended_range_and_multiselect(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication,QAbstractItemView
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    window=gui.MainWindow(tmp_path)
    image=cv2.imread(str(FIXTURES/'results/native-bot-start.png'))
    for second in (1,2,3):
        window.store.save_screenshot(window.manager.session_id,None,image,
            f'2026-10-19T00:00:0{second}.000+00:00',None,.9)
    window.navigate(2)
    window.show();app.processEvents()
    assert window.shot_list.selectionMode()==QAbstractItemView.ExtendedSelection
    view=window.shot_list.viewport()
    first=window.shot_list.visualItemRect(window.shot_list.item(0)).center()
    third=window.shot_list.visualItemRect(window.shot_list.item(2)).center()
    middle=window.shot_list.visualItemRect(window.shot_list.item(1)).center()
    QTest.mouseClick(view,Qt.LeftButton,Qt.NoModifier,first)
    QTest.mouseClick(view,Qt.LeftButton,Qt.ShiftModifier,third)
    assert len(window.shot_list.selectedItems())==3
    QTest.mouseClick(view,Qt.LeftButton,Qt.ControlModifier,middle)
    assert {window.shot_list.row(item) for item in window.shot_list.selectedItems()}=={0,2}
    assert window.delete_shots_button.isEnabled()
    ids=window.selected_screenshot_ids()
    assert len(ids)==2 and len(set(ids))==2
    window.close();window.deleteLater();app.processEvents()


def test_live_move_click_pins_history_until_return_to_live_or_game_change(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    window=gui.MainWindow(tmp_path)
    board=chess.Board()
    for san in ('e4','e5','Nf3'):board.push_san(san)
    snap={'game_id':'first','initial_fen':chess.STARTING_FEN,'fen':board.fen(),
          'moves':['e4','e5','Nf3'],'orientation':'white','status':'Recording'}
    window.on_update(snap)
    window.move_table.itemClicked.emit(window.move_table.item(0,1))
    first=chess.Board();first.push_san('e4')
    assert window.live_board.fen==first.fen() and not window.return_live_button.isHidden()
    board.push_san('Nc6');snap={**snap,'fen':board.fen(),'moves':snap['moves']+['Nc6']}
    window.on_update(snap)
    assert window.live_board.fen==first.fen() and not window.store.games()
    window.return_live_button.click();assert window.live_board.fen==board.fen()
    window.move_table.itemClicked.emit(window.move_table.item(0,2))
    window.on_update({**snap,'game_id':'second'})
    assert window.live_board.fen==board.fen() and window.return_live_button.isHidden()
    # A midgame FEN can start on Black's move; the Black cell still maps to ply 1.
    black=first.copy();black.push_san('e5');ending=black.copy();ending.push_san('Nf3')
    window.on_update({'game_id':'black-root','initial_fen':first.fen(),'fen':ending.fen(),
                      'moves':['e5','Nf3'],'orientation':'black','status':'Recording'})
    window.move_table.itemClicked.emit(window.move_table.item(0,2))
    assert window.live_board.fen==black.fen()
    window.close();window.deleteLater();app.processEvents()


def test_library_deletion_shows_difference_between_pgn_copy_and_game_record(tmp_path,monkeypatch):
    """The old UI appeared not to delete anything because game rows remained."""
    from PySide6.QtWidgets import QApplication,QMessageBox
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    monkeypatch.setattr(gui.MainWindow,'start_preview',lambda self:None)
    win=gui.MainWindow(tmp_path)
    win.manager.process(Observation.from_board(chess.Board()))
    win.manager.finish()
    gid=win.manager.current_id
    assert gid and win.store.game(gid)
    saved=win.store.root/'pgn'/(gid+'.pgn')
    assert saved.is_file()
    win.refresh_library()
    i=next(i for i,game in enumerate(win.game_rows) if game['id']==gid)
    assert win.game_table.item(i,6).text()=='Yes'
    monkeypatch.setattr(gui.QMessageBox,'warning',lambda *args,**kwargs:QMessageBox.Yes)
    monkeypatch.setattr(win,'selected_games',lambda:[win.store.game(gid)])
    win.delete_saved_pgns()
    assert not saved.exists() and win.store.game(gid)
    i=next(i for i,game in enumerate(win.game_rows) if game['id']==gid)
    assert win.game_table.item(i,6).text()=='No'
    win.delete_games()
    assert win.store.game(gid) is None and all(g['id']!=gid for g in win.game_rows)
    win.close();win.deleteLater();app.processEvents()


def test_clicking_last_move_and_follow_control_resume_live_updates(tmp_path,monkeypatch):
    from PySide6.QtWidgets import QApplication
    import chessstream.gui as gui
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr(gui,'windows',lambda:[])
    window=gui.MainWindow(tmp_path)
    board=chess.Board()
    for san in ('e4','e5','Nf3'):board.push_san(san)
    snap={'game_id':'live','initial_fen':chess.STARTING_FEN,'fen':board.fen(),
          'moves':['e4','e5','Nf3'],'orientation':'white','status':'Recording'}
    window.on_update(snap)
    window.review_live_move(window.move_table.item(0,1))
    assert window._live_review and not window.follow_live_button.isChecked()
    window.review_live_move(window.move_table.item(1,1))
    assert window._live_review is None and window.follow_live_button.isChecked()
    board.push_san('Nc6');snap={**snap,'fen':board.fen(),'moves':snap['moves']+['Nc6']}
    window.on_update(snap);assert window.live_board.fen==board.fen()
    window.review_live_move(window.move_table.item(0,1));window.follow_live_button.click()
    assert window._live_review is None and window.live_board.fen==board.fen()
    window.review_live_move(window.move_table.item(1,1));window.navigate_live_move(1)
    assert window._live_review is None
    window.navigate_live_move(-1);assert window._live_review['ply']==3
    window.navigate_live_move(1);assert window._live_review is None
    preview=board.copy();preview.push_san('Bb5')
    window.on_update({**snap,'provisional':True,'pending_moves':['Bb5'],'preview_fen':preview.fen()})
    window.navigate_live_move(-1);assert window._live_review['ply']==3
    window.navigate_live_move(1);assert window._live_review is None
    window.close();window.deleteLater();app.processEvents()
