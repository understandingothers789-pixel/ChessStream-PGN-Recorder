from __future__ import annotations

from datetime import datetime
from pathlib import Path
import io
import json
import threading
import time
import logging
import uuid
import numpy as np
import chess
import chess.pgn
from .domain import Settings, Observation, utcnow, atomic_text, board_labels
from .reconstruction import Reconstructor, LegalSearcher, Branch
from .storage import Store
from .game_extras import GameExtras
from .pgn_tools import merge_annotations
from .gap_join import join_recordings


def export_pgn(initial_fen: str, moves: list[str], headers: dict, comment="", review_pgn="", clocks=None, inferred_moves=None) -> str:
    game = chess.pgn.Game()
    initial = chess.Board(initial_fen)
    game.setup(initial)
    for key, value in headers.items():
        # PGN values cannot contain newlines or unescaped quotes. Exporter does not escape them.
        key = str(key)
        if key.replace("_", "").isalnum():
            game.headers[key] = str(value).replace("\n"," ").replace("\r"," ").replace('"', "'").replace("\\", "/")
    if initial.fen() != chess.STARTING_FEN:
        game.headers["SetUp"] = "1"
        game.headers["FEN"] = initial.fen()
    if comment:
        game.comment = comment
    node = game
    board = initial.copy()
    for uci in moves:
        move = chess.Move.from_uci(uci)
        if move not in board.legal_moves:
            raise ValueError(f"Cannot export illegal move {uci}")
        node = node.add_variation(move)
        board.push(move)
    merge_annotations(game,review_pgn,clocks)
    for ply,node in enumerate(game.mainline(),1):
        inferred=(inferred_moves or {}).get(str(ply))
        if inferred and inferred['uci']==node.move.uci() and inferred['comment'] not in node.comment:
            node.comment=(node.comment+' '+inferred['comment']).strip()
    return game.accept(chess.pgn.StringExporter(headers=True, variations=True, comments=True))


class GameManager(GameExtras):
    def __init__(self, store: Store, settings: Settings, session_id: str | None = None):
        self.store, self.settings = store, settings
        self.session_id = session_id or store.session()
        self.lock = threading.RLock()
        self.current_id: str | None = None
        self.rec: Reconstructor | None = None
        self.headers: dict = {}
        self.name = ""
        self.started = ""
        self.ended: str | None = None
        self.note = ""
        self.result_override=False
        self.reset_candidate: Reconstructor | None = None
        self.reset_started: str | None = None
        self.last_observation: Observation | None = None
        self._recognition_ignored_squares=[]
        self._opening_cache=None
        self.last_message = "Select a board and start recording"
        self._persisted_fingerprint=None
        self._last_evidence_signature=None
        self._unresolved_position=None
        self._unresolved_since=None
        self._unresolved_timestamp=None
        self._review_position=None
        self._review_since=None
        self._review_candidate=None
        self._review_recorded=None
        self._clock=time.monotonic
        self._reset_extras()

    def searcher(self):
        s = self.settings
        return LegalSearcher(s.max_plies, s.search_nodes, s.search_ms, s.min_confidence)

    def reconstructor(self, board, roots=None):
        return Reconstructor(board, self.searcher(), roots, int(self.settings.confirm_on_reply))

    def _create(self, board, timestamp, roots=None, note=""):
        self._reset_extras()
        self.reset_candidate=None;self.reset_started=None
        self.current_id = uuid.uuid4().hex
        self.started = timestamp
        self.ended = None
        self.result_override=False
        self.name = "Game " + datetime.fromisoformat(timestamp).astimezone().strftime("%H:%M:%S")
        self.headers = {"Event":"YouTube Chess Recording","Site":"YouTube",
                        "Date":timestamp[:10].replace("-","."),"Round":"?",
                        "White":"Unknown","Black":"Unknown","Result":"*"}
        self.rec = self.reconstructor(board, roots)
        self.note = note
        self.last_message = self.rec.status
        self.persist()
        self.store.associate_screenshots(self.session_id,self.current_id,initial_placement=board.board_fen())

    def _initialize(self, obs):
        # Arbitrary root FENs need all 64 squares. A bounded standard-opening
        # hypothesis can instead carry at most two unchanged squares as unknown.
        uncertain = obs.uncertain_squares(max(.80, self.settings.min_confidence))
        if self.settings.initial_fen:
            b = chess.Board(self.settings.initial_fen)
            if uncertain or not obs.matches(b, self.settings.min_confidence):
                self.last_message = "Observed board does not match the configured initial FEN"
                return False
            self._create(b, obs.timestamp)
            return True
        opening_moves=self._infer_short_opening(obs)
        if (len(uncertain)<=2 and obs.confidence>=max(.80,self.settings.min_confidence)
                and self._resume_latest_game_at_position(obs,allow_completed_review=not bool(opening_moves))):
            return True
        if not uncertain and obs.placement() == chess.Board().board_fen():
            self._create(chess.Board(), obs.timestamp)
            return True
        if opening_moves:
            note=self._opening_note()
            if uncertain:note+=' Uncertain unchanged squares retained from the starting position: '+', '.join(uncertain)+'.'
            self._create(chess.Board(), obs.timestamp, note=note)
            self._seed_opening(opening_moves)
            self._recognition_ignored_squares=uncertain
            self.last_message = "Recording • guessed opening line: " + " ".join(
                self._san_line(chess.Board(), opening_moves))
            self.store.audit("opening prefix inferred", {"game_id":self.current_id,
                "moves":opening_moves,"method":"shortest legal path; pawn moves first; move order guessed",
                "uncertain_unchanged_squares":uncertain})
            return True
        if uncertain:
            self.last_message = ("Waiting for reliable recognition • uncertain squares: "
                                 + ", ".join(uncertain[:8])
                                 + (f" (+{len(uncertain)-8} more)" if len(uncertain)>8 else ""))
            return False
        roots = []
        for turn in ["w", "b"]:
            b = chess.Board(f"{obs.placement()} {turn} - - 0 1")
            if b.is_valid():
                roots.append(b.fen())
        if not roots:
            self.last_message = "Position is not a valid chessboard • check region, orientation or calibrate"
            return False
        note = ("Recording began midgame. Earlier moves are unavailable. Side to move is inferred from later evidence. "
                "Castling rights and en passant history were not visible; no rights were assumed. Set an exact initial FEN if needed.")
        self._create(chess.Board(roots[0]), obs.timestamp, roots, note)
        return True

    def _resume_latest_game_at_position(self, obs, allow_completed_review=True):
        """Reuse a recent PGN on an exact match or shortest legal bridge.

        The visible image gives us piece placement, but not side to move,
        castling rights, en-passant state, or counters. Match placement against
        the verified/pending endpoint, or infer a bounded continuation from
        the verified prefix. If a live FEN checkpoint was just created, also
        retry the preserved PGN that preceded it before keeping the split.
        """
        rows=self.store.query("SELECT id,state,headers,session_id,status,name FROM games WHERE status!='imported' AND status NOT LIKE 'reconnected%' AND status NOT LIKE 'combined source%' ORDER BY started DESC,updated DESC LIMIT 16")
        if not rows:return False
        latest=rows[0]

        def is_checkpoint(row):
            try:note=json.loads(row['state']).get('note','')
            except (TypeError,ValueError):return False
            return 'visible midgame FEN' in note or 'visible board FEN' in note

        is_fen_checkpoint=is_checkpoint(latest)
        candidates=[]
        active=next((row for row in rows if row['id']==self.current_id),None)
        if active and not is_checkpoint(active):candidates.append(active)
        if is_fen_checkpoint:
            # Fullscreen/resize recovery can briefly produce an unmatched view
            # and a FEN checkpoint. Reconsider the game that was preserved just
            # before that checkpoint, since its endpoint may still bridge to
            # the newly stable board.
            prior=[row for row in rows if row['id']!=latest['id']
                   and row['session_id']==latest['session_id']
                   and row['status'].startswith('preserved')]
            candidates.extend(row for row in prior if row['id'] not in {item['id'] for item in candidates})
        if latest['id'] not in {row['id'] for row in candidates}:candidates.append(latest)
        # A newer temporary segment must not hide the last real game.
        candidates.extend(row for row in rows if row['status'].startswith('preserved')
                          and row['id'] not in {item['id'] for item in candidates})

        chosen=None
        joined=None
        if is_fen_checkpoint:
            # A temporary FEN PGN is a segment of the current game when its
            # verified line can be attached to the immediately preceding PGN.
            # Try this full join before falling back to a direct bridge from
            # the older PGN to the latest image.
            if (not self.pending_identity
                    and not (self.clocks_recently_reset() and obs.placement()==chess.Board().board_fen())):
                for previous in candidates:
                    if (previous['id']==latest['id'] or previous['session_id']!=latest['session_id']
                            or not previous['status'].startswith('preserved')):
                        continue
                    try:
                        joined=self._join_checkpoint(previous['id'],latest['id'],obs)
                    except (ValueError,TypeError,KeyError,chess.IllegalMoveError):
                        logging.info('Could not join checkpoint %s into %s; trying the ordinary saved-position recovery',
                                     latest['id'],previous['id'],exc_info=True)
                        joined=None
                    if joined is not None:
                        chosen=(previous,joined['rec'],joined['bridge_before'],[],joined['bridged'],None,False)
                        break
        for row in candidates:
            if chosen is not None:break
            try:
                state=json.loads(row['state'])
                if not allow_completed_review and (json.loads(row['headers']).get('Result','*')!='*' or state.get('terminal_message')):
                    continue
                saved=Reconstructor.restore(state,self.searcher())
                placements={saved.board.board_fen()}
                placements.update(branch.board().board_fen() for branch in saved.branches)
            except (KeyError,TypeError,ValueError,chess.IllegalMoveError):
                logging.warning('Could not compare saved game %s for automatic resume',row['id'],exc_info=True)
                continue
            before=len(saved.verified)
            previous_pending=[branch.moves for branch in saved.branches]
            bridged=False
            bridge_update=None
            review=obs.placement() not in placements and obs.placement() in saved.history[:-1]
            if obs.placement() not in placements and not review:
                headers=json.loads(row['headers'])
                # A declared result blocks reconnecting an unrelated game.
                # Identity OCR alone cannot override a legal continuation. A clock reset alone is weak during window
                # layout changes; only let it block a standard-start reset.
                if (headers.get('Result','*')!='*' or state.get('terminal_message')
                        or (self.clocks_recently_reset()
                            and obs.placement()==chess.Board().board_fen())):
                    continue
                saved.confirmation_plies=int(self.settings.confirm_on_reply)
                bridge_update=saved.bridge_gap(obs,self.searcher())
                if bridge_update is None:continue
                bridged=True
            chosen=(row,saved,before,previous_pending,bridged,bridge_update,review)
            break
        if chosen is None:return False
        row,saved,before,previous_pending,bridged,bridge_update,review=chosen
        latest_checkpoint_id=(latest['id'] if row['id']!=latest['id'] and is_fen_checkpoint else None)
        unused_session=self.session_id
        self.recover(row["id"],persist=False)
        if joined is not None and row['id']!=latest['id']:
            self.rec=joined['rec']
            self.review_pgn=joined['pgn']
            self.headers=dict(joined['game'].headers)
            self.move_clocks.update(joined['clocks'])
            self.note=self.note.replace(
                ' A separate PGN segment was started from the visible board FEN; this game\'s saved moves remain unchanged.','').strip()
            self.note += " A temporary visible-FEN recording was joined to this PGN using the shortest legal connection; inferred gap moves are labeled."
            if bridged:
                self._mark_inferred_gap(before,previous_pending)
                if joined['bridge_update'] and joined['bridge_update'].tie_broken:
                    self._mark_capture_tiebreak(before)
            self._persisted_fingerprint=None
            self.store.audit('saved PGN segments automatically joined',{
                'game_id':self.current_id,'checkpoint_game_id':latest_checkpoint_id,
                'joined_plies':len(self.rec.verified),'bridge_plies':len(self.rec.verified)-before,
                'fen':self.rec.board.fen()})
        elif bridged:
            self.rec=saved
            self._mark_inferred_gap(before,previous_pending)
            if bridge_update.tie_broken and len(saved.verified)>before:
                self._mark_capture_tiebreak(before)
        if latest_checkpoint_id:
            with self.store.transaction() as db:
                db.execute('UPDATE games SET status=?,ended=?,updated=? WHERE id=?',
                    (f"reconnected • see {row['name']}",utcnow(),utcnow(),latest_checkpoint_id))
        if unused_session!=self.session_id:
            self.store.finish_session(unused_session)
        self.last_observation=obs
        backfilled=self._backfill_opening_prefix()
        self.last_message=("Joined the saved PGNs • continuing the combined game" if joined is not None else
                           "Review position • linked to latest saved PGN history" if review else
                           "Gap linked to latest PGN • shortest legal continuation • "+self.rec.status if bridged else
                           "Continued latest saved PGN • visible board matches its verified or pending position")
        if backfilled:self.last_message='Opening prefix guessed and restored • '+self.last_message
        self.persist()
        self.store.audit("latest PGN resumed by visible position",{
            "game_id":self.current_id,"checkpoint_game_id":latest_checkpoint_id,
            "placement":obs.placement(),"matched_pending":obs.placement()!=saved.board.board_fen(),
            "bridged":bridged,"review":review})
        logging.info("Resumed latest saved PGN %s from matching visible board placement",self.current_id)
        return True

    def _join_checkpoint(self, previous_id, checkpoint_id, obs):
        """Return a validated merged PGN and live reconstructor for two saved segments."""
        previous=self.store.game(previous_id);checkpoint=self.store.game(checkpoint_id)
        if not previous or not checkpoint:raise ValueError('A saved PGN segment is missing.')
        previous_state=json.loads(previous['state']);checkpoint_state=json.loads(checkpoint['state'])
        previous_headers=json.loads(previous['headers']);checkpoint_headers=json.loads(checkpoint['headers'])
        if (previous_headers.get('Result','*')!='*' or previous_state.get('terminal_message')
                or checkpoint_headers.get('Result','*')!='*' or checkpoint_state.get('terminal_message')):
            raise ValueError('A game-end result prevents automatic joining.')
        pgn=join_recordings([previous,checkpoint],self.searcher())
        game=chess.pgn.read_game(io.StringIO(pgn))
        if game is None or game.errors:raise ValueError('The joined PGN did not pass validation.')
        checkpoint_note=checkpoint_state.get('note','')
        if checkpoint_note:
            def sanitize_segment_note(node):
                if checkpoint_note in node.comment:
                    node.comment=node.comment.replace(checkpoint_note,
                        'Visible-FEN checkpoint joined to the preceding PGN; inferred gap moves are labeled.')
                for child in node.variations:sanitize_segment_note(child)
            sanitize_segment_note(game)
            pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
        rec=self.reconstructor(game.board())
        clocks={}
        for ply,node in enumerate(game.mainline(),1):
            if node.move not in rec.board.legal_moves:raise ValueError('Joined PGN contains an illegal move.')
            rec.board.push(node.move);rec.verified.append(node.move.uci());rec.history.append(rec.board.board_fen())
            clock=node.clock()
            if clock is not None:clocks[str(ply)]=clock
        rec.branches=[Branch(rec.board.fen(),())]
        rec.status='recording • joined saved PGN segments'
        bridge_before=len(rec.verified);bridge_update=None;bridged=False
        if not obs.matches(rec.board,max(.8,self.settings.min_confidence)):
            bridge_update=rec.bridge_gap(obs,self.searcher())
            if bridge_update is None:raise ValueError('The joined PGN does not reach the current visible position.')
            bridged=True
        if not rec.branches or any(branch.board().board_fen()!=obs.placement() for branch in rec.branches):
            raise ValueError('The joined PGN does not match the current visible position.')
        rec.confirmation_plies=int(self.settings.confirm_on_reply)
        return {'pgn':pgn,'game':game,'rec':rec,'clocks':clocks,
                'bridge_before':bridge_before,'bridge_update':bridge_update,'bridged':bridged}

    def _mark_inferred_gap(self, before, previous_pending):
        """Annotate only the common new path across a multi-move gap."""
        added=tuple(self.rec.verified[before:])
        paths=[added+branch.moves for branch in self.rec.branches]
        if not paths:return
        common=min(len(path) for path in paths)
        for offset in range(common):
            if len({path[offset] for path in paths})!=1:break
            uci=paths[0][offset]
            if any(len(old)>offset and old[:offset+1]==paths[0][:offset+1] for old in previous_pending):continue
            self.inferred_moves[str(before+offset+1)]={
                'uci':uci,'comment':'Inferred across capture gap: shortest legal continuation; intermediate frames were not recorded.'}
        self.store.audit('shortest legal gap linked',{'game_id':self.current_id,'after_ply':before,
            'paths':[list(path) for path in paths],'ambiguous':len(paths)>1})

    def _mark_capture_tiebreak(self, before):
        """Keep the deterministic choice visible in the exported PGN and audit."""
        for offset,uci in enumerate(self.rec.verified[before:]):
            self.inferred_moves[str(before+offset+1)]={
                'uci':uci,
                'comment':'Equal shortest legal paths reached this position; selected by capture continuity, then stable move order.'}
        self.store.audit('equal shortest paths resolved',{
            'game_id':self.current_id,'after_ply':before,
            'selected':self.rec.verified[before:],
            'rule':'same-square recaptures, consecutive captures, capture count, then stable UCI order'})

    def _visible_roots(self, obs):
        threshold=max(.80,self.settings.min_confidence)
        if not obs.uncertain_squares(threshold) and obs.placement()==chess.Board().board_fen():
            return chess.Board(),None,""
        moves=self._infer_short_opening(obs,max_plies=4)
        if moves:
            sans=self._san_line(chess.Board(),moves)
            note=self._opening_note()+' Selected line: '+' '.join(sans)+'.'
            return chess.Board(),None,note
        if obs.confidence<threshold or obs.uncertain_squares(threshold):
            raise ValueError("Wait for a clear, stable board before starting from its FEN")
        roots=[]
        for turn in ["w","b"]:
            board=chess.Board(f"{obs.placement()} {turn} - - 0 1")
            if board.is_valid():roots.append(board.fen())
        if not roots:
            raise ValueError("The visible pieces do not form a valid chess position")
        note=("Recording started from a visible midgame FEN. Earlier moves are not included. "
              "Side to move is inferred from the next legal continuation. Castling rights and en passant history "
              "are not visible in the image and were not assumed.")
        return chess.Board(roots[0]),roots,note

    @staticmethod
    def _opening_note():
        return ('Opening prefix guessed from the standard starting position using a shortest legal path. '
                'Pawn moves were prioritized, then direct target progress and central pawn advances. '
                'The actual earlier move order may differ; this is an inferred opening, not recorded history.')

    def _infer_short_opening(self, obs, max_plies=6, target_turn=None):
        """Choose one bounded shortest opening; ambiguity is explicitly guessed.

        A few unknown unchanged squares do not invalidate the whole opening.
        The legal search still requires positive evidence for every move's
        changed squares. Sparse endgames and heavily changed roots are not
        interpreted as a handful of moves from the standard starting board.
        """
        if self.settings.initial_fen:return []
        threshold=max(.80,self.settings.min_confidence)
        confident=obs.probabilities.max(axis=1)>=threshold
        if obs.confidence<threshold or np.count_nonzero(~confident)>2:return []
        initial=chess.Board();expected=board_labels(initial);labels=obs.labels
        if obs.matches(initial,threshold):return []
        occupied=int(np.count_nonzero((labels!=0)&confident))
        displaced=int(np.count_nonzero((expected!=0)&(labels!=expected)&confident))
        if not 28<=occupied<=32 or not 1<=displaced<=6:return []
        if np.any(obs.probabilities[np.arange(64)[~confident],expected[~confident]]<.05):return []
        key=(obs.probabilities.tobytes(),max_plies,target_turn,threshold,
             self.settings.search_nodes,self.settings.search_ms)
        if self._opening_cache and self._opening_cache[0]==key:return list(self._opening_cache[1])
        search=LegalSearcher(max_plies=max_plies,
            node_limit=min(60000,max(1000,self.settings.search_nodes)),
            time_limit_ms=min(400,max(50,self.settings.search_ms)),threshold=threshold)
        result=search.search(initial,obs,target_turn=target_turn,first_shortest=True,pawn_first=True)
        if not result.shortest_proven or not result.paths or not result.paths[0]:return []
        moves=[move.uci() for move in result.paths[0]]
        board=chess.Board()
        for uci in moves:
            board.push_uci(uci)
        if not obs.matches(board,threshold):return []
        self._opening_cache=(key,tuple(moves))
        return moves

    def opening_ready(self, obs):
        with self.lock:
            return bool(self._infer_short_opening(obs))

    def _backfill_opening_prefix(self):
        """Repair an application-created early FEN segment without losing its continuation."""
        if (not self.rec or self.rec.initial_fen==chess.STARTING_FEN or self.headers.get('Result','*')!='*'
                or not any(text in self.note for text in ('Recording began midgame','visible midgame FEN'))):
            return False
        old=self.rec;root=chess.Board(old.initial_fen)
        turn=None if not old.verified and len({b.root_fen for b in old.branches})>1 else root.turn
        prefix=self._infer_short_opening(Observation.from_board(root),target_turn=turn)
        if not prefix:return False
        try:
            board=chess.Board()
            for uci in prefix+old.verified:board.push_uci(uci)
            branches=[]
            for branch in old.branches:
                origin=chess.Board(branch.root_fen)
                if origin.board_fen()!=board.board_fen() or origin.turn!=board.turn:continue
                endpoint=board.copy()
                for uci in branch.moves:endpoint.push_uci(uci)
                if endpoint.board_fen()==branch.board().board_fen():branches.append(Branch(board.fen(),branch.moves))
            if not branches:return False
            headers={key:value for key,value in self.headers.items() if key not in ('FEN','SetUp')}
            pgn=export_pgn(old.initial_fen,old.verified,self.headers,self.note,
                           self.review_pgn,self.move_clocks,self.inferred_moves)
            joined=join_recordings([
                {'id':'opening-prefix','started':'','pgn':export_pgn(chess.STARTING_FEN,prefix,headers,self._opening_note())},
                {'id':self.current_id,'started':self.started,'pgn':pgn}],self.searcher())
            game=chess.pgn.read_game(io.StringIO(joined))
            if game is None or game.errors:return False
            anchor=game
            for _ in prefix:anchor=anchor.variations[0]
            anchor.comment=anchor.comment.replace(self.note,
                'The original application-created FEN start followed this guessed opening prefix.')
            data=old.serialize();data['initial_fen']=chess.STARTING_FEN
            data['verified']=prefix+old.verified
            data['branches']=[{'root_fen':b.root_fen,'moves':list(b.moves)} for b in branches]
            if not old.verified and not any(b.moves for b in old.branches) and self.settings.confirm_on_reply:
                data['verified']=prefix[:-1];before=chess.Board()
                for uci in prefix[:-1]:before.push_uci(uci)
                data['branches']=[{'root_fen':before.fen(),'moves':[prefix[-1]]}]
            restored=Reconstructor.restore(data,self.searcher())
        except (ValueError,KeyError,IndexError):
            logging.info('Could not backfill a saved opening FEN; original retained',exc_info=True)
            return False
        self.rec=restored;self.headers=dict(game.headers)
        self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
        self.move_clocks={str(ply):node.clock() for ply,node in enumerate(game.mainline(),1) if node.clock() is not None}
        self.inferred_moves={str(int(ply)+len(prefix)):value for ply,value in self.inferred_moves.items()}
        for ply,uci in enumerate(prefix,1):
            self.inferred_moves[str(ply)]={'uci':uci,'comment':'Guessed opening prefix restored before an earlier FEN recording; pawn moves prioritized.'}
        self.note=self._opening_note()+' An earlier application-created FEN start was replaced; its recorded continuation was retained.'
        self._persisted_fingerprint=None
        self.store.audit('opening prefix backfilled',{'game_id':self.current_id,'previous_initial_fen':old.initial_fen,
            'prefix':prefix,'method':'shortest legal opening; pawn moves first; earlier order guessed'})
        return True

    @staticmethod
    def _san_line(board, moves):
        result=[]
        for uci in moves:
            move=chess.Move.from_uci(uci)
            result.append(board.san(move));board.push(move)
        return result

    def _seed_opening(self, moves):
        if not self.rec or not moves:return
        pending=1 if self.settings.confirm_on_reply else 0
        confirmed=moves[:-pending] if pending else moves
        for ply,uci in enumerate(moves,1):
            self.inferred_moves[str(ply)]={'uci':uci,'comment':'Guessed opening prefix: shortest legal path, pawn moves prioritized; earlier move order may differ.'}
        for uci in confirmed:
            self.rec.board.push_uci(uci)
            self.rec.verified.append(uci)
            self.rec.history.append(self.rec.board.board_fen())
        self.rec.branches=[Branch(self.rec.board.fen(),tuple(moves[len(confirmed):]))]
        self.rec.status=("provisional move • opening guessed; waiting for opponent response" if pending else
                         "recording • opening guessed from visible position")
        self._persisted_fingerprint=None

    def _start_from_visible(self, obs, reason, since=None):
        opening_moves=self._infer_short_opening(obs,max_plies=4)
        board,roots,note=self._visible_roots(obs)
        previous_id=self.current_id
        if self.rec:
            self.note += " A separate PGN segment was started from the visible board FEN; this game's saved moves remain unchanged."
            self.finish("preserved • continued from visible FEN")
        self.rec=None
        self.reset_candidate=None
        self._create(board,obs.timestamp,roots,note+" Temporary visible board FEN segment.")
        self._seed_opening(opening_moves)
        self.persist()
        self.last_message="New PGN started from the visible board position"
        self.clear_position_recovery()
        self.store.audit("visible FEN checkpoint",{"previous_game_id":previous_id,"game_id":self.current_id,
            "reason":reason,"fen":board.fen(),"side_to_move":"inferred" if roots and len(roots)>1 else ("white" if board.turn else "black")})
        start=since or obs.timestamp
        self.store.associate_screenshots(self.session_id,self.current_id,since=start)
        with self.store.transaction() as db:
            db.execute("UPDATE observations SET game_id=? WHERE session_id=? AND timestamp>=?",(self.current_id,self.session_id,start))

    def process(self, obs: Observation) -> dict:
        with self.lock:
            self.last_observation = obs
            move_evidence=obs
            self._recognition_ignored_squares=[]
            # An aborted game can end before a single move. A clear legal
            # opening after its popup disappears starts a fresh recording.
            if (self.rec and self.terminal_message and not self.rec.verified
                    and self.rec.initial_fen==chess.STARTING_FEN
                    and obs.placement()!=self.rec.board.board_fen()
                    and not obs.uncertain_squares(max(.8,self.settings.min_confidence))):
                opening=LegalSearcher(1,self.settings.search_nodes,self.settings.search_ms,self.settings.min_confidence).search(chess.Board(),obs)
                if opening.exhaustive and len(opening.paths)==1:
                    self._create(chess.Board(),obs.timestamp)
            if (self.rec and self.pending_identity and self.clocks_recently_reset()
                    and obs.placement()==chess.Board().board_fen()
                    and obs.confidence>=.8 and not obs.uncertain_squares(max(.8,self.settings.min_confidence))):
                names=self.pending_identity
                self._start_from_visible(obs,'visible player names changed')
                self.observed_names=names
                for color,name in names.items():self.headers[color.title()]=name
            if (self.rec and ('visible midgame FEN' in self.note or 'visible board FEN' in self.note)
                    and not obs.uncertain_squares(max(.8,self.settings.min_confidence))
                    and self.store.query("SELECT id FROM games WHERE id!=? AND session_id=? AND status LIKE 'preserved%' LIMIT 1",(self.current_id,self.session_id))):
                self._resume_latest_game_at_position(obs)
            if not self.rec:
                self._initialize(obs)
            else:
                # A manual orientation correction on the initial, unplayed board
                # must repair its provisional FEN rather than appear to be moves.
                if (not self.settings.initial_fen and not self.rec.verified
                        and all(not branch.moves for branch in self.rec.branches)
                        and obs.confidence>=self.settings.min_confidence
                        and obs.placement()!=self.rec.board.board_fen()):
                    rotated=self.rec.board.transform(chess.flip_vertical).transform(chess.flip_horizontal)
                    if obs.placement()==rotated.board_fen():
                        previous=self.rec.initial_fen
                        if obs.placement()==chess.Board().board_fen():
                            self.rec=self.reconstructor(chess.Board());self.note=''
                        else:
                            roots=[]
                            for turn in ['w','b']:
                                initial=chess.Board(f'{obs.placement()} {turn} - - 0 1')
                                if initial.is_valid():roots.append(initial.fen())
                            if roots:self.rec=self.reconstructor(chess.Board(roots[0]),roots)
                        if self.rec.initial_fen!=previous:
                            if self.settings.result_player_color=='initial-bottom':self.player_color=obs.orientation
                            if not self.result_override:self.headers['Result']='*';self.ended=None
                            self.store.audit('initial orientation correction',{'game_id':self.current_id,'previous_fen':previous,'corrected_fen':self.rec.initial_fen})
                self.rec.searcher = self.searcher()
                self.rec.confirmation_plies=int(self.settings.confirm_on_reply)
                is_start = obs.placement() == chess.Board().board_fen()
                if is_start and (self.rec.verified or self.terminal_message) and self.rec.board.board_fen() != obs.placement():
                    if self.terminal_message or self.clocks_recently_reset() or self.rec.board.is_game_over(claim_draw=False) or self.headers["Result"] != "*":
                        self.finish("complete")
                        self._create(chess.Board(), obs.timestamp)
                    else:
                        if not self.reset_candidate:
                            self.reset_candidate = self.reconstructor(chess.Board())
                            self.reset_started = obs.timestamp
                        self.last_message = "Board reset • checking for a new game or opening review"
                elif self.terminal_message:
                    self._confirm_terminal_pending(obs)
                    self._observe_review(obs)
                elif self.ended and self.headers['Result']!='*':
                    self.last_message='Game complete • waiting for a new game'
                elif self.reset_candidate:
                    if obs.matches(self.rec.board):
                        self.reset_candidate = None
                        self.last_message = "Live position restored"
                    else:
                        self.reset_candidate.observe(obs)
                        candidate = self.reset_candidate
                        # A known opening replay is ambiguous; a different legal continuation
                        # from a witnessed reset is evidence of a separate game.
                        diverges = any(a != b for a,b in zip(candidate.verified, self.rec.verified))
                        if candidate.verified and (diverges or len(candidate.verified)>len(self.rec.verified)):
                            stamp = self.reset_started
                            self.finish("transitioned • result unknown")
                            self._create(chess.Board(), stamp)
                            self.rec = candidate
                            self.reset_candidate = None
                            # Screenshots taken while awaiting reset classification belong to the new game.
                            self.store.associate_screenshots(self.session_id,self.current_id,since=stamp)
                            with self.store.transaction() as db:
                                db.execute("UPDATE observations SET game_id=? WHERE session_id=? AND timestamp>=?", (self.current_id,self.session_id,stamp))
                            self.last_message = "New game detected after board reset"
                        else:
                            self.last_message = "Opening review / possible new game • previous PGN preserved"
                else:
                    before=len(self.rec.verified)
                    previous_pending=[branch.moves for branch in self.rec.branches]
                    update = self.rec.observe(obs)
                    if update.ignored_squares:
                        move_evidence=obs.with_unknown(update.ignored_squares)
                        self._recognition_ignored_squares=[chess.square_name(s) for s in update.ignored_squares]
                        if (self.current_id,obs.placement(),update.status,obs.orientation)!=self._last_evidence_signature:
                            self.store.audit('recognition continuity recovery',{
                                'game_id':self.current_id,'raw_placement':obs.placement(),
                                'ignored_squares':self._recognition_ignored_squares,
                                'reason':'weak model disagreement; unchanged legal squares carried forward; changed move squares remain positively observed'})
                    paths=[tuple(self.rec.verified[before:])+branch.moves for branch in self.rec.branches]
                    unseen=min((len(path)-max((len(old) for old in previous_pending
                               if path[:len(old)]==old),default=0) for path in paths),default=0)
                    if (not self.rec.incomplete and unseen>1
                            and all(branch.board().board_fen()==obs.placement() for branch in self.rec.branches)):
                        self._mark_inferred_gap(before,previous_pending)
                    if update.tie_broken and len(self.rec.verified)>before:
                        self._mark_capture_tiebreak(before)
                    if update.ignored_squares:
                        comment=('Recorded with uncertain unchanged square(s): '+', '.join(self._recognition_ignored_squares)+
                                 '; move source and destination were observed. Position continuity used.')
                        for ply in range(before,len(self.rec.verified)):
                            entry=self.inferred_moves.setdefault(str(ply+1),{'uci':self.rec.verified[ply],'comment':''})
                            if comment not in entry['comment']:entry['comment']=(entry['comment']+' '+comment).strip()
                    if update.recovered:
                        self.store.audit("transient candidate replaced",{"game_id":self.current_id,
                            "placement":obs.placement(),"reason":"clear shorter legal continuation from the verified board; no verified moves rewritten"})
                    self.last_message = update.status
                    self._track_unresolved_position(move_evidence,update.status)
                    outcome = self.rec.board.outcome(claim_draw=False)
                    if outcome and not self.result_override:
                        self.headers["Result"] = outcome.result()
                        self.ended = self.ended or obs.timestamp
                        self.last_message = "Complete • " + outcome.termination.name.replace("_"," ").lower()
            if self.rec:
                self._record_clocks(move_evidence)
                self.persist()
            signature=(self.current_id,obs.placement(),self.last_message,obs.orientation)
            if signature!=self._last_evidence_signature:
                logging.info('Recorder state %s',json.dumps({'game_id':self.current_id,'status':self.last_message,'placement':obs.placement(),'plies':len(self.rec.verified) if self.rec else 0,'uncertain_squares':obs.uncertain_squares(max(.8,self.settings.min_confidence))}))
                self.store.save_observation(self.session_id, self.current_id, obs, self.last_message,
                    {"labels":obs.labels.tolist(), "confidence":[round(float(v),3) for v in obs.probabilities.max(axis=1)],
                     "orientation":obs.orientation,"ignored_squares":self._recognition_ignored_squares})
                self._last_evidence_signature=signature
            return self.snapshot()

    def _track_unresolved_position(self,obs,status):
        """Treat legal history as review; split only a sustained unexplained board."""
        threshold=max(.80,self.settings.min_confidence)
        eligible=(self.rec is not None
                  and status.startswith(("unmatched position","search limit","uncertain","review / rewind"))
                  and obs.placement()!=self.rec.board.board_fen()
                  and obs.confidence>=threshold
                  and not obs.uncertain_squares(threshold))
        if not eligible:
            self.clear_position_recovery()
            return

        history_path=self._find_history_path(obs)
        if history_path is not None:
            self._unresolved_position=self._unresolved_since=self._unresolved_timestamp=None
            index,moves=history_path
            self.last_message="Review position • linked to saved game history"
            if moves and index < len(self.rec.verified):
                self._track_analysis_branch(obs,index,moves)
            else:
                self._review_position=self._review_since=self._review_candidate=None
            return

        self._review_position=self._review_since=self._review_candidate=None
        current=board_labels(self.rec.board)
        target=obs.labels
        confident=obs.probabilities.max(axis=1)>=threshold
        changed=int(np.count_nonzero((current!=target)&confident))
        large_change=changed>=self.settings.new_game_min_changed_squares
        seconds=(self.settings.new_game_change_seconds if large_change
                 else self.settings.unresolved_fen_seconds)
        if seconds<=0:
            self.clear_position_recovery();return
        now=self._clock()
        if self._unresolved_position!=obs.placement():
            self._unresolved_position=obs.placement()
            self._unresolved_since=now
            self._unresolved_timestamp=obs.timestamp
        elapsed=now-self._unresolved_since
        if elapsed>=seconds:
            reason=(f"stable board differed on {changed} confident squares and was not reachable from saved PGN history"
                    if large_change else "stable board remained unresolved for configured timeout")
            if self._resume_latest_game_at_position(obs):
                self.clear_position_recovery()
                return
            # Small disagreements and ambiguous legal paths are recovery work,
            # not evidence of a new game. Preserve the active prefix indefinitely.
            if not large_change or status.startswith(('uncertain','search limit')):
                self.last_message=status+' • existing PGN preserved; waiting for clearer continuation'
                return
            try:
                self._start_from_visible(obs,reason,self._unresolved_timestamp)
            except ValueError:
                self.clear_position_recovery()
                self.last_message=status+' • visible pieces do not form a valid FEN; existing game preserved'
                logging.warning(self.last_message)
        else:
            remaining=max(1,int(seconds-elapsed+.999))
            label="possible new game" if large_change else "unresolved position"
            self.last_message=f"{status} • {label} ({changed} changed squares); checking saved PGNs in {remaining}s if stable"

    def _find_history_path(self,obs):
        """Find an exact or short legal continuation from any verified PGN position."""
        if not self.rec:return None
        positions=[];board=chess.Board(self.rec.initial_fen);positions.append(board.copy())
        for uci in self.rec.verified:
            board.push_uci(uci);positions.append(board.copy())
        threshold=max(.80,self.settings.min_confidence)
        for index in range(len(positions)-1,-1,-1):
            if obs.matches(positions[index],threshold):return index,()
        target=obs.labels
        confident=obs.probabilities.max(axis=1)>=threshold
        candidates=[]
        max_changes=4*min(3,self.settings.max_plies)
        for index,position in enumerate(positions):
            distance=int(np.count_nonzero((board_labels(position)!=target)&confident))
            if distance<=max_changes:
                candidates.append((distance,-index,index,position))
        candidates.sort(key=lambda item:(item[0],item[1]))
        started=time.monotonic();used_nodes=0
        for _,__,index,position in candidates[:40]:
            remaining=8000-used_nodes
            if remaining<1000 or (time.monotonic()-started)*1000>45:break
            searcher=LegalSearcher(min(3,self.settings.max_plies),min(1600,remaining),45,
                                   threshold,path_limit=32)
            result=searcher.search(position,obs);used_nodes+=result.nodes
            if result.paths:
                path=(tuple(move.uci() for move in result.paths[0])
                      if result.exhaustive and len(result.paths)==1 else ())
                return index,path
        return None

    def _track_analysis_branch(self,obs,index,moves):
        signature=(index,tuple(moves))
        if self._review_position!=obs.placement() or self._review_candidate!=signature:
            self._review_position=obs.placement();self._review_candidate=signature;self._review_since=self._clock();self._review_recorded=None
            return
        if self._review_recorded==signature:return
        if self._clock()-self._review_since<self.settings.new_game_change_seconds:return
        board=chess.Board(self.rec.initial_fen)
        for uci in self.rec.verified[:index]:board.push_uci(uci)
        sans=[]
        for uci in moves:
            move=chess.Move.from_uci(uci);sans.append(board.san(move));board.push(move)
        try:
            self.annotate(self.current_id,[0]*index,' '.join(sans),
                          comment='Observed analysis branch; not confirmed as part of the played main line.',
                          automatic=True)
            self._review_recorded=signature
            self.last_message="Review position • legal analysis variation saved"
        except ValueError:
            self.last_message="Review position • legal continuation linked to saved game"

    def clear_position_recovery(self):
        self._unresolved_position=self._unresolved_since=self._unresolved_timestamp=None
        self._review_position=self._review_since=self._review_candidate=None
        self._review_recorded=None

    def persist(self):
        if not self.rec:
            return
        comment = self.note
        pending = any(b.moves for b in self.rec.branches) or len(self.rec.branches)>1 or self.rec.incomplete
        if pending:
            comment += (" Final move awaits opponent response or explicit confirmation; only the verified prefix is exported."
                        if self.rec.confirmation_plies and len(self.rec.branches)==1 and len(self.rec.branches[0].moves)==1
                        else " Unresolved observations exist; only the verified prefix is exported.")
        status = ("aborted" if self.terminal_message["reason"]=="aborted" else "complete") if self.terminal_message else ("complete" if self.ended and self.headers["Result"] != "*" else self.rec.status)
        if pending:status+=' • unresolved'
        data = self.rec.serialize()
        data["note"] = self.note
        data.update(self._extra_state())
        data['result_override']=self.result_override
        fingerprint=json.dumps([self.current_id,self.name,self.headers,data,self.ended,self.settings.export_dir,self.settings.auto_export],sort_keys=True)
        if fingerprint==self._persisted_fingerprint:return
        pgn = export_pgn(self.rec.initial_fen, self.rec.verified, self.headers, comment,self.review_pgn,self.move_clocks,self.inferred_moves)
        self.store.save_game(self.current_id,self.session_id,self.name,self.started,status,self.headers,data,pgn,self.ended)
        if self.settings.export_dir and self.settings.auto_export:
            atomic_text(Path(self.settings.export_dir)/(self.current_id+".pgn"),pgn+"\n")
        self._persisted_fingerprint=fingerprint

    def snapshot(self):
        with self.lock:
            if not self.rec:
                return {"status":self.last_message,"game_id":None,"fen":None,"moves":[],"alternatives":[]}
            b = chess.Board(self.rec.initial_fen)
            san = []
            for uci in self.rec.verified:
                san.append(b.san(chess.Move.from_uci(uci)))
                b.push_uci(uci)
            alternatives = []
            preview_board = self.rec.board
            preview_moves = []
            preview_last_move = self.rec.verified[-1] if self.rec.verified else None
            preview_candidates = 0
            ranked_branches = (self.rec.rank_branches(self.rec.branches,self.last_observation,
                               self.active_clock_turn()) if self.last_observation and len(self.rec.branches)>1 else [])
            if not self.rec.incomplete and self.rec.branches:
                preview_branch = ranked_branches[0][2] if ranked_branches else self.rec.branches[0]
                preview_board = preview_branch.board()
                preview_candidates = len(self.rec.branches) if any(
                    branch.moves for branch in self.rec.branches
                ) or len(self.rec.branches) > 1 else 0
                preview_last_move = preview_branch.moves[-1] if preview_branch.moves else preview_last_move
                leaf = chess.Board(preview_branch.root_fen)
                for uci in preview_branch.moves:
                    move = chess.Move.from_uci(uci)
                    preview_moves.append(leaf.san(move))
                    leaf.push(move)
            ordered_branches=[row[2] for row in ranked_branches] if ranked_branches else self.rec.branches
            for branch in ordered_branches:
                if branch.moves or len(self.rec.branches)>1:
                    leaf = chess.Board(branch.root_fen)
                    line = []
                    for uci in branch.moves:
                        line.append(leaf.san(chess.Move.from_uci(uci)))
                        leaf.push_uci(uci)
                    alternatives.append(" ".join(line) or ("White to move" if leaf.turn else "Black to move"))
            return {"status":self.last_message,"game_id":self.current_id,"name":self.name,
                    "recognition_ignored_squares":list(self._recognition_ignored_squares),
                    "fen":self.rec.board.fen(),"preview_fen":preview_board.fen(),
                    "preview_last_move":preview_last_move,"preview_moves":preview_moves,
                    "preview_candidates":preview_candidates,
                    "preview_confidence":(float(np.exp(ranked_branches[0][0])*100) if ranked_branches else None),
                    "preview_clock_support":(ranked_branches[0][1] if ranked_branches else 0),
                    "initial_fen":self.rec.initial_fen,"moves":san,
                    "guessed_plies":sorted(int(ply) for ply,item in self.inferred_moves.items()
                        if str(ply).isdigit() and 0<int(ply)<=len(san) and 'Guessed opening prefix' in item.get('comment','')),
                    "plies":len(san),"last_move":self.rec.verified[-1] if san else None,
                    "alternatives":alternatives,"incomplete":self.rec.incomplete,"note":self.note,
                    "result":self.headers.get("Result","*"),"terminal_message":self.terminal_message,"clocks":(self.latest_context or {}).get("clocks",{}),"players":{"white":self.headers.get('White','Unknown'),"black":self.headers.get('Black','Unknown')},
                    "provisional":bool(self.rec.confirmation_plies and len(self.rec.branches)==1 and len(self.rec.branches[0].moves)==1),
                    "pending_terminal":bool(self.rec.confirmation_plies and len(self.rec.branches)==1 and len(self.rec.branches[0].moves)==1 and self.rec.branches[0].board().is_game_over()),
                    "pending_moves":alternatives[0].split() if self.rec.confirmation_plies and len(self.rec.branches)==1 and alternatives else []}

    def finish(self, status="stopped"):
        with self.lock:
            if self.rec:
                self.rec.status = status
                self.ended = self.ended or utcnow()
                self.persist()

    def force_new(self):
        with self.lock:
            if not self.last_observation:
                raise ValueError("Capture a clear board first")
            self._start_from_visible(self.last_observation,"started manually from visible board")

    def visible_fens(self):
        """FEN candidates for the last screen position, preserving known rights if available."""
        with self.lock:
            if not self.last_observation:return []
            threshold=max(.80,self.settings.min_confidence)
            if self.last_observation.confidence<threshold or self.last_observation.uncertain_squares(threshold):return []
            placement=self.last_observation.placement();boards=[]
            if self.rec:
                board=chess.Board(self.rec.initial_fen)
                boards.append(board.copy())
                for uci in self.rec.verified:
                    board.push_uci(uci);boards.append(board.copy())
                boards.extend(branch.board() for branch in self.rec.branches)
            candidates=[]
            for board in boards:
                if board.board_fen()==placement and board.fen() not in candidates:candidates.append(board.fen())
            if not candidates:
                for turn in ["w","b"]:
                    board=chess.Board(f"{placement} {turn} - - 0 1")
                    if board.is_valid():candidates.append(board.fen())
            return candidates

    def recover(self, gid, persist=True):
        with self.lock:
            row = self.store.game(gid)
            if not row:
                raise ValueError("Recording not found")
            self.current_id, self.session_id = gid, row["session_id"]
            self.name, self.started, self.ended = row["name"],row["started"],None
            self.headers = json.loads(row["headers"])
            self.ended=(row['ended'] or utcnow()) if self.headers.get('Result','*')!='*' else None
            state = json.loads(row["state"])
            self.note = state.get("note", "")
            self._load_extras(state)
            if self.terminal_message:self.ended=row['ended'] or utcnow()
            self.result_override=state.get('result_override',False)
            self.rec = Reconstructor.restore(state,self.searcher())
            self._recognition_ignored_squares=[]
            self.rec.confirmation_plies=int(self.settings.confirm_on_reply)
            self.clear_position_recovery()
            self.rec.status = "recovered • ready to resume"
            self.last_message = self.rec.status
            if persist:
                if self._backfill_opening_prefix():self.last_message='Opening prefix guessed and restored • '+self.last_message
                self.persist()

    def choose(self, index):
        with self.lock:
            if not self.rec:
                return
            self.rec.choose(index)
            self._sync_move_clocks()
            outcome=self.rec.board.outcome(claim_draw=False)
            if outcome and not self.result_override:
                self.headers['Result']=outcome.result();self.ended=self.last_observation.timestamp if self.last_observation else utcnow()
            self.last_message = 'Complete • final move confirmed' if outcome else self.rec.status
            self.store.audit("manual reconstruction choice",{"game_id":self.current_id,"index":index})
            self.persist()

    def correct_line(self, san_text: str, undo: int = 0, expected_plies: int | None = None):
        """Append explicitly entered legal SAN to the verified prefix, never fabricate a gap."""
        with self.lock:
            if not self.rec:
                raise ValueError("No game to correct")
            if expected_plies is not None and expected_plies!=len(self.rec.verified):
                raise ValueError('The game advanced while you edited. Pause capture and reopen the correction dialog.')
            if not 0<=undo<=len(self.rec.verified):raise ValueError('Invalid number of plies to undo')
            prefix=self.rec.verified[:len(self.rec.verified)-undo] if undo else self.rec.verified[:]
            trial = chess.Board(self.rec.initial_fen)
            for uci in prefix:trial.push_uci(uci)
            moves = []
            for token in san_text.split():
                move = trial.parse_san(token)
                moves.append(move.uci())
                trial.push(move)
            if not moves and not undo:
                return
            previous=self.rec.serialize()
            self.rec.board=chess.Board(self.rec.initial_fen)
            self.rec.verified=prefix+moves
            self.move_clocks={key:value for key,value in self.move_clocks.items() if int(key)<=len(prefix)}
            self.inferred_moves={key:value for key,value in self.inferred_moves.items() if int(key)<=len(prefix)}
            self.clock_evidence={};self.review_tracker=None
            self.rec.history=[self.rec.board.board_fen()]
            for uci in self.rec.verified:
                self.rec.board.push_uci(uci);self.rec.history.append(self.rec.board.board_fen())
            from .reconstruction import Branch
            self.rec.branches = [Branch(self.rec.board.fen(), ())]
            self.rec.incomplete = False
            self.note += " A move sequence was confirmed manually."
            self.rec.status = "recording"
            if not self.result_override and not self.terminal_message:
                self.headers['Result']='*';self.ended=None
            self.store.audit("manual legal SAN correction",{"game_id":self.current_id,"moves":moves,"undone_plies":undo,"previous_state":previous})
            self.persist()

    def edit(self, gid, name, headers):
        with self.lock:
            row = self.store.game(gid)
            if not row:
                return
            if gid == self.current_id:
                if headers.get('Result','*')!=self.headers.get('Result','*'):
                    self.result_override=True
                    self.ended=utcnow() if headers.get('Result','*')!='*' else None
                    if headers.get('Result','*')=='*':self.terminal_message=None;self.review_tracker=None
                self.name, self.headers = name,headers
                self.persist()
            else:
                state = json.loads(row["state"])
                if headers.get('Result','*')!=json.loads(row['headers']).get('Result','*'):state['result_override']=True
                pgn = export_pgn(state["initial_fen"],state["verified"],headers,state.get("note",""),state.get("review_pgn",""),state.get("move_clocks",{}),state.get('inferred_moves',{}))
                self.store.save_game(gid,row["session_id"],name,row["started"],row["status"],headers,state,pgn,row["ended"])

    def combine_games(self, rows, pgn=None):
        """Save a validated combined game; source records and files remain intact."""
        with self.lock:
            pgn = pgn or join_recordings(rows,self.searcher())
            game=chess.pgn.read_game(io.StringIO(pgn))
            if game is None or game.errors:raise ValueError('Combined PGN is invalid.')
            rec=self.reconstructor(game.board())
            for move in game.mainline_moves():
                rec.board.push(move);rec.verified.append(move.uci());rec.history.append(rec.board.board_fen())
            rec.branches=[Branch(rec.board.fen(),())]
            gid=uuid.uuid4().hex
            started=min(row['started'] for row in rows)
            state={**rec.serialize(),'review_pgn':pgn,'note':game.comment,
                   'combined_source_ids':[row['id'] for row in rows]}
            self.store.save_game(gid,self.session_id,'Combined game',started,'combined',dict(game.headers),state,pgn,None)
            with self.store.transaction() as db:
                for row in rows:
                    db.execute('UPDATE games SET status=? WHERE id=?',(f'combined source • see {gid}',row['id']))
            self.recover(gid,persist=False)
            self.last_message='Selected PGNs combined • originals kept'
            self.persist()
            self.store.audit('PGNs combined',{'game_id':gid,'sources':[row['id'] for row in rows]})
            return gid

    def import_pgn(self, path: Path) -> int:
        count = 0
        with path.open(encoding="utf-8-sig", errors="strict") as f:
            while (game := chess.pgn.read_game(f)) is not None:
                if game.errors:
                    raise ValueError(f"Invalid PGN: {game.errors[0]}")
                r = self.reconstructor(game.board())
                for move in game.mainline_moves():
                    r.board.push(move)
                    r.verified.append(move.uci())
                    r.history.append(r.board.board_fen())
                from .reconstruction import Branch
                r.branches = [Branch(r.board.fen(), ())]
                gid = uuid.uuid4().hex
                pgn = game.accept(chess.pgn.StringExporter(headers=True, variations=True, comments=True))
                self.store.save_game(gid,self.session_id,f"{game.headers.get('White','Unknown')} — {game.headers.get('Black','Unknown')}",
                    utcnow(),"imported",dict(game.headers),{**r.serialize(),"review_pgn":pgn,"note":game.comment},pgn,utcnow())
                count += 1
        return count
