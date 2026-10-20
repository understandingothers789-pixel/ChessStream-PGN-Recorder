"""Regression for the SukunaTakingOver / ItadoriClueless gap.

Uses the exact 25.Bb5 endpoint and the later nonstandard FEN, with the
recorded move prefix. This deliberately does not assert guessed gap history.
"""
import io
from unittest.mock import patch
import chess
import chess.pgn
import pytest

from chessstream.gap_join import AmbiguousGapError, join_recordings
from chessstream.reconstruction import SearchResult

SOURCE_FEN = "r3r1k1/1p1qppbp/p1n2np1/1B1p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 b - - 1 25"
TARGET_FEN = "r3r1k1/3qppbp/p1p2np1/3p2N1/3P1B2/1Q2P2P/PP3PP1/2R2RK1 w - - 0 1"
PREFIX = """[Event "YouTube Chess Recording"]
[Site "YouTube"]
[Date "2026.10.20"]
[White "SukunaTakingOver"]
[Black "ItadoriClueless"]
[Result "*"]

1. d4 Nf6 2. Bf4 g6 3. e3 Bg7 4. h3 d6 5. Nf3 O-O
6. Be2 Bf5 7. O-O Be4 8. c4 Re8 9. Nc3 c6
10. Qb1 Bd5 11. Qe4 Be6 12. Qc2 Bd5 13. Qb3 Be4
14. Ng5 Qd7 15. Nd5 Qd8 16. Nc3 d5 17. cxd5 Qd7
18. Ncxe4 Qd6 19. Nc3 Qd7 20. d6 Qxd6
21. Nd5 Qd7 22. Rac1 cxd5 23. Qa3 Nc6
24. Qb3 a6 25. Bb5 *
"""
LATER = f"""[Event "YouTube Chess Recording"]
[Site "YouTube"]
[Date "2026.10.20"]
[White "SukunaTakingOver"]
[Black "Itadoriclueless"]
[Result "*"]
[SetUp "1"]
[FEN "{TARGET_FEN}"]

{{ Segment note and timestamp retained. }}
1. Rc2 {{ [%clk 0:08:57] }} 1... Rec8 *
"""


def prefix_board():
    game = chess.pgn.read_game(io.StringIO(PREFIX))
    assert game is not None and not game.errors, game.errors if game else ""
    return game.end().board()


def witness(board, san):
    state = board.copy()
    path = []
    for token in san.split():
        move = state.parse_san(token)
        path.append(move)
        state.push(move)
    assert state.board_fen() == chess.Board(TARGET_FEN).board_fen()
    assert state.turn == chess.WHITE
    assert state.castling_rights == 0
    return tuple(path)


def test_exact_endpoints_and_material():
    before = prefix_board()
    after = chess.Board(TARGET_FEN)
    assert before.board_fen() == chess.Board(SOURCE_FEN).board_fen()
    assert before.turn == chess.BLACK
    assert after.turn == chess.WHITE
    assert before.castling_rights == after.castling_rights == 0
    assert before.occupied_co[chess.WHITE].bit_count() == 14
    assert before.occupied_co[chess.BLACK].bit_count() == 14
    assert after.occupied_co[chess.WHITE].bit_count() == 13
    assert after.occupied_co[chess.BLACK].bit_count() == 13


def test_two_distinct_legal_seven_ply_bridges():
    before = prefix_board()
    a = witness(before, "Qd8 Qa4 Qc7 Qb3 Qd7 Bxc6 bxc6")
    b = witness(before, "Qd8 Qc2 Qc7 Qb3 Qd7 Bxc6 bxc6")
    assert a != b and len(a) == len(b) == 7


def test_ambiguous_join_does_not_alter_input_or_pick_arbitrary_path():
    before = prefix_board()
    a = witness(before, "Qd8 Qa4 Qc7 Qb3 Qd7 Bxc6 bxc6")
    b = witness(before, "Qd8 Qc2 Qc7 Qb3 Qd7 Bxc6 bxc6")
    rows = [
        {"id": 1, "started": "2026-10-20T01:00:00", "pgn": PREFIX},
        {"id": 2, "started": "2026-10-20T01:10:00", "pgn": LATER},
    ]
    originals = [row["pgn"] for row in rows]
    class DummySearcher:
        max_plies=4
        node_limit=60000
        time_limit_ms=350
        threshold=.70
        path_limit=128
    with patch("chessstream.gap_join._gap_search",
               return_value=SearchResult(paths=[a,b], exhaustive=True, shortest_proven=True)):
        with pytest.raises(AmbiguousGapError) as error:
            join_recordings(rows, DummySearcher())
    assert len(error.value.alternatives) == 2
    assert [row["pgn"] for row in rows] == originals
