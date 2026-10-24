"""Small independent correctness checks for the bounded shortest-path search."""
import itertools
import random
import chess
from chessstream.domain import Observation
from chessstream.reconstruction import LegalSearcher,Reconstructor,select_capture_path,speculative_detour


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
           ('7k/8/8/3pP3/8/8/8/7K w - d6 0 1','exd6'),
           # No white target is missing before Rc2: its last move can still
           # sacrifice a piece that disappears on the opponent's final turn.
           ('8/8/8/8/8/2k5/R7/7K w - - 0 1','Rc2+ Kxc2'),
           ('1r5k/P7/8/8/8/8/8/7K w - - 0 1','axb8=N Kg7')]
    for fen,line in cases:
        source=chess.Board(fen);target=play(source.copy(),line)
        result=LegalSearcher(4).search(source,Observation.from_board(target))
        assert result.exhaustive
        assert {tuple(m.uci() for m in path) for path in result.paths}==oracle(source,target)
        assert source.fen()==fen


def test_final_move_filter_matches_unpruned_moves_with_partial_observations():
    """Exercise every legal move, including moves hidden by low confidence."""
    sources=[chess.Board(fen) for fen in (
        chess.STARTING_FEN,
        'r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',
        'r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1',
        '7k/8/8/3pP3/8/8/8/7K w - d6 0 1',
        '7k/8/8/8/3Pp3/8/8/7K b - d3 0 1',
        '1r5k/P7/8/8/8/8/8/7K w - - 0 1',
        '7k/8/8/8/8/8/p7/1R5K b - - 0 1')]
    randomizer=random.Random(20261023)
    state=chess.Board()
    for index in range(48):
        if state.is_game_over():break
        state.push(randomizer.choice(list(state.legal_moves)))
        if index%8==7:sources.append(state.copy(stack=False))
    for source in sources:
        original=source.fen()
        endpoints=[]
        for move in source.legal_moves:
            endpoint=source.copy(stack=False);endpoint.push(move)
            endpoints.append((move,endpoint))
        for move,target in endpoints:
            for hidden in ((),randomizer.sample(range(64),4)):
                observed=Observation.from_board(target)
                if hidden:observed.probabilities[list(hidden)]=1/13
                expected=set()
                for candidate,endpoint in endpoints:
                    # Low-confidence squares cannot be used as evidence that
                    # an unseen piece changed. This is the public search rule.
                    if observed.matches(endpoint) and all(
                            endpoint.piece_at(square)==source.piece_at(square) for square in hidden):
                        expected.add((candidate.uci(),))
                result=LegalSearcher(1,time_limit_ms=1000).search(source,observed,target_turn=target.turn)
                assert result.exhaustive
                assert {tuple(m.uci() for m in path) for path in result.paths}==expected
        assert source.fen()==original


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
    state=Reconstructor(chess.Board()).serialize()
    probe=Reconstructor.restore(state)
    probe.observe(Observation.from_board(play(chess.Board(),'e4')))
    assert probe.verified==['e2e4'] and state['verified']==[]


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


def test_opening_first_shortest_proves_depth_and_prefers_pawns_without_enumerating_orders():
    target=play(chess.Board(),'e4 c5 d3 Nc6 c3')
    result=LegalSearcher(6).search(chess.Board(),Observation.from_board(target),
                                 first_shortest=True,pawn_first=True)
    assert result.shortest_proven and not result.exhaustive
    assert [move.uci() for move in result.paths[0]]==[move.uci() for move in target.move_stack]
    assert result.depth==5 and result.nodes<1000
    limited=LegalSearcher(6,node_limit=1).search(chess.Board(),Observation.from_board(target),
                                              first_shortest=True,pawn_first=True)
    assert not limited.shortest_proven and not limited.paths


def test_guesses_put_double_pawn_push_before_single_push_in_fast_and_exhaustive_paths():
    target=play(chess.Board(),'c3 e5 d4')
    search=LegalSearcher(3)
    exact=search.search(chess.Board(),Observation.from_board(target))
    assert exact.exhaustive
    for paths in (select_capture_path(chess.Board(),exact.paths),
                  search.search(chess.Board(),Observation.from_board(target),first_shortest=True).paths):
        assert [m.uci() for m in paths[0]]==['d2d4','e7e5','c2c3']
    from chessstream.reconstruction import guess_move_priority
    source=play(chess.Board(),'e4 d5')
    assert guess_move_priority(source,source.parse_san('exd5')) < guess_move_priority(source,source.parse_san('d4'))
    assert guess_move_priority(source,source.parse_san('d4')) < guess_move_priority(source,source.parse_san('d3'))
    assert guess_move_priority(source,source.parse_san('d3')) < guess_move_priority(source,source.parse_san('Nf3'))


def test_repeated_queen_excursion_is_unverified_but_ordinary_three_plies_are_not():
    # Concrete dubious route present in the reported YouTube recording.
    from unittest.mock import patch
    from chessstream.reconstruction import SearchResult
    source=play(chess.Board(),'d4 Nf6 Bf4 g6 e3 Bg7 h3 d6 Nf3 O-O Be2 Bf5 O-O Be4 c4 Re8 Nc3 c6')
    state=source.copy()
    route=[]
    for san in 'Qb1 Bd5 Qe4'.split():
        move=state.parse_san(san);route.append(move);state.push(move)
    assert speculative_detour(source,tuple(route))
    rec=Reconstructor(source,confirmation_plies=0)
    with patch('chessstream.reconstruction.LegalSearcher.search',
               return_value=SearchResult(paths=[tuple(route)],exhaustive=True,shortest_proven=True)):
        update=rec.observe(Observation.from_board(state))
    assert not rec.verified
    assert rec.gap_requires_confirmation
    assert [b.moves for b in rec.branches]==[tuple(m.uci() for m in route)]
    restored=Reconstructor.restore(rec.serialize())
    assert restored.gap_requires_confirmation and not restored.verified
    rec.choose(0)
    assert not rec.gap_requires_confirmation and rec.verified==[m.uci() for m in route]

    # True rapid captures/moves by distinct pieces must not be blocked.
    normal=play(chess.Board(),'e4 e5 Nf3 Nc6 Bc4 Bc5 d4 Bxd4 c3 Bb6')
    trial=normal.copy();moves=[]
    for san in 'Ng5 Nh6 Qf3'.split():
        move=trial.parse_san(san);moves.append(move);trial.push(move)
    assert not speculative_detour(normal,tuple(moves))
