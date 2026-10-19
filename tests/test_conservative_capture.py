"""Held legal hovers, transient-path recovery, and position-based storage."""
from pathlib import Path
import io
import json
import chess
import chess.pgn
import cv2
import numpy as np
import pytest
from chessstream.domain import Observation,Settings,utcnow
from chessstream.reconstruction import Reconstructor,LegalSearcher,Branch
from chessstream.games import GameManager
from chessstream.storage import Store
from chessstream.vision import ScreenshotRecognizer


def play(board,line):
    for san in line.split():board.push_san(san)
    return board


def test_five_second_legal_hover_is_never_verified_and_final_bishop_square_wins():
    initial=play(chess.Board(),'e4 e5 Nf3 Nc6 Nc3')
    rec=Reconstructor(initial,confirmation_plies=1)
    hover=play(initial.copy(),'Bc5')
    for second in range(6):
        obs=Observation.from_board(hover);obs.timestamp=f'2026-10-18T12:00:0{second}+00:00'
        assert not rec.observe(obs).verified
        assert rec.verified==[]
    actual=play(initial.copy(),'Bb4')
    rec.observe(Observation.from_board(actual))
    assert not rec.verified
    assert rec.branches[0].moves==('f8b4',)
    actual.push_san('a3');rec.observe(Observation.from_board(actual))
    assert rec.verified==['f8b4']
    assert rec.branches[0].moves==('a2a3',)
    assert 'f8c5' not in rec.verified


def test_return_to_source_cancels_provisional_piece_move():
    initial=chess.Board();rec=Reconstructor(initial,confirmation_plies=1)
    rec.observe(Observation.from_board(play(initial.copy(),'Nf3')))
    rec.observe(Observation.from_board(initial))
    assert rec.verified==[] and rec.branches[0].moves==()
    rec.observe(Observation.from_board(play(initial.copy(),'e4 e5')))
    assert rec.verified==['e2e4']


def test_reported_bb6_position_recovers_without_an_unseen_bishop_cycle():
    initial=play(chess.Board(),'e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6')
    actual=play(initial.copy(),'Ng5 Nh6 Qf3')
    speculative=play(initial.copy(),'Be6 Bd4 Bc4 Bb6 Ng5 Nh6 Qf3')
    assert speculative.board_fen()==actual.board_fen()
    rec=Reconstructor(initial,confirmation_plies=1)
    bogus=tuple(m.uci() for m in speculative.move_stack[len(initial.move_stack):])
    genuine=tuple(m.uci() for m in actual.move_stack[len(initial.move_stack):])
    rec.branches=[Branch(initial.fen(),bogus),Branch(initial.fen(),genuine)]
    update=rec.observe(Observation.from_board(actual))
    assert update.recovered
    assert rec.verified==['f3g5','g8h6']
    assert rec.branches[0].moves==('d1f3',)
    assert not any(m in rec.verified for m in ['c4e6','b6d4'])


def test_pending_move_and_confirmation_policy_survive_restart():
    rec=Reconstructor(chess.Board(),confirmation_plies=1)
    rec.observe(Observation.from_board(play(chess.Board(),'e4')))
    restored=Reconstructor.restore(rec.serialize())
    assert restored.confirmation_plies==1 and not restored.verified
    restored.observe(Observation.from_board(play(chess.Board(),'e4 e5')))
    assert restored.verified==['e2e4']


def test_provisional_final_move_is_not_exported_or_auto_promoted(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board()
    manager.process(Observation.from_board(board))
    for san in 'f3 e5 g4 Qh4#'.split():
        board.push_san(san);manager.process(Observation.from_board(board))
    snap=manager.snapshot()
    assert snap['provisional'] and snap['pending_moves']==['Qh4#']
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert len(list(game.mainline_moves()))==3 and game.headers['Result']=='*'
    manager.choose(0)
    game=chess.pgn.read_game(io.StringIO(store.game(manager.current_id)['pgn']))
    assert len(list(game.mainline_moves()))==4 and game.headers['Result']=='0-1'
    store.close()


def test_real_arrow_cursor_and_texture_changes_save_only_one_position(tmp_path):
    store=Store(tmp_path);sid=store.session();model=ScreenshotRecognizer()
    root=Path(__file__).parent/'fixtures/themes'
    processed=0
    for name in ['chesscom-ocean-05.png','chesscom-ocean-burled.png','chesscom-ocean-arrows.png','chesscom-ocean-cursor.png']:
        image=cv2.imread(str(root/name));obs=model.recognize(image,'black');processed+=1
        store.save_screenshot(sid,None,image,utcnow(),obs.placement(),obs.confidence,deduplicate_position=True)
    assert processed==4 and len(store.screenshots())==1
    image=cv2.imread(str(root/'chesscom-ocean-06.png'));obs=model.recognize(image,'black')
    assert store.save_screenshot(sid,None,image,utcnow(),obs.placement(),obs.confidence,deduplicate_position=True)
    assert len(store.screenshots())==2
    store.close()


def test_repeated_positions_are_kept_when_position_changes_but_same_position_is_session_deduped(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());board=chess.Board();manager.process(Observation.from_board(board));sid=manager.session_id;gid=manager.current_id;image=np.zeros((80,80,3),np.uint8)
    for san in ['']+'Nf3 Nf6 Ng1 Ng8'.split():
        if san:board.push_san(san)
        assert store.save_screenshot(sid,gid,image,utcnow(),board.board_fen(),deduplicate_position=True)
    second=GameManager(store,Settings(),sid);second.process(Observation.from_board(board))
    assert store.save_screenshot(sid,second.current_id,image,utcnow(),board.board_fen(),deduplicate_position=True) is None
    assert len(store.screenshots())==5
    store.close()


def test_position_dedup_ignores_layout_images_without_recognized_fen(tmp_path):
    store=Store(tmp_path);manager=GameManager(store,Settings());manager.process(Observation.from_board(chess.Board()))
    sid,gid=manager.session_id,manager.current_id;image=np.zeros((80,80,3),np.uint8)
    start=chess.Board().board_fen()
    assert store.save_screenshot(sid,gid,image,utcnow(),start,deduplicate_position=True)
    assert store.save_screenshot(sid,gid,image,utcnow(),None,deduplicate_position=True)
    assert store.save_screenshot(sid,gid,image,utcnow(),start,deduplicate_position=True) is None
    assert len(store.screenshots())==2
    store.close()


def test_old_settings_gain_safe_defaults_without_enabling_deletion(tmp_path):
    path=tmp_path/'settings.json';path.write_text(json.dumps({'interval':1,'deduplicate':False}))
    settings=Settings.load(path)
    assert settings.confirm_on_reply and settings.screenshot_mode=='positions'
    assert settings.retention_days==0


def test_unknown_destination_cannot_be_used_to_prove_a_move():
    initial=chess.Board();obs=Observation.from_board(play(initial.copy(),'e4'))
    for square in [chess.E3,chess.E4]:obs.probabilities[square]=1/13
    # The pawn disappeared from e2, but neither possible destination is visible.
    result=LegalSearcher(max_plies=1).search(initial,obs)
    assert result.exhaustive and not result.paths


CASES=json.loads((Path(__file__).parent/'fixtures/confirmation/manifest.json').read_text())['cases']


def test_old_recording_recovers_three_missed_plies_from_real_arrow_frame(tmp_path):
    # The visible e4 position uniquely proves the first opening move from the
    # standard start, so the recovered prefix now includes 1.e4 as well.
    initial=chess.Board('rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b - - 0 1')
    store=Store(tmp_path);old=GameManager(store,Settings(confirm_on_reply=False))
    old.process(Observation.from_board(initial));board=initial.copy()
    for san in 'e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6'.split():
        board.push_san(san);old.process(Observation.from_board(board))
    prefix=list(old.rec.verified);assert len(prefix)==10
    alternatives=[]
    for line in ['Be6 Bd4 Bc4 Bb6 Ng5 Nh6 Qf3','Ng5 Nh6 Qf3']:
        leaf=board.copy(stack=False);play(leaf,line)
        alternatives.append(Branch(board.fen(),tuple(m.uci() for m in leaf.move_stack)))
    old.rec.branches=alternatives;old.persist();gid=old.current_id
    state=json.loads(store.game(gid)['state']);state.pop('confirmation_plies')
    with store.transaction() as db:db.execute('UPDATE games SET state=? WHERE id=?',(json.dumps(state),gid))
    store.close()
    store=Store(tmp_path);resumed=GameManager(store,Settings());resumed.recover(gid)
    assert resumed.rec.confirmation_plies==1
    image=cv2.imread(str(Path(__file__).parent/'fixtures/confirmation/italian-arrows.png'))
    resumed.process(ScreenshotRecognizer().recognize(image,'black'))
    assert resumed.rec.verified==prefix+['f3g5','g8h6']
    assert resumed.snapshot()['pending_moves']==['Qf3']
    assert store.query("SELECT * FROM audit WHERE action='transient candidate replaced'")
    store.close()


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_native_chesscom_drag_and_reported_italian_arrows(case,tmp_path):
    root=Path(__file__).parent/'fixtures/confirmation';model=ScreenshotRecognizer()
    store=Store(tmp_path);manager=GameManager(store,Settings(initial_fen=case['initial_fen']))
    for frame in case['frames']:
        obs=model.recognize(cv2.imread(str(root/frame['file'])),'black')
        for _ in range(8 if frame['kind']=='hover' else 1):
            manager.process(obs)
            if frame['kind']=='hover':assert not manager.rec.verified
        if case['id']=='italian' and frame['kind']=='annotation':
            assert manager.rec.verified==['f3g5','g8h6']
    if case['id']=='italian':
        assert manager.rec.verified==['f3g5','g8h6','d1f3']
        assert manager.rec.branches[0].moves==('d7d6',)
    else:
        assert manager.rec.verified==['f8b4']
        assert manager.rec.branches[0].moves==('a2a3',)
    store.close()


def test_supported_shared_prefix_does_not_wait_for_ambiguous_later_order():
    initial=chess.Board()
    a=play(initial.copy(),'e4 e5 Nf3 Nc6 Nc3 Nf6')
    b=play(initial.copy(),'e4 e5 Nc3 Nf6 Nf3 Nc6')
    assert a.board_fen()==b.board_fen()
    rec=Reconstructor(initial,LegalSearcher(max_plies=1),confirmation_plies=1)
    rec.branches=[Branch(initial.fen(),tuple(m.uci() for m in board.move_stack)) for board in [a,b]]
    rec.observe(Observation.from_board(a))
    assert rec.verified==['e2e4','e7e5']
    assert len(rec.branches)==2  # Different later move orders remain unresolved.
