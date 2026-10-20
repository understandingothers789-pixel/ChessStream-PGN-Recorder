"""Non-destructive joining of saved PGN segments across a shortest legal gap."""
import io
import json
import base64
import chess
import chess.pgn
from .domain import Observation
from .reconstruction import LegalSearcher


class AmbiguousGapError(ValueError):
    """More than one equally short legal reconstruction; nothing was committed."""

    def __init__(self, alternatives):
        self.alternatives = tuple(tuple(move.uci() for move in path) for path in alternatives)
        super().__init__(f'{len(self.alternatives)} shortest legal gap paths exist. '
                         'Choose a verified sequence; automatic joining would invent history.')


def _gap_search(source, later, searcher):
    """Separate, capped saved-PGN search budget; never widen live capture budgets.

    The target is the later segment's actual starting FEN, including its turn.
    A FEN-only checkpoint is valid. Positive castling rights are evidence,
    while absent rights in an image-derived initial FEN are not proof of loss.
    """
    target = later.board()
    if not source.is_valid() or not target.is_valid():
        raise ValueError('A segment endpoint contains an invalid position.')
    # Material cannot be resurrected through an ordinary gap. Promotions do
    # not change the number of pieces belonging to either player.
    for color in (chess.WHITE, chess.BLACK):
        if source.occupied_co[color].bit_count() < target.occupied_co[color].bit_count():
            raise ValueError('The target has more pieces than the earlier position.')
    if source.castling_rights == 0 and target.castling_rights:
        raise ValueError('Castling rights cannot be regained between segments.')
    # Higher than the live default of four, but bounded in work and time.
    probe = LegalSearcher(max_plies=max(9, searcher.max_plies),
                          node_limit=max(600000, searcher.node_limit),
                          time_limit_ms=max(5000, searcher.time_limit_ms),
                          threshold=searcher.threshold,
                          path_limit=max(256, searcher.path_limit))
    return probe.search(source, Observation.from_board(target), target_turn=target.turn,
                        target_castling_rights=target.castling_rights or None)



def join_recordings(rows, searcher):
    rows = sorted(rows,key=lambda row: row['started'])
    if len(rows)<2 or len({row['id'] for row in rows})!=len(rows):
        raise ValueError('Select at least two different recordings to join.')

    def read(row):
        game = chess.pgn.read_game(io.StringIO(row['pgn']))
        if game is None or game.errors:raise ValueError('A selected recording contains invalid PGN.')
        return game

    combined = read(rows[0])
    for row in rows[1:]:
        later = read(row)
        for color in ('White','Black'):
            a,b = combined.headers.get(color,'Unknown'),later.headers.get(color,'Unknown')
            if (a not in ('Unknown','?','') and b not in ('Unknown','?','')
                    and ''.join(a.casefold().split())!=''.join(b.casefold().split())):
                raise ValueError(f'These recordings have different {color.lower()} player names.')
        if combined.headers.get('Result','*')!='*':
            raise ValueError('The earlier game has a declared result. Correct it before joining further play.')
        end = combined.end()
        source = end.board()
        # Repeated/overlapping recordings need no invented return to the root.
        # Only accept overlap when the shared mainline agrees move for move.
        overlap=None
        later_moves=list(later.mainline_moves())
        root=later.board()
        for node in [combined,*combined.mainline()]:
            board=node.board()
            if (board.board_fen()!=root.board_fen() or board.turn!=root.turn
                    or (root.castling_rights and board.castling_rights!=root.castling_rights)
                    or (board.ep_square if board.has_legal_en_passant() else None)
                        != (root.ep_square if root.has_legal_en_passant() else None)):continue
            cursor=node;compatible=True
            for move in later_moves:
                if not cursor.variations:break
                if cursor.variations[0].move!=move:compatible=False;break
                cursor=cursor.variations[0]
            if compatible:overlap=node;break
        if overlap is not None:
            end=overlap
        else:
            # Preserve the newer PGN's initial FEN, turn and castling rights.
            # These are constraints, not reasons to guess missing moves.
            result = _gap_search(source, later, searcher)
            if not result.exhaustive:
                raise ValueError('Saved-PGN gap search was inconclusive (node/time/path limit); originals preserved.')
            valid = []
            for path in result.paths:
                trial = source.copy()
                for move in path:trial.push(move)
                # Compare the *join position*, not merely the endpoint reached
                # after replaying the later segment. Matching placement alone
                # can conceal wrong turn or lost castling rights.
                if (trial.board_fen()!=root.board_fen()
                        or trial.turn!=root.turn
                        or (root.castling_rights and trial.castling_rights!=root.castling_rights)
                        or (trial.ep_square if trial.has_legal_en_passant() else None)
                            != (root.ep_square if root.has_legal_en_passant() else None)):
                    continue
                for move in later.mainline_moves():
                    if move not in trial.legal_moves:break
                    trial.push(move)
                else:
                    if trial.board_fen()==later.end().board().board_fen():valid.append(path)
            if not valid:
                raise ValueError('No legal connection was found within the configured gap limit.')
            # Never use a capture heuristic or UCI ordering as historical evidence.
            if len(valid) != 1:
                raise AmbiguousGapError(valid)
            chosen = valid[0]
            for move in chosen:
                end = end.add_main_variation(move)
                end.comment = 'Inferred across recording gap: shortest legal continuation; intermediate frames were not recorded.'
        if later.comment:end.comment=(end.comment+' Segment note: '+later.comment).strip()
        # Keep later recording identity and original headers in a sidecar note;
        # the source PGNs remain untouched in storage.
        # PGN comments cannot contain raw curly braces. Encode the complete
        # secondary headers losslessly so the exported PGN remains parseable.
        encoded_headers=base64.urlsafe_b64encode(json.dumps(dict(later.headers),
            ensure_ascii=False).encode('utf-8')).decode('ascii')
        end.comment=(end.comment+' Secondary recording headers (base64url JSON): '+encoded_headers).strip()

        def copy_tree(old,new,board):
            for child in old.variations:
                if child.move not in board.legal_moves:
                    raise ValueError('An analysis variation is incompatible with the earlier game state.')
                target = next((node for node in new.variations if node.move==child.move),None)
                if target is None:target=new.add_variation(child.move)
                if child.comment and child.comment not in target.comment:
                    target.comment=(target.comment+' '+child.comment).strip()
                if child.starting_comment:target.starting_comment=child.starting_comment
                target.nags.update(child.nags)
                next_board=board.copy();next_board.push(child.move)
                copy_tree(child,target,next_board)

        copy_tree(later,end,end.board())
        combined.headers['Result']=later.headers.get('Result','*')
        for color in ('White','Black'):
            if combined.headers.get(color,'Unknown') in ('Unknown','?',''):
                name=later.headers.get(color,'Unknown')
                combined.headers[color]=name if name not in ('?','') else 'Unknown'
    # Obsolete checkpoint notices are administrative status, not chess evidence.
    # The original PGN and its complete note remain in the source recording.
    combined.comment=combined.comment.replace(
        "A separate PGN segment was started from the visible board FEN; this game's saved moves remain unchanged.", "").strip()
    combined.comment=(combined.comment+' Joined saved recording segments; gap moves are explicitly annotated as inferred.').strip()
    return combined.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
