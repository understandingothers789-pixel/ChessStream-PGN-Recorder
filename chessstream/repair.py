"""Remove reversible piece excursions only after replaying the retained game."""
from time import monotonic
import io
import chess
import chess.pgn


def position_key(board):
    # Counters change when redundant plies disappear. Preserve all chess rights.
    return board.board_fen(),board.turn,board.castling_xfen(),board.fen(en_passant='legal').split()[3]


def retained_annotations(pgn,indices):
    """Keep move comments/clocks and variations whose anchor position survives."""
    source=chess.pgn.read_game(io.StringIO(pgn));old=list(source.mainline())
    game=chess.pgn.Game();game.setup(source.board());game.headers.update(source.headers);game.comment=source.comment
    cursor=game

    def copy_branch(node,parent,board):
        if node.move not in board.legal_moves:return
        target=parent.add_variation(node.move)
        target.comment=node.comment;target.starting_comment=node.starting_comment;target.nags=set(node.nags)
        next_board=board.copy();next_board.push(node.move)
        for child in node.variations:copy_branch(child,target,next_board)

    for index in indices:
        node=old[index];parent=cursor
        cursor=parent.add_main_variation(node.move)
        cursor.comment=node.comment;cursor.starting_comment=node.starting_comment;cursor.nags=set(node.nags)
        if position_key(parent.board())==position_key(node.parent.board()):
            for variation in node.parent.variations[1:]:copy_branch(variation,parent,parent.board())
    return game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))


def simplify_shuffles(initial_fen,moves,eligible=None,time_limit_ms=150):
    """Return retained original indices; keep a legal identical endpoint.

    Look for inverse noncapturing piece moves from each side. The two sides'
    excursions can be interleaved with real development, as in Bb8/Bf4 and
    Na6/Nb8. Both excursions must be removable together without breaking turn
    order, captures, castling rights, or the final position.
    """
    started=monotonic();retained=list(range(len(moves)))
    while (monotonic()-started)*1000<time_limit_ms:
        board=chess.Board(initial_fen);steps=[]
        for original in retained:
            move=chess.Move.from_uci(moves[original])
            steps.append((move,board.turn,board.piece_type_at(move.from_square),
                          board.is_capture(move) or board.is_castling(move)))
            board.push(move)
        expected=position_key(board);pairs={chess.WHITE:[],chess.BLACK:[]}
        for i in range(max(0,len(steps)-48),len(steps)):
            move,color,piece,special=steps[i]
            if special or piece in (chess.PAWN,chess.KING):continue
            if eligible is not None and retained[i] not in eligible:continue
            for j in range(i+2,len(steps),2):
                other,other_color,other_piece,other_special=steps[j]
                if other.from_square!=move.to_square:continue
                if (other.to_square==move.from_square and other_color==color
                        and other_piece==piece and not other_special
                        and (eligible is None or retained[j] in eligible)):
                    pairs[color].append((i,j))
                # This piece moved again: later moves are not the inverse of i.
                break
        found=False
        for white in pairs[chess.WHITE]:
            for black in pairs[chess.BLACK]:
                if (monotonic()-started)*1000>=time_limit_ms:return retained
                removed=set(white+black)
                trial=chess.Board(initial_fen);candidate=[]
                for i,original in enumerate(retained):
                    if i in removed:continue
                    move=chess.Move.from_uci(moves[original])
                    if move not in trial.legal_moves:break
                    trial.push(move);candidate.append(original)
                else:
                    if position_key(trial)==expected:
                        retained=candidate;found=True;break
            if found:break
        if not found:break
    return retained
