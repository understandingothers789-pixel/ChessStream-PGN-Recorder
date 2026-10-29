import chess
from chessstream.domain import Observation,Settings,utcnow
from chessstream.games import GameManager
from chessstream.storage import Store


def played(line):
    b=chess.Board()
    for san in line.split():b.push_san(san)
    return b


def test_ambiguous_five_ply_start_does_not_resume_same_players_archive(tmp_path):
    store=Store(tmp_path);old=GameManager(store,Settings(confirm_on_reply=False))
    old._create(chess.Board(),utcnow());old.correct_line('d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O')
    old.headers.update(White='Streamer',Black='Opponent');old.finish();old_id=old.current_id
    original=store.game(old_id)['pgn']
    fresh=GameManager(store,Settings(confirm_on_reply=False))
    fresh.lifecycle.names={'white':'Streamer','black':'Opponent'}
    fresh.lifecycle.raw_names=dict(fresh.lifecycle.names)
    target=played('d4 Nf6 c4 e6 Nc3')
    fresh.process(Observation.from_board(target))
    assert fresh.current_id!=old_id and store.game(old_id)['pgn']==original
    assert not fresh.rec.board.turn and fresh.rec.board.fullmove_number==3
    assert fresh.rec.board.castling_rights==target.castling_rights
    assert not fresh.rec.verified  # Earlier order remains uncertain, not fabricated.
    for san in ('Bb4','e3','O-O'):
        target.push_san(san);fresh.process(Observation.from_board(target))
    assert fresh.rec.verified==['f8b4','e2e3','e8g8']
    assert fresh.rec.board.board_fen()==target.board_fen()
    assert fresh.current_id!=old_id and store.game(old_id)['pgn']==original
    store.close()


def test_incomplete_early_search_cannot_establish_side_to_move(tmp_path,monkeypatch):
    from chessstream.reconstruction import SearchResult
    store=Store(tmp_path);m=GameManager(store,Settings())
    monkeypatch.setattr('chessstream.games.LegalSearcher.search',lambda *a,**k:SearchResult(exhaustive=False))
    assert m._early_start_turn(Observation.from_board(played('d4 Nf6 c4 e6 Nc3'))) is None
    assert not m._early_inferred_roots
    store.close()


def test_search_budget_miss_does_not_make_opening_an_archive_identity(tmp_path,monkeypatch):
    store=Store(tmp_path);old=GameManager(store,Settings(confirm_on_reply=False))
    old._create(chess.Board(),utcnow());old.correct_line('d4 Nf6 c4 e6 Nc3 Bb4')
    old.headers.update(White='Streamer',Black='Opponent');old.finish();old_id=old.current_id
    fresh=GameManager(store,Settings())
    fresh.lifecycle.names={'white':'Streamer','black':'Opponent'};fresh.lifecycle.raw_names=dict(fresh.lifecycle.names)
    monkeypatch.setattr(fresh,'_early_start_turn',lambda obs:None)
    fresh.process(Observation.from_board(played('d4 Nf6 c4 e6 Nc3')))
    assert fresh.current_id!=old_id
    assert {branch.board().turn for branch in fresh.rec.branches}=={chess.WHITE,chess.BLACK}
    store.close()


def test_logged_late_positions_and_missing_dragged_queen_do_not_force_detours(tmp_path):
    # The pasted log omits the game's initial FEN/history. This replay checks
    # the witnessed local transitions using the consistent White-to-move root;
    # it does not assert that the old 43-ply prefix can be repaired from the log.
    from chessstream.capture import RecordingWorker
    from chessstream.domain import Region
    store=Store(tmp_path);m=GameManager(store,Settings(confirm_on_reply=False))
    board=chess.Board('2r1b1k1/pp3pbp/2n1p1p1/8/4N3/P3PN1Q/1qBR1PPP/6K1 w - - 0 1')
    m._create(board,utcnow());gid=m.current_id;clock=[100.];m._clock=lambda:clock[0]
    worker=RecordingWorker(m,Region(0,0,500,500))
    line=['e4g5','b2c1','c2d1','c8d8','h3h7','g8f8','d2d8','c6d8','h2h3','c1d1','g1h2']
    for index,uci in enumerate(line):
        move=chess.Move.from_uci(uci);assert move in board.legal_moves;board.push(move)
        # Preserve the same skipped pairs as the log's captured placements.
        if index in (0,4,6):continue
        clock[0]+=1;worker.process_observation(Observation.from_board(board),2)
    assert m.rec.verified==line and m.current_id==gid
    missing=board.copy();missing.remove_piece_at(chess.D1)
    clock[0]+=1;worker.process_observation(Observation.from_board(missing),2)
    assert m.rec.verified==line
    board.push_uci('d1d6');clock[0]+=1
    worker.process_observation(Observation.from_board(board),2)
    assert m.rec.verified==line+['d1d6'] and m.current_id==gid
    m.cancel_background_recovery();m.cancel_saved_join();store.close()
