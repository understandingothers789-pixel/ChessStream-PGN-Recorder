"""PGN annotation trees and observed clock comments, separate from verified play."""
import io
import chess.pgn


def merge_annotations(game, review_pgn='', clocks=None):
    if review_pgn:
        source=chess.pgn.read_game(io.StringIO(review_pgn))
        if source and source.board().fen()==game.board().fen():
            def merge(old,new):
                for child in old.variations:
                    target=next((n for n in new.variations if n.move==child.move),None)
                    # Review annotations cannot silently extend the actual game.
                    if target is None and new.is_mainline() and new.is_end():continue
                    if target is None:target=new.add_variation(child.move)
                    target.comment=child.comment;target.starting_comment=child.starting_comment;target.nags=set(child.nags)
                    merge(child,target)
            merge(source,game)
    for ply,node in enumerate(game.mainline(),1):
        seconds=(clocks or {}).get(str(ply))
        if seconds is not None:node.set_clock(seconds)
    return game


def node_at(game,path):
    node=game
    for index in path:node=node.variations[index]
    return node
