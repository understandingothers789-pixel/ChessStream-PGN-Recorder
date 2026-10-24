import io
import chess
import chess.pgn
from chessstream.games import export_pgn


def test_stale_fen_headers_cannot_replace_standard_start_on_export():
    stale=chess.Board();stale.push_san('d4')
    pgn=export_pgn(chess.STARTING_FEN,['e2e4','e7e5'],{'FEN':stale.fen(),'SetUp':'1'})
    game=chess.pgn.read_game(io.StringIO(pgn))
    assert not game.errors and 'FEN' not in game.headers and 'SetUp' not in game.headers
    expected=chess.Board();expected.push_san('e4');expected.push_san('e5')
    assert game.end().board().fen()==expected.fen()


def test_explicit_setup_is_exported_from_actual_root():
    root=chess.Board();root.push_san('d4')
    pgn=export_pgn(root.fen(),['d7d5'],{'FEN':chess.STARTING_FEN,'SetUp':'0'})
    game=chess.pgn.read_game(io.StringIO(pgn))
    assert not game.errors and game.headers['FEN']==root.fen() and game.headers['SetUp']=='1'
    root.push_san('d5');assert game.end().board().fen()==root.fen()
