"""Small independent correctness checks for the bounded shortest-path search."""
import itertools
import chess
from chessstream.domain import Observation
from chessstream.reconstruction import LegalSearcher,Reconstructor,select_capture_path


def play(board,line):
    for san in line.split():board.push_san(san)
    return board


def oracle(board,target):
    """Unpruned two-ply enumeration, independent of production pruning."""
    for depth in range(3):
        found=set()
        def visit(state,left,path):
            if not left:
                if state.board_fen()==target.board_fen():found.add(tuple(path))
                return
            for move in list(state.legal_moves):
                state.push(move);visit(state,left-1,path+[move.uci()]);state.pop()
        visit(board.copy(),depth,[])
        if found:return found
    return set()


def test_shortest_search_matches_independent_oracle_for_moves_and_special_rules():
    cases=[(chess.STARTING_FEN,'e4 e5'),(chess.STARTING_FEN,'Nf3 Nf6'),
           ('r3k2r/ppp2ppp/2n5/3pp3/3PP3/2N5/PPP2PPP/R3K2R w KQkq - 0 10','O-O O-O-O'),
           ('7k/P7/8/8/8/8/8/7K w - - 0 1','a8=N'),
           ('7k/8/8/3pP3/8/8/8/7K w - d6 0 1','exd6')]
    for fen,line in cases:
        source=chess.Board(fen);target=play(source.copy(),line)
        result=LegalSearcher(4).search(source,Observation.from_board(target))
        assert result.exhaustive
        assert {tuple(m.uci() for m in path) for path in result.paths}==oracle(source,target)
        assert source.fen()==fen


def test_equal_shortest_orders_stay_distinct_and_limits_or_hidden_squares_are_not_proof():
    target=play(chess.Board(),'Nf3 Nf6 Nc3 Nc6')
    result=LegalSearcher(4).search(chess.Board(),Observation.from_board(target))
    expected={tuple(itertools.chain.from_iterable(zip(w,b)))
              for w in itertools.permutations(('g1f3','b1c3'))
              for b in itertools.permutations(('g8f6','b8c6'))}
    assert result.exhaustive and {tuple(m.uci() for m in p) for p in result.paths}==expected
    assert not LegalSearcher(4,node_limit=1).search(chess.Board(),Observation.from_board(target)).exhaustive
    hidden=Observation.from_board(play(chess.Board(),'e4'))
    hidden.probabilities[[chess.E3,chess.E4]]=1/13
    assert not LegalSearcher(1).search(chess.Board(),hidden).paths
    assert not LegalSearcher(1).search(chess.Board(),Observation.from_board(chess.Board()),target_turn=chess.BLACK).paths


def test_gap_probe_preserves_prefix_pending_policy_and_unchanged_state_on_failure():
    source=play(chess.Board(),'e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4')
    rec=Reconstructor(source,confirmation_plies=1)
    source.push_san('cxd4');rec.observe(Observation.from_board(source))
    source.push_san('Qxd4')
    assert rec.bridge_gap(Observation.from_board(source)) is not None
    assert rec.verified==['c5d4'] and rec.branches[0].moves==('d1d4',)
    previous=rec.serialize()
    distant=play(source.copy(),'Ne7 Nf3 Nbc6')
    assert rec.bridge_gap(Observation.from_board(distant),LegalSearcher(4,node_limit=1)) is None
    assert rec.serialize()==previous


def test_backward_pawn_positions_are_rejected_before_expanding_a_gap_tree():
    source=play(chess.Board(),'e4');target=play(chess.Board(),'d4')
    result=LegalSearcher(6).search(source,Observation.from_board(target))
    assert result.exhaustive and not result.paths and result.nodes==0


def test_capture_recapture_is_the_preferred_equal_length_tiebreak():
    source=play(chess.Board(),'e4 e6 d4 d5 e5 c5 Bb5+ Bd7 a4')
    first=source.parse_san('cxd4')
    after_capture=source.copy();after_capture.push(first)
    recapture=[first,after_capture.parse_san('Qxd4')]
    quiet=[first,after_capture.parse_san('Nc3')]
    selected=select_capture_path(source,[quiet,recapture])
    assert selected==[recapture]
