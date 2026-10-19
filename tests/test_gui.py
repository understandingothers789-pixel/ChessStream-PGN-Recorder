import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QInputDialog
from chessstream.gui import MainWindow
from chessstream.domain import Observation
import chess
import cv2
from pathlib import Path


def test_desktop_pages_game_review_and_screenshots(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path);window.show();app.processEvents()
    b=chess.Board();window.manager.process(Observation.from_board(b))
    for san in 'e4 e5 Nf3'.split():b.push_san(san);window.manager.process(Observation.from_board(b))
    window.manager.choose(0)
    window.on_update(window.manager.snapshot());assert window.move_table.rowCount()==2
    image=cv2.imread(str(Path(__file__).parent/'fixtures/real/lichess-start.png'));window.on_frame(image)
    window.store.save_screenshot(window.manager.session_id,window.manager.current_id,image,'2026-10-18T00:00:00.000+00:00',b.board_fen(),.99,3)
    window.navigate(1);window.game_table.selectRow(0);app.processEvents();assert 'Nf3' in window.library_pgn.toPlainText()
    window.review_slider.setValue(1);assert chess.Board(window.library_board.fen).piece_at(chess.E4)==chess.Piece(chess.PAWN,chess.WHITE)
    window.navigate(2);app.processEvents();assert window.shot_list.count()==1
    window.shot_list.setCurrentRow(0);assert 'Verified ply at capture: 3' in window.shot_info.text()
    window.navigate(3);assert window.retention.value()==0 and not window.dedupe.isChecked()
    window.navigate(0);window.resize(1000,580);app.processEvents()
    scroll=window.stack.currentWidget()
    assert scroll.verticalScrollBar().maximum()>0
    scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
    assert scroll.verticalScrollBar().value()==scroll.verticalScrollBar().maximum()
    window.close();window.deleteLater();app.processEvents()


def test_pending_recognition_is_not_shown_as_a_reconstructed_start(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    assert window.live_board.fen is None
    window.on_update({"fen":None,"moves":[],"status":"Waiting for reliable recognition",
                      "weakest_confidence":.55,"confidence":.99,"uncertain_squares":["d8"]})
    assert window.metric_labels['confidence'].text()=='55.0%'
    assert 'd8' in window.recognition_details.text()
    assert window.live_board.fen is None
    window.close();window.deleteLater();app.processEvents()


def test_provisional_san_is_visible_but_excluded_from_verified_pgn(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path);board=chess.Board()
    window.manager.process(Observation.from_board(board))
    board.push_san('e4');window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.move_table.item(0,1).text()=='… e4'
    assert window.metric_labels['moves'].text()=='0'
    assert window.live_board.fen==board.fen()
    assert window.manager.snapshot()['fen']==chess.Board().fen()
    assert 'PROVISIONAL' in window.board_heading.text()
    assert 'e4' in window.last_move_label.text()
    assert window.choose_path.text()=='Confirm final / pending move'
    assert '1. e4' not in window.store.game(window.manager.current_id)['pgn']
    board.push_san('e5');window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.move_table.item(0,1).text()=='✓ e4'
    assert window.move_table.item(0,2).text()=='… e5'
    assert window.metric_labels['moves'].text()=='1'
    assert window.live_board.fen==board.fen()
    window.manager.choose(0);window.on_update(window.manager.snapshot())
    assert window.move_table.item(0,2).text()=='✓ e5'
    assert window.live_board.fen==board.fen()
    assert window.screenshot_mode.currentData()=='positions' and not window.interval.isEnabled()
    window.screenshot_mode.setCurrentIndex(1)
    assert window.settings.screenshot_mode=='interval' and window.interval.isEnabled()
    window.close();window.deleteLater();app.processEvents()


def test_live_board_preview_tracks_replaced_hover_without_committing_it(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path);board=chess.Board()
    window.manager.process(Observation.from_board(board))
    board.push_san('e4');window.on_update(window.manager.process(Observation.from_board(board)))
    assert window.live_board.fen==board.fen()
    assert window.manager.snapshot()['preview_moves']==['e4']

    # A drag hovering on d4 replaces the earlier e4 hypothesis.
    board=chess.Board();board.push_san('d4')
    window.on_update(window.manager.process(Observation.from_board(board)))
    snap=window.manager.snapshot()
    assert window.live_board.fen==board.fen()
    assert snap['preview_moves']==['d4']
    assert snap['moves']==[] and snap['fen']==chess.Board().fen()
    assert '1. d4' not in window.store.game(window.manager.current_id)['pgn']
    assert 'not yet in PGN' in window.last_move_label.text()
    window.close();window.deleteLater();app.processEvents()


def test_copy_visible_fen_copies_known_and_user_selected_side_to_move(tmp_path,monkeypatch):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path)
    board=chess.Board()
    for san in 'e4 e5 Nf3 Nc6 Bc4'.split():board.push_san(san)
    window.manager.process(Observation.from_board(board))

    choices={}
    def choose_side(parent,title,prompt,items,current,editable):
        choices['items']=items
        return items[1],True
    monkeypatch.setattr(QInputDialog,'getItem',choose_side)
    window.copy_visible_fen()
    copied=app.clipboard().text()
    assert chess.Board(copied).board_fen()==board.board_fen()
    assert chess.Board(copied).turn is chess.BLACK
    assert len(choices['items'])==2
    window.close();window.deleteLater();app.processEvents()


def test_pgn_variation_viewer_navigates_alternative_without_changing_mainline(tmp_path):
    app=QApplication.instance() or QApplication([])
    window=MainWindow(tmp_path);board=chess.Board();window.manager.process(Observation.from_board(board))
    for san in 'e4 e5 Nf3'.split():board.push_san(san);window.manager.process(Observation.from_board(board))
    window.manager.choose(0);gid=window.manager.current_id
    window.manager.annotate(gid,[],'d4 d5','Queen pawn alternative')
    window.navigate(1);window.game_table.selectRow(0);app.processEvents()
    window.review_tree.setCurrentItem(window.review_items[(1,0)])
    expected=chess.Board();expected.push_san('d4');expected.push_san('d5')
    assert chess.Board(window.library_board.fen).board_fen()==expected.board_fen()
    assert 'variation' in window.review_label.text()
    assert len(window.manager.rec.verified)==3
    window.review_slider.setValue(0);app.processEvents()
    assert window.library_board.fen==chess.STARTING_FEN
    import io
    parsed=chess.pgn.read_game(io.StringIO(window.library_pgn.toPlainText()))
    assert len(parsed.variations)==2 and parsed.variations[1].move.uci()=='d2d4'
    window.close();window.deleteLater();app.processEvents()
