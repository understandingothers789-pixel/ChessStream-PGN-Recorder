"""Lichess-inspired inline notation renders locally and navigates the actual tree."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import io
import chess
import chess.pgn
from PySide6.QtCore import Qt,QUrl
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from chessstream.notation_view import NotationView


def test_mainline_nested_variations_clocks_and_safe_comments():
    app=QApplication.instance() or QApplication([])
    game=chess.pgn.read_game(io.StringIO('1. e4 {[%clk 0:09:52]} e6 (1... e5 2. Nf3 (2. Nc3 Nc6)) 2. d4 d5 *'))
    game.variations[0].comment+=' <img src="https://invalid.example/secret"> & unsafe'
    view=NotationView();view.resize(300,460);view.show_game(game,(0,1,0),pending=['Nc3'])
    assert set(view.paths)=={(),(0,),(0,0),(0,1),(0,1,0),(0,1,1),(0,1,1,0),(0,0,0),(0,0,0,0)}
    text=view.toPlainText()
    assert 'e5' in text and 'Nc6' in text and '9:52' in text and 'Pending' in text
    assert '<img src=' in text and 'https://invalid.example' in text
    assert view.loadResource(2,QUrl('https://invalid.example')) is None
    clicked=[];view.move_selected.connect(clicked.append)
    view._activate(QUrl('move:0.1.1'))
    assert clicked==[(0,1,1)]
    view._activate(QUrl('https://invalid.example'));assert len(clicked)==1
    view._activate(QUrl('move:999'));assert len(clicked)==1
    view.selected=(0,1,0);QTest.keyClick(view,Qt.Key_Right)
    assert clicked[-1]==(0,1,1)
    view.show();app.processEvents()
    cursor=view.document().find('Nc3');start=cursor.selectionStart();cursor.setPosition(start+1)
    view.setTextCursor(cursor);view.ensureCursorVisible();app.processEvents()
    QTest.mouseClick(view.viewport(),Qt.LeftButton,Qt.NoModifier,view.cursorRect(cursor).center())
    assert clicked[-1]==(0,1,1)
    view.close()


def test_live_and_library_variation_selection_updates_board(tmp_path,monkeypatch):
    from chessstream.gui import MainWindow
    app=QApplication.instance() or QApplication([])
    monkeypatch.setattr('chessstream.gui.windows',lambda:[])
    win=MainWindow(tmp_path)
    pgn='1. e4 e6 (1... e5 2. Nf3) 2. d4 d5 *'
    doc=chess.pgn.read_game(io.StringIO(pgn));board=doc.end().board()
    snap={'game_id':'test','initial_fen':chess.STARTING_FEN,'fen':board.fen(),
          'moves':[node.san() for node in doc.mainline()],'recorded_pgn':pgn,'status':'Recording'}
    win.on_update(snap);win.live_notation._activate(QUrl('move:0.1.0'))
    expected=chess.Board()
    for san in ('e4','e5','Nf3'):expected.push_san(san)
    assert win.live_board.fen==expected.fen() and win._live_review['path']==(0,1,0)
    win.on_update(snap);assert win.live_board.fen==expected.fen()
    win.live_notation._activate(QUrl('move:0.0.0.0'))
    assert win._live_review is None and win.live_board.fen==board.fen()
    win.populate_review({'id':'test','pgn':pgn})
    win.library_notation._activate(QUrl('move:0.1.0'))
    assert win.library_board.fen==expected.fen()
    assert 'variation' in win.review_label.text()
    win.close();win.deleteLater();app.processEvents()


def test_black_to_move_nonstandard_fen_numbering_and_empty_game():
    app=QApplication.instance() or QApplication([])
    game=chess.pgn.Game();view=NotationView();view.show_game(game)
    assert view.paths==[()]
    board=chess.Board();board.push_san('e4');board.fullmove_number=17
    game.setup(board);game.add_main_variation(board.parse_san('e5'))
    view.show_game(game,(0,));assert '17' in view.toPlainText() and 'e5' in view.toPlainText()
    assert view.paths==[(),(0,)]
    view.close()
