"""Essential recording, gap, ambiguity, result and PGN export regressions."""
import io
import chess
import chess.pgn
from chessstream.domain import Settings,Observation
from chessstream.storage import Store
from chessstream.games import GameManager,export_pgn
from chessstream.reconstruction import LegalSearcher
from chessstream.gap_join import join_recordings

PREFIX='e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4 cxd4'


def record(store,settings,line):
    manager=GameManager(store,settings);board=chess.Board()
    manager.process(Observation.from_board(board))
    for san in line.split():board.push_san(san);manager.process(Observation.from_board(board))
    return manager,board


def test_queen_capture_gap_resumes_latest_with_or_without_pending_move_and_labels_inference(tmp_path):
    for pending in (False,True):
        store=Store(tmp_path/str(pending));settings=Settings(confirm_on_reply=pending)
        first,board=record(store,settings,PREFIX);gid=first.current_id;first.finish()
        board.push_san('Qxd4');resumed=GameManager(store,settings)
        resumed.process(Observation.from_board(board))
        assert resumed.current_id==gid and len(store.games())==1
        board.push_san('Ne7');resumed.process(Observation.from_board(board))
        if pending:resumed.choose(0)
        game=chess.pgn.read_game(io.StringIO(store.game(gid)['pgn']))
        nodes=list(game.mainline())
        assert not game.errors and game.end().board().fen()==board.fen()
        assert 'Inferred across capture gap' in nodes[10].comment
        assert all('Inferred across capture gap' not in node.comment for node in nodes[:10])
        restored=GameManager(store,settings);restored.recover(gid)
        assert restored.inferred_moves['11']['uci']=='d1d4'
        store.close()


def test_live_multi_move_gap_keeps_one_game_and_hovers_remain_provisional(tmp_path):
    store=Store(tmp_path);manager,board=record(store,Settings(),'e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6')
    gid=manager.current_id
    for san in 'Ng5 Nh6 Qf3'.split():board.push_san(san)
    manager.process(Observation.from_board(board))
    assert manager.current_id==gid and manager.snapshot()['pending_moves']==['Qf3']
    assert manager.rec.verified[-2:]==['f3g5','g8h6']
    for _ in range(3):manager.process(Observation.from_board(board))
    assert manager.snapshot()['pending_moves']==['Qf3']
    assert len(store.games())==1
    assert 'Inferred across capture gap' in store.game(gid)['pgn']
    rewind=chess.Board()
    for san in 'e4 e5 Nf3'.split():rewind.push_san(san)
    restored=GameManager(store,Settings());restored.process(Observation.from_board(rewind))
    assert restored.current_id==gid and restored.rec.verified==manager.rec.verified
    assert 'Review position' in restored.last_message
    store.close()


def test_resumed_equal_shortest_lines_choose_one_deterministically(tmp_path):
    store=Store(tmp_path);first,board=record(store,Settings(),'');first.finish()
    for san in 'Nf3 Nf6 Nc3 Nc6'.split():board.push_san(san)
    resumed=GameManager(store,Settings());resumed.process(Observation.from_board(board))
    assert resumed.current_id==first.current_id and len(store.games())==1
    assert len(resumed.rec.branches)==1
    assert resumed.rec.branches[0].board().board_fen()==board.board_fen()
    assert 'Equal shortest legal paths reached this position' in store.game(first.current_id)['pgn']
    target=chess.pgn.Game();target.setup(board)
    rows=[dict(id='a',started='2026-10-19T10:00:00',pgn=export_pgn(chess.STARTING_FEN,[],{'Result':'*'})),
          dict(id='b',started='2026-10-19T10:04:00',pgn=str(target))]
    joined=chess.pgn.read_game(io.StringIO(join_recordings(rows,LegalSearcher())))
    assert not joined.errors and joined.end().board().board_fen()==board.board_fen()
    assert len(list(joined.mainline_moves()))==4
    store.close()


def test_terminal_game_and_unrelated_opening_remain_separate(tmp_path):
    store=Store(tmp_path/'mate');manager,board=record(store,Settings(confirm_on_reply=False),'f3 e5 g4 Qh4#')
    gid=manager.current_id;assert manager.headers['Result']=='0-1'
    manager.process(Observation.from_board(chess.Board()))
    assert manager.current_id!=gid and len(store.games())==2
    store.close()
    store=Store(tmp_path/'reset');first,_=record(store,Settings(confirm_on_reply=False),'e4')
    other=chess.Board();other.push_san('d4')
    second=GameManager(store,Settings());second.process(Observation.from_board(other))
    assert second.current_id!=first.current_id and len(store.games())==2
    store.close()


def test_join_saved_segments_fills_qxd4_and_preserves_clocks_and_variations():
    source=chess.Board();moves=[]
    for san in PREFIX.split():move=source.parse_san(san);moves.append(move.uci());source.push(move)
    target=source.copy();target.push_san('Qxd4')
    later=chess.pgn.Game();later.setup(chess.Board(f'{target.board_fen()} b - - 0 1'));node=later
    for san in 'Ne7 Nf3 Nbc6 Qf4'.split():
        move=target.parse_san(san);node=node.add_variation(move);target.push(move)
    later.variations[0].set_clock(444)
    later.add_variation(chess.Move.from_uci('g8f6')).comment='Review alternative'
    rows=[dict(id='a',started='2026-10-19T10:00:00',pgn=export_pgn(chess.STARTING_FEN,moves,{'White':'YO MAMA','Result':'*'})),
          dict(id='b',started='2026-10-19T10:04:00',pgn=str(later))]
    original=[row['pgn'] for row in rows]
    joined=chess.pgn.read_game(io.StringIO(join_recordings(rows,LegalSearcher())))
    nodes=list(joined.mainline())
    assert not joined.errors and len(nodes)==15 and joined.end().board().fen()==target.fen()
    assert nodes[10].san()=='Qxd4' and 'Inferred across recording gap' in nodes[10].comment
    assert nodes[11].clock()==444 and len(nodes[10].variations)==2
    assert [row['pgn'] for row in rows]==original
