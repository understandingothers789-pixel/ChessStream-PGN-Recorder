"""Small, goal-directed legal search for openings visible only at their endpoint."""
from time import perf_counter
import chess
from .domain import board_labels
from .reconstruction import guess_move_priority


def infer_visible_opening(observed, *, max_plies=14, time_limit_ms=400,
                          node_limit=50000, target_turn=None, start_board=None):
    """Return one legal line to a near-full opening, or no line.

    Moves must clear a square that differs from the image and progress toward
    an occupied target square, except a capture may temporarily occupy the
    square of a later recapture. This keeps the branching factor small without
    mistaking an arbitrary late endgame for an opening.
    """
    target=observed.placement()
    goal=chess.Board(f'{target} w - - 0 1')
    if not goal.is_valid() and not chess.Board(f'{target} b - - 0 1').is_valid():return []
    wanted=board_labels(goal)
    start=start_board.copy(stack=False) if start_board is not None else chess.Board()
    occupied=len(goal.piece_map())
    missing=start.occupied.bit_count()-occupied
    if missing<0 or missing>2:return []
    target_count={color:sum(piece.color==color for piece in goal.piece_map().values())
                  for color in chess.COLORS}
    start_time=perf_counter();nodes=0;path=[]
    dead=set();aborted=False

    def distance(board):
        return sum(board.piece_at(square)!=goal.piece_at(square) for square in chess.SQUARES)

    def needed_by_color(board,color):
        needed=sum(piece.color==color and board.piece_at(square)!=piece
                   for square,piece in goal.piece_map().items())
        rank=0 if color else 7
        for king_file,rook_file,home_rook_file,rights in (
                (6,5,7,board.has_kingside_castling_rights),
                (2,3,0,board.has_queenside_castling_rights)):
            king=chess.square(king_file,rank);rook=chess.square(rook_file,rank)
            home_king=chess.square(4,rank);home_rook=chess.square(home_rook_file,rank)
            if (goal.piece_at(king)==chess.Piece(chess.KING,color)
                    and goal.piece_at(rook)==chess.Piece(chess.ROOK,color)
                    and board.piece_at(home_king)==chess.Piece(chess.KING,color)
                    and board.piece_at(home_rook)==chess.Piece(chess.ROOK,color)
                    and board.piece_at(king)!=goal.piece_at(king)
                    and board.piece_at(rook)!=goal.piece_at(rook)
                    and rights(color)):
                needed-=1
                break
        return needed

    def visit(board,remaining,captures):
        nonlocal nodes,aborted
        nodes+=1
        if nodes>node_limit or (nodes%64==0 and (perf_counter()-start_time)*1000>time_limit_ms):
            aborted=True;return False
        if board.board_fen()==target and (target_turn is None or board.turn==target_turn):return True
        if remaining==0 or captures>missing:return False
        if any(board.occupied_co[color].bit_count()<target_count[color] for color in chess.COLORS):return False
        mismatch=distance(board)
        if mismatch>4*remaining:return False
        white_turns=(remaining+int(board.turn==chess.WHITE))//2
        if needed_by_color(board,chess.WHITE)>white_turns or needed_by_color(board,chess.BLACK)>remaining-white_turns:
            return False
        key=(board.board_fen(),board.turn,board.castling_rights,board.ep_square,remaining)
        if key in dead:return False
        choices=[]
        for move in board.legal_moves:
            source=board.piece_at(move.from_square)
            if source==goal.piece_at(move.from_square) and not board.is_capture(move):continue
            capture=board.is_capture(move)
            castling=board.is_castling(move)
            if capture and captures==missing:continue
            destination=goal.piece_at(move.to_square)
            setup_pawn=False
            if missing and source.piece_type==chess.PAWN and destination is None:
                next_rank=chess.square_rank(move.to_square)+(1 if board.turn else -1)
                if 0<=next_rank<8:
                    setup_pawn=any(goal.piece_at(chess.square(file,next_rank)) is not None
                                   for file in (chess.square_file(move.to_square)-1,chess.square_file(move.to_square)+1)
                                   if 0<=file<8)
            # A capture/recapture can temporarily put the wrong piece on its
            # final square. Other moves must advance toward a visible piece.
            if not capture and not castling and not setup_pawn and (destination is None or destination.color!=board.turn):
                continue
            move_priority=guess_move_priority(board,move)
            board.push(move)
            after=distance(board)
            # Reject reversals and irrelevant setup moves. A preparatory pawn
            # advance onto a recapture square can keep the mismatch unchanged.
            if after<=mismatch or (missing and source.piece_type==chess.PAWN and after==mismatch+1):
                center={4:0,3:1,2:2,5:3,1:4,6:5,0:6,7:7}
                priority=(after,move_priority,
                          center[chess.square_file(move.to_square)],move.uci())
                choices.append((priority,move,capture))
            board.pop()
        for _,move,capture in sorted(choices,key=lambda entry:entry[0]):
            board.push(move);path.append(move)
            if visit(board,remaining-1,captures+int(capture)):return True
            path.pop();board.pop()
            if aborted:return False
        dead.add(key)
        return False

    lower=max(1,needed_by_color(start,chess.WHITE)+needed_by_color(start,chess.BLACK))
    for depth in range(lower,max_plies+1):
        if target_turn is not None and (start.turn ^ bool(depth&1))!=target_turn:continue
        if visit(start,depth,0):return [move.uci() for move in path]
        if aborted:break
    return []
