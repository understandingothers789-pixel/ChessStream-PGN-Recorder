"""Video seeking at the start of a streamed game must not invent retreats.

Observed 2026-10-20: recording started after e4 c5 Nf3 Nc6, video hid
the board during a seek, then settled at e4 c5 Nf3. The earlier version
automatically committed the bogus c6b8 after 0.82 seconds.
"""
import chess

from chessstream.domain import Observation, Settings, utcnow
from chessstream.games import GameManager
from chessstream.reconstruction import Branch, Reconstructor, LegalSearcher
from chessstream.storage import Store


def board(line):
    b=chess.Board()
    for san in line.split(): b.push_san(san)
    return b


def test_midopening_video_rewind_cannot_commit_false_nb8(tmp_path):
    store=Store(tmp_path)
    m=GameManager(store,Settings())
    now=[100.]
    m._clock=lambda:now[0]
    four=board('e4 c5 Nf3 Nc6')
    early=board('e4 c5 Nf3')
    m._create(four,utcnow(),note='Recording began midgame. Earlier moves are unavailable.')
    gid=m.current_id
    snapshot=m.process(Observation.from_board(early))
    now[0]=101.
    snapshot=m.process(Observation.from_board(early))
    now[0]=103.
    snapshot=m.process(Observation.from_board(early))
    assert m.current_id==gid
    assert m.rec.verified==[],m.rec.verified
    assert snapshot['lifecycle']['state'] in ('analysis / replay','game in progress','uncertain transition')
    assert 'c6b8' not in m.rec.verified
    assert 'c6b8' not in store.game(gid)['pgn']
    store.close()


def test_rewind_to_witnessed_e4_rebases_midopening_in_same_record(tmp_path):
    store=Store(tmp_path)
    m=GameManager(store,Settings())
    m._create(board('e4 c5 Nf3 Nc6'),utcnow(),
              note='Recording began midgame. Earlier moves are unavailable.')
    gid=m.current_id
    first=board('e4')
    m.process(Observation.from_board(first))
    m.process(Observation.from_board(first))
    assert m.current_id==gid
    assert m.rec.initial_fen==chess.STARTING_FEN
    assert ('e2e4' in m.rec.verified
            or any('e2e4' in b.moves for b in m.rec.branches))
    assert len(store.games())==1
    # From this point the following c5 has a consistent black-to-move root.
    after=board('e4 c5')
    m.process(Observation.from_board(after))
    assert m.current_id==gid and len(store.games())==1
    assert m.rec.initial_fen==chess.STARTING_FEN
    store.close()


def test_rewind_to_standard_start_corrects_an_unverified_opening_fen(tmp_path):
    store=Store(tmp_path)
    m=GameManager(store,Settings())
    m._create(board('e4 c5 Nf3 Nc6'),utcnow())
    gid=m.current_id
    m.process(Observation.from_board(chess.Board()))
    m.process(Observation.from_board(chess.Board()))
    assert m.current_id==gid
    assert m.rec.initial_fen==chess.STARTING_FEN
    assert not m.rec.verified
    store.close()


def test_settle_timeout_must_not_choose_between_equally_good_knight_orders(tmp_path):
    store=Store(tmp_path)
    m=GameManager(store,Settings())
    m._create(chess.Board(),utcnow())
    root=chess.Board()
    def path(line):
        x=root.copy()
        moves=[]
        for san in line.split():
            move=x.parse_san(san);moves.append(move.uci());x.push(move)
        return tuple(moves),x
    left,target=path('Nf3 Nf6 Nc3 Nc6')
    right,alternate=path('Nc3 Nc6 Nf3 Nf6')
    assert target.board_fen()==alternate.board_fen()
    m.rec.branches=[Branch(root.fen(),left),Branch(root.fen(),right)]
    now=[10.]
    m._clock=lambda:now[0]
    m._settle_position(Observation.from_board(target))
    now[0]+=2
    m._settle_position(Observation.from_board(target))
    assert len(m.rec.verified)==0
    assert len(m.rec.branches)==2
    store.close()


def test_canceling_queen_detour_releases_confirmation_lock():
    base=board('e4 e5 Nf3 Nc6')
    trial=base.copy()
    moves=[]
    for san in 'Qe2 Nf6 Qd1'.split():
        move=trial.parse_san(san);moves.append(move.uci());trial.push(move)
    rec=Reconstructor(base,LegalSearcher(max_plies=4),confirmation_plies=0)
    rec.branches=[Branch(base.fen(),tuple(moves))]
    rec.gap_requires_confirmation=True
    rec.observe(Observation.from_board(base))
    assert rec.gap_requires_confirmation is False
    assert rec.branches[0].moves==()
    follow=base.copy();follow.push_san('Be2')
    rec.observe(Observation.from_board(follow))
    assert rec.verified==[base.parse_san('Be2').uci()]
