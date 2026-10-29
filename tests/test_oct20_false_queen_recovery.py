"""2026-10-20 observed regression: freshly detected 1.e4 replaced by an
older wrong-turn PGN, then background worker invented Qe2/c5/Qd1.

Also verifies that video labels and text from other tabs are not usernames.
"""
import chess

from chessstream.domain import Observation, Settings, utcnow
from chessstream.games import GameManager
from chessstream.reconstruction import Reconstructor
from chessstream.recovery import recover_gap
from chessstream.results import extract_context
from chessstream.storage import Store


def played(line):
    board=chess.Board()
    for san in line.split():
        board.push_san(san)
    return board


def test_fresh_e4_does_not_return_to_old_checkpoint_with_wrong_turn(tmp_path):
    store=Store(tmp_path)
    e4=played('e4')
    bad=chess.Board(f'{e4.board_fen()} w - - 0 1')
    archived=GameManager(store,Settings())
    archived._create(bad,utcnow())
    archived.headers.update(White='DoingMyBest',Black='BuiltDifferent')
    archived.persist()
    old_id=archived.current_id
    archived.finish()
    fresh=GameManager(store,Settings())
    obs=Observation.from_board(e4)
    fresh.process(obs)
    assert fresh.current_id!=old_id
    gid=fresh.current_id
    pair={'white':'DoingMyBest','black':'BuiltDifferent'}
    fresh.observe_context({'names':pair,'names_stable':True,
                           'clocks':{'white':599,'black':594}},utcnow())
    for _ in range(3):
        fresh.process(Observation.from_board(e4))
        assert fresh.current_id==gid
    assert fresh.rec.initial_fen==chess.STARTING_FEN
    assert 'e2e4' in fresh.rec.verified or any(
        'e2e4' in branch.moves for branch in fresh.rec.branches)
    assert store.game(old_id) is not None
    store.close()


def test_known_e4_turn_rejects_an_older_same_placement_white_turn_checkpoint(tmp_path):
    store=Store(tmp_path)
    e4=played('e4')
    bad=chess.Board(f'{e4.board_fen()} w - - 0 1')
    archived=GameManager(store,Settings())
    archived._create(bad,utcnow())
    archived.headers.update(White='DoingMyBest',Black='BuiltDifferent')
    archived.persist()
    gid=archived.current_id
    fresh=GameManager(store,Settings())
    pair={'white':'DoingMyBest','black':'BuiltDifferent'}
    fresh.observe_context({'names':pair,'names_stable':True},utcnow())
    assert not fresh._resume_initial_identity(Observation.from_board(e4),['e2e4'])
    assert fresh.current_id!=gid
    store.close()


def test_background_recovery_cannot_invent_queen_roundtrip_to_correct_turn():
    e4=played('e4')
    bad=chess.Board(f'{e4.board_fen()} w - - 0 1')
    c5=played('e4 c5')
    bad_state=Reconstructor(bad).serialize()
    result=recover_gap([bad_state],Observation.from_board(c5),
                       max_plies=4,node_limit=60000,time_limit_ms=1500)
    assert result is None, 'Unobserved Qe2 c5 Qd1 must not become verified PGN'
    good_state=Reconstructor(e4).serialize()
    recovered=recover_gap([good_state],Observation.from_board(c5),
                          max_plies=2,node_limit=60000,time_limit_ms=1500)
    assert recovered is not None
    assert recovered[1]['verified']==['c7c5']


def test_unrelated_ocr_from_other_tabs_and_pgn_move_list_is_not_a_player():
    board=(200,180,700,700)
    fake=['Create Python tool to optimize prompts','CANDIDATE SLOWKARU I',
          'Work with Codex','Downloads-File Explorer','14... gxh6 15. Rf3 15... Qb6',
          'No']
    for title in fake:
        lines=[(title,.99,(230,90,530,115))]
        assert extract_context(lines,board,'white')['names']=={},title
    authentic=[('DoingMyBest (1673)',.99,(230,90,460,115)),
               ('BuiltDifferent (1671)',.99,(230,900,470,920))]
    assert extract_context(authentic,board,'white')['names']=={
        'black':'DoingMyBest','white':'BuiltDifferent'}
