"""User-reported Eric Rosen v1.6.23 stream capture, Oct 20, 2026."""
import io
import chess
import chess.pgn

from chessstream.results import extract_context, ContextStabilizer


ERIC_ROSEN_MOVES = """
[Event "YouTube Chess Recording"]
[Site "YouTube"]
[Date "2026.10.20"]
[Round "?"]
[White "V1.6.23"]
[Black "chess speedrun"]
[Result "*"]

{ Opening prefix guessed; earlier move order may differ. }
1. e4 { [%clk 0:09:59] } e5 { [%clk 0:09:58] }
2. Nf3 Nc6 3. Bc4 Bc5 4. c3 Nf6 5. d4 exd4
6. cxd4 Bb4+ 7. Nc3 Nxe4 8. d5 Nxf2
9. O-O Bxc3 10. Rxf2 Bd4 11. Nxd4 Nxd4
12. Qxd4 O-O 13. d6 cxd6 14. Bh6 gxh6
15. Rf3 Qb6 *
"""


def test_eric_rosen_capture_is_legal_and_has_no_artificial_queen_shuffles():
    game = chess.pgn.read_game(io.StringIO(ERIC_ROSEN_MOVES))
    assert game is not None and not game.errors
    board = chess.Board()
    for move in game.mainline_moves():
        assert move in board.legal_moves
        board.push(move)
    assert board.is_valid()
    assert len(list(game.mainline_moves())) == 30
    assert game.end().board().board_fen() == board.board_fen()


def test_software_version_and_stream_title_are_never_player_names():
    board=(100,150,420,420)
    clocks=[
        ('9:59',.99,(450,112,493,140)),
        ('9:57',.99,(450,580,493,604)),
    ]
    misleading=[
        ('V1.6.23',.99,(170,112,250,140)),
        ('chess speedrun',.99,(170,580,315,604)),
    ]
    o=extract_context(clocks+misleading,board,'white')
    assert o['clocks']['black'] == 599
    assert o['clocks']['white'] == 597
    assert not o['names']
    stabilizer=ContextStabilizer()
    for _ in range(5):
        assert not stabilizer.observe(o)['names']
    real=[
        ('actualBlack123',.99,(170,112,300,140)),
        ('actualWhite123',.99,(170,580,300,604)),
    ]
    names=extract_context(clocks+real,board,'white')['names']
    assert names=={'white':'actualWhite123','black':'actualBlack123'}
