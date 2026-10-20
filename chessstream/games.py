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
from .opening import infer_visible_opening
from .repair import simplify_shuffles,retained_annotations
from .analysis_tracking import AnalysisTracking
from .lifecycle import GameLifecycle
from .game_boundaries import GameBoundaries


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


class GameManager(GameBoundaries,AnalysisTracking,GameExtras):
    def __init__(self, store: Store, settings: Settings, session_id: str | None = None):
        self.store, self.settings = store, settings
        self.lifecycle=GameLifecycle()
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
        self._new_opening_position=None;self._new_opening_since=None
        self._boundary_position=None;self._boundary_since=None
        self._boundary_history_link=None
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
        self._settled_key=None;self._settled_since=None;self._settled_error=None
        self._frame_placement=None;self._frame_since=None
        self._timed_base=None;self._timed_end=0
        self._recovery_executor=None;self._recovery_future=None;self._recovery_token=None
        self._recovery_next=0.;self._recovery_attempt=0
        self._clock=time.monotonic
        self._reset_extras()

    def searcher(self):
        s = self.settings
        return LegalSearcher(s.max_plies, s.search_nodes, s.search_ms, s.min_confidence)

    def reconstructor(self, board, roots=None):
        return Reconstructor(board, self.searcher(), roots, int(self.settings.confirm_on_reply))

    def _create(self, board, timestamp, roots=None, note=""):
        initial_context=self.latest_context if self.rec is None else None
        initial_names=dict(self.lifecycle.names) if self.rec is None else {}
        self._reset_extras()
        self._timed_base=None;self._timed_end=0
        self._settled_key=None;self._settled_since=None
        self._new_opening_position=None;self._new_opening_since=None
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
        for color,name in initial_names.items():self.headers[color.title()]=name
        self.latest_context=initial_context;self.observed_names=initial_names
        self.lifecycle.bind(self,initial_context)
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
        opening_moves=self._infer_short_opening(obs,max_plies=14 if self.settings.infer_unseen_opening else 1)
        if len(opening_moves)>1 and not self.settings.infer_unseen_opening:opening_moves=[]
        if (len(uncertain)<=2 and obs.confidence>=max(.80,self.settings.min_confidence)
                and self._resume_initial_identity(obs)):
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
        rows=[row for row in rows if row['id'] not in self.separated_from]
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
                visible_names=self.lifecycle.names
                saved_headers=json.loads(row['headers'])
                if any(''.join(saved_headers.get(color.title(),'Unknown').casefold().split())!=''.join(name.casefold().split()) for color,name in visible_names.items()):continue
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
        moves=self._infer_short_opening(obs,max_plies=14 if self.settings.infer_unseen_opening else 1)
        if len(moves)>1 and not self.settings.infer_unseen_opening:moves=[]
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
        return ('Opening prefix guessed from the standard starting position using a bounded legal path. '
                'Pawn moves were prioritized where visual progress was equal; captures and castling were checked legally. '
                'The actual earlier move order may differ; this is an inferred opening, not recorded history.')

    def _infer_short_opening(self, obs, max_plies=14, target_turn=None):
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
        occupied=int(np.count_nonzero((labels!=0)&confident)+np.count_nonzero((expected!=0)&~confident))
        displaced=int(np.count_nonzero((expected!=0)&(labels!=expected)&confident))
        if not 30<=occupied<=32 or not 1<=displaced<=14:return []
        if np.any(obs.probabilities[np.arange(64)[~confident],expected[~confident]]<.05):return []
        key=(obs.probabilities.tobytes(),max_plies,target_turn,threshold,
             self.settings.search_nodes,self.settings.search_ms)
        if self._opening_cache and self._opening_cache[0]==key:return list(self._opening_cache[1])
        moves=[]
        if displaced<=6:
            search=LegalSearcher(max_plies=min(6,max_plies),
                node_limit=min(60000,max(1000,self.settings.search_nodes)),
                time_limit_ms=min(400,max(50,self.settings.search_ms)),threshold=threshold)
            result=search.search(initial,obs,target_turn=target_turn,first_shortest=True,pawn_first=True)
            if result.shortest_proven and result.paths and result.paths[0]:
                moves=[move.uci() for move in result.paths[0]]
        if not moves and max_plies>6:
            probabilities=obs.probabilities.copy()
            probabilities[~confident]=0
            probabilities[np.arange(64)[~confident],expected[~confident]]=1
            evidence=Observation(probabilities,obs.timestamp,obs.orientation,obs.quality)
            moves=infer_visible_opening(evidence,max_plies=min(14,max_plies),target_turn=target_turn)
            trial=chess.Board()
            for uci in moves:
                move=chess.Move.from_uci(uci);changed={move.from_square,move.to_square}
                if trial.is_castling(move):
                    rank=chess.square_rank(move.from_square)
                    changed.update((chess.square(7 if move.to_square>move.from_square else 0,rank),
                                    chess.square(5 if move.to_square>move.from_square else 3,rank)))
                if any(not confident[square] for square in changed):moves=[];break
                trial.push(move)
        if not moves:
            self._opening_cache=(key,())
            return []
        board=chess.Board()
        for uci in moves:
            board.push_uci(uci)
        if not obs.matches(board,threshold):return []
        self._opening_cache=(key,tuple(moves))
        return moves

    def opening_ready(self, obs):
        with self.lock:
            if obs.placement()==chess.Board().board_fen():return False
            if self._infer_short_opening(obs,max_plies=14 if self.settings.infer_unseen_opening else 1):return True
            return (not obs.uncertain_squares(max(.8,self.settings.min_confidence))
                    and len(chess.Board(f'{obs.placement()} w - - 0 1').piece_map())>=4
                    and any(chess.Board(f'{obs.placement()} {turn} - - 0 1').is_valid() for turn in ('w','b')))

    def _backfill_opening_prefix(self):
        """Repair an application-created early FEN segment without losing its continuation."""
        if (not self.settings.infer_unseen_opening or not self.rec or self.rec.initial_fen==chess.STARTING_FEN or self.headers.get('Result','*')!='*'
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
            self.inferred_moves[str(ply)]={'uci':uci,'comment':'Guessed opening prefix restored before an earlier FEN recording; captures and double pawn pushes prioritized.'}
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
            self.inferred_moves[str(ply)]={'uci':uci,'comment':'Guessed opening prefix: bounded legal path to the visible position; captures and double pawn pushes were prioritized where possible; earlier move order may differ.'}
        for uci in confirmed:
            self.rec.board.push_uci(uci)
            self.rec.verified.append(uci)
            self.rec.history.append(self.rec.board.board_fen())
        self.rec.branches=[Branch(self.rec.board.fen(),tuple(moves[len(confirmed):]))]
        self.rec.status=("provisional move • opening guessed; waiting for opponent response" if pending else
                         "recording • opening guessed from visible position")
        self._persisted_fingerprint=None

    def _start_from_visible(self, obs, reason, since=None):
        opening_moves=self._infer_short_opening(obs,max_plies=14 if self.settings.infer_unseen_opening else 1)
        if len(opening_moves)>1 and not self.settings.infer_unseen_opening:opening_moves=[]
        board,roots,note=self._visible_roots(obs)
        previous_id=self.current_id
        if self.rec:
            self.note += " A separate PGN segment was started from the visible board FEN; this game's saved moves remain unchanged."
            self.finish("preserved • continued from visible FEN")
        self.rec=None
        self.reset_candidate=None
        self._create(board,obs.timestamp,roots,note+" Temporary visible board FEN segment.")
        self._seed_opening(opening_moves)
        if opening_moves:
            ignored=obs.uncertain_squares(max(.8,self.settings.min_confidence))
            self._recognition_ignored_squares=ignored
            if ignored:self.note+=' Uncertain unchanged starting squares retained: '+', '.join(ignored)+'.'
        self.persist()
        self.last_message="New PGN started from the visible board position"
        self.clear_position_recovery()
        self.store.audit("visible FEN checkpoint",{"previous_game_id":previous_id,"game_id":self.current_id,
            "reason":reason,"fen":board.fen(),"side_to_move":"inferred" if roots and len(roots)>1 else ("white" if board.turn else "black")})
        start=since or obs.timestamp
        self.store.associate_screenshots(self.session_id,self.current_id,since=start)
        with self.store.transaction() as db:
            db.execute("UPDATE observations SET game_id=? WHERE session_id=? AND timestamp>=?",(self.current_id,self.session_id,start))

    def _consider_new_opening(self,obs):
        """Prefer a fresh opening after a short stable divergence from recent PGNs."""
        if not self.settings.infer_unseen_opening:return False
        if (self.settings.initial_fen or not self.rec or self.premove_state or obs.confidence<.85
                or len(obs.uncertain_squares(max(.80,self.settings.min_confidence)))>2):
            self._new_opening_position=self._new_opening_since=None
            return False
        names=(self.latest_context or {}).get('names',{})
        changed_name=any(color in self.observed_names and
                         ''.join(self.observed_names[color].casefold().split())!=''.join(name.casefold().split())
                         for color,name in names.items())
        strong_boundary=changed_name and self.clocks_recently_reset()
        placement=obs.placement()
        if not strong_boundary and (placement in self.rec.history or
                any(branch.board().board_fen()==placement for branch in self.rec.branches)):
            self._new_opening_position=self._new_opening_since=None
            return False
        visible=chess.Board(f'{placement} w - - 0 1')
        changed=sum(self.rec.board.piece_at(square)!=visible.piece_at(square) for square in chess.SQUARES)
        if (not strong_boundary and changed<=4
                and LegalSearcher(1,2000,30,self.settings.min_confidence).search(self.rec.board,obs).paths):
            self._new_opening_position=self._new_opening_since=None
            return False
        opening=self._infer_short_opening(obs)
        if len(opening)<(1 if strong_boundary else 2):
            self._new_opening_position=self._new_opening_since=None
            return False
        target=chess.Board()
        for uci in opening:target.push_uci(uci)
        placement=target.board_fen()
        opening_obs=Observation.from_board(target);opening_obs.timestamp=obs.timestamp;opening_obs.orientation=obs.orientation
        if self._new_opening_position!=placement:
            self._new_opening_position=placement;self._new_opening_since=self._clock()
            return False
        if self._clock()-self._new_opening_since<1.0:return False
        rows=self.store.query("SELECT id,state,headers FROM games WHERE status!='imported' AND status NOT LIKE 'combined source%' ORDER BY started DESC,updated DESC LIMIT 3")
        # Current plus the two most recent saved PGNs. A known position is
        # review/replay evidence, even when a guessed opening order differs.
        for row in rows:
            if row['id'] in self.separated_from:continue
            try:
                saved=Reconstructor.restore(json.loads(row['state']),self.searcher())
            except (TypeError,ValueError,KeyError,chess.IllegalMoveError):continue
            known=set(saved.history)
            known.update(branch.board().board_fen() for branch in saved.branches)
            if placement in known and not strong_boundary:
                if row['id']!=self.current_id:self._resume_latest_game_at_position(obs)
                return False
        # A legal continuation from the active endpoint has priority over a
        # split, unless fresh identity and reset clocks show a new game.
        if not self.terminal_message and not strong_boundary:
            line=infer_visible_opening(opening_obs,start_board=self.rec.board,max_plies=14,
                                       time_limit_ms=250,node_limit=30000)
            if line:
                before=len(self.rec.verified)
                accepted=line[:-1] if self.settings.confirm_on_reply else line
                for uci in accepted:
                    self.rec.board.push_uci(uci);self.rec.verified.append(uci)
                    self.rec.history.append(self.rec.board.board_fen())
                self.rec.branches=[Branch(self.rec.board.fen(),tuple(line[len(accepted):]))]
                self.rec.incomplete=False
                self.rec.status=self.last_message='Opening continuation linked to current PGN • skipped moves inferred'
                for ply,uci in enumerate(line,before+1):
                    self.inferred_moves[str(ply)]={'uci':uci,'comment':'Inferred across a skipped opening; one legal order was selected from the visible position.'}
                self.store.audit('opening continuation linked',{'game_id':self.current_id,'after_ply':before,'moves':line})
                self.rewind_state=None
                self._new_opening_position=self._new_opening_since=None
                self.persist()
                return True
        if not strong_boundary:
            link=self._find_history_path(opening_obs,max_plies=6,min_ply=2,time_limit_ms=150,node_limit=16000)
            if link is not None:
                self._boundary_history_link=(self.current_id,tuple(self.rec.verified),placement)
                return False
        previous=self.current_id
        excluded=[row['id'] for row in rows if row['id']!=previous][:2] if strong_boundary else []
        if strong_boundary:excluded.insert(0,previous)
        self._start_from_visible(obs,'stable opening could not be linked to either of the two recent PGNs',obs.timestamp)
        self.separated_from=excluded
        if names:
            self.observed_names=dict(names)
            for color,name in names.items():
                if color in ('white','black'):self.headers[color.title()]=name
        self.last_message='New opening detected • PGN guessed from visible position'
        self.store.audit('new opening split',{'previous_game_id':previous,'game_id':self.current_id,
            'placement':placement,'inferred_opening':opening})
        self.persist()
        return True

    def _consider_unlinked_position(self,obs):
        """A stable unrelated board must not stay trapped in rewind/recovery."""
        threshold=max(.8,self.settings.min_confidence)
        if (not self.settings.split_unlinked_positions or not self.rec or self.settings.initial_fen
                or self.premove_state or obs.confidence<threshold or obs.uncertain_squares(threshold)
                or obs.matches(self.rec.board,threshold)
                or any(obs.matches(branch.board(),threshold) for branch in self.rec.branches)):
            self._boundary_position=self._boundary_since=None;return False
        placement=obs.placement()
        if placement in self.rec.history:
            self._boundary_position=self._boundary_since=None;return False
        changed=int(np.count_nonzero(board_labels(self.rec.board)!=obs.labels))
        if changed<self.settings.new_game_min_changed_squares:return False
        if not any(chess.Board(f'{placement} {turn} - - 0 1').is_valid() for turn in ('w','b')):return False
        if self._boundary_position!=placement:
            self._boundary_position=placement;self._boundary_since=self._clock();return False
        if self._clock()-self._boundary_since<self.settings.new_game_change_seconds:return False
        self._boundary_since=self._clock()
        link=self._find_history_path(obs,max_plies=6,min_ply=2 if len(self.rec.verified)>6 else 0,
                                     time_limit_ms=250,node_limit=30000)
        if link is not None:
            self._boundary_history_link=(self.current_id,tuple(self.rec.verified),placement)
            return False
        if self._resume_latest_game_at_position(obs):return False
        previous=self.current_id
        self.cancel_background_recovery()
        self._start_from_visible(obs,'stable new position could not be linked to recent PGNs or earlier played positions')
        self._boundary_position=self._boundary_since=None
        self.last_message='New position • previous PGN saved; recording the visible game'
        self.store.audit('unlinked position split',{'previous_game_id':previous,'game_id':self.current_id,
            'placement':placement,'checked_history_depth':6,'search_ms':250})
        return True

    def process(self, obs: Observation) -> dict:
        with self.lock:
            self.last_observation = obs
            if self.lifecycle_gate(obs):return self.lifecycle_snapshot(obs)
            move_evidence=obs
            self._recognition_ignored_squares=[]
            if self.rec and self._handle_saved_analysis(obs):
                self.reset_settling();self.persist()
                self.store.save_observation(self.session_id,self.current_id,obs,self.last_message,{'analysis':True,'cursor':self.analysis_cursor})
                snapshot=self.snapshot()
                snapshot.update(preview_fen=obs.placement()+' w - - 0 1',preview_moves=[],preview_last_move=None)
                return snapshot
            if self.rec and self.lifecycle.mode=='auto':self._consider_new_opening(obs)
            if self.rec and self.lifecycle.mode=='auto':self._consider_unlinked_position(obs)
            if self.rec and self._handle_rewind(obs):
                self.reset_settling()
                self.persist()
                self.store.save_observation(self.session_id,self.current_id,obs,self.last_message,
                    {'rewind':True,'anchor_ply':self.rewind_state['anchor_ply'] if self.rewind_state else None})
                snapshot=self.snapshot()
                snapshot.update(preview_fen=obs.placement()+' w - - 0 1',preview_moves=[],
                                preview_last_move=None)
                return snapshot
            if self.rec and not self.terminal_message and self._handle_premove(obs):
                self.reset_settling()
                self.persist()
                snapshot=self.snapshot()
                snapshot.update(preview_fen=obs.placement()+' w - - 0 1',preview_moves=[],preview_last_move=None)
                return snapshot
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
                if (is_start and (self.rec.verified or self.terminal_message) and self.rec.board.board_fen() != obs.placement()
                        and not (not self.terminal_message and self.headers.get('Result','*')=='*'
                                 and LegalSearcher(1,2000,30,self.settings.min_confidence).search(self.rec.board,obs).paths)):
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
                    self._revise_timed_hover(obs)
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
                self._settle_position(move_evidence)
                if obs.matches(self.rec.board,max(.8,self.settings.min_confidence)):
                    self.repair_current(automatic=True)
                if not self.terminal_message and not self.result_override:
                    outcome=self.rec.board.outcome(claim_draw=False)
                    if outcome:
                        self.headers['Result']=outcome.result();self.ended=self.ended or obs.timestamp
                        self.last_message='Complete • '+outcome.termination.name.replace('_',' ').lower()
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

    def _handle_premove(self, obs):
        """An inactive-side-only change cannot justify invented waiting moves."""
        if obs.confidence<.8 or obs.uncertain_squares(self.settings.min_confidence):
            return bool(self.premove_state)
        boards=[branch.board() for branch in self.rec.branches] or [self.rec.board]
        distances=[int(np.count_nonzero(board_labels(board)!=obs.labels)) for board in boards]
        nearest=[board for board,distance in zip(boards,distances) if distance==min(distances)]
        if len({board.turn for board in nearest})!=1:
            self.premove_state=None;return False
        for board in nearest[:8]:
            if board.board_fen()==obs.placement():break
            changed=np.flatnonzero(board_labels(board)!=obs.labels)
            if not 2<=len(changed)<=4:continue
            # There must be no changed piece belonging to the active player.
            if any(obs.labels[s] and (obs.labels[s]<=6)==board.turn for s in changed):continue
            opposite=board.copy();opposite.turn=not board.turn;opposite.ep_square=None
            result=LegalSearcher(1,2000,25,self.settings.min_confidence).search(opposite,obs)
            if not result.paths:continue
            move=result.paths[0][0]
            state={'placement':obs.placement(),'move':move.uci(),'waiting_for':'white' if board.turn else 'black'}
            if self.premove_state!=state:
                self.store.audit('possible premove held',{'game_id':self.current_id,**state,
                    'reason':'only the inactive side moved; no opponent move observed'})
            self.premove_state=state
            self.rec.status=self.last_message='Possible premove • waiting for opponent move; excluded from PGN'
            return True
        if self.premove_state:
            self.store.audit('premove view cleared',{'game_id':self.current_id,'placement':obs.placement()})
        self.premove_state=None
        return False

    def cancel_background_recovery(self):
        if self._recovery_executor:self._recovery_executor.shutdown(wait=False,cancel_futures=True)
        self._recovery_executor=None;self._recovery_future=None;self._recovery_token=None

    def background_recovery(self,obs,evidence=()):
        """Poll/queue longer bounded work while the capture thread keeps comparing."""
        from concurrent.futures import ThreadPoolExecutor
        from .recovery import recover_gap
        with self.lock:
            if not self.rec:return False
            if self.lifecycle_gate(obs):return False
            token=(self.current_id,self.rec.initial_fen,tuple(self.rec.verified),obs.placement(),self.lifecycle.generation)
            if self._recovery_future:
                if not self._recovery_future.done():return self._recovery_token==token
                try:result=self._recovery_future.result()
                except Exception:
                    logging.exception('Background legal recovery failed');result=None
                expected=self._recovery_token;self._recovery_future=None
                if (result and expected==token and not self.premove_state and not self.rewind_state
                        and not self.terminal_message):
                    base,recovered=result;before=len(base['verified'])
                    if before<len(self.rec.verified):
                        self.inferred_moves={k:v for k,v in self.inferred_moves.items() if int(k)<=before}
                        self.move_clocks={k:v for k,v in self.move_clocks.items() if int(k)<=before}
                        self._trim_timed_review(before)
                    self.rec=Reconstructor.restore(recovered,self.searcher())
                    self._timed_base=base;self._timed_end=len(self.rec.verified)
                    for ply in range(before,len(self.rec.verified)):
                        self.inferred_moves[str(ply+1)]={'uci':self.rec.verified[ply],
                            'comment':'Inferred: background gap recovery matched observed placement; move order not independently verified.'}
                    self.rec.status=self.last_message='Recording • gap recovered using buffered evidence'
                    self.store.audit('background gap recovered',{'game_id':self.current_id,'after_ply':before,
                        'moves':self.rec.verified[before:],'placement':obs.placement()})
                    self.persist();return False
            eligible=(not self.premove_state and not self.rewind_state and not self.terminal_message
                and not obs.uncertain_squares(max(.8,self.settings.min_confidence))
                and self.rec.status.startswith(('unmatched','search limit','uncertain'))
                and obs.placement() not in self.rec.history)
            if not eligible or self._clock()<self._recovery_next:return False
            # Recheck premoves before a larger search can invent a waiting move.
            if self._handle_premove(obs):return False
            if self._recovery_executor is None:self._recovery_executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='chess-gap')
            states=[self.rec.serialize()]
            for before in range(max(0,len(self.rec.verified)-8),len(self.rec.verified)):
                if str(before+1) not in self.inferred_moves:continue
                probe=self.reconstructor(chess.Board(self.rec.initial_fen))
                for uci in self.rec.verified[:before]:
                    probe.board.push_uci(uci);probe.verified.append(uci);probe.history.append(probe.board.board_fen())
                states.append(probe.serialize())
            self._recovery_attempt=min(self._recovery_attempt+1,3)
            self._recovery_token=token;self._recovery_next=self._clock()+3
            self.store.audit('background gap queued',{'game_id':self.current_id,'buffered_observations':len(evidence),
                'attempt':self._recovery_attempt,'placement':obs.placement(),'max_ms':min(1500,self.settings.search_ms*(1+self._recovery_attempt))})
            self._recovery_future=self._recovery_executor.submit(recover_gap,states,obs,
                max(6,self.settings.max_plies),min(300000,self.settings.search_nodes*3),
                min(1500,self.settings.search_ms*(1+self._recovery_attempt)),evidence,self.settings.min_confidence)
            return True

    def _discard_inferred_rook_cycles(self):
        """On confirmed rewind, remove recent guessed four-ply rook round trips."""
        old=list(self.rec.verified)
        positions=[chess.Board(self.rec.initial_fen)];rook_moves=[]
        for uci in old:
            board=positions[-1].copy();move=chess.Move.from_uci(uci)
            rook_moves.append(board.piece_type_at(move.from_square)==chess.ROOK and not board.is_capture(move))
            board.push(move);positions.append(board)
        for start in range(max(0,len(old)-12),len(old)-3):
            end=start+4
            if (not all(rook_moves[start:end]) or
                    not all(str(p+1) in self.inferred_moves for p in range(start,end)) or
                    positions[start].board_fen()!=positions[end].board_fen()):continue
            retained=old[:start]+old[end:]
            probe=self.reconstructor(chess.Board(self.rec.initial_fen))
            for uci in retained:
                move=chess.Move.from_uci(uci)
                if move not in probe.board.legal_moves:break
                probe.board.push(move);probe.verified.append(uci);probe.history.append(probe.board.board_fen())
            else:
                probe.branches=[Branch(probe.board.fen(),())]
                def shifted(values):
                    return {str(int(k)-4 if int(k)>end else int(k)):v for k,v in values.items()
                            if not start<int(k)<=end}
                self.move_clocks=shifted(self.move_clocks);self.inferred_moves=shifted(self.inferred_moves)
                self._trim_timed_review(start)
                self.rec=probe;self._timed_base=None;self._timed_end=0
                self.store.audit('rewind additions deleted',{'game_id':self.current_id,'after_ply':start,
                    'removed':old[start:end],'reason':'inferred rook round trip contradicted by rewind evidence'})
                return

    def _handle_rewind(self, obs):
        """Check saved history before forward search can invent a return detour."""
        if obs.confidence<.8 or obs.uncertain_squares(self.settings.min_confidence):
            return bool(self.rewind_state)
        placement=obs.placement();live={self.rec.board.board_fen()}
        live.update(branch.board().board_fen() for branch in self.rec.branches)
        if placement in live:
            if self.rewind_state:
                self.store.audit('video rewind ended',{'game_id':self.current_id,'placement':placement})
                self.rewind_state=None
            return False
        # A genuine terminal/new-game reset is handled by the ordinary game logic.
        if placement==chess.Board().board_fen() and (self.terminal_message or self.headers.get('Result','*')!='*' or self.clocks_recently_reset()):
            self.rewind_state=None;return False
        history=[i for i,p in enumerate(self.rec.history[:-1]) if p==placement]
        direct=LegalSearcher(1,2000,30,self.settings.min_confidence).search(self.rec.board,obs)
        if history and not direct.paths:
            cursor=max(history)
            if not self.rewind_state:
                self._discard_inferred_rook_cycles()
                history=[i for i,p in enumerate(self.rec.history[:-1]) if p==placement]
                if history:cursor=max(history)
                self.rewind_state={'anchor_ply':len(self.rec.verified),'cursor':cursor}
                self.store.audit('video rewind detected',{'game_id':self.current_id,'anchor_ply':len(self.rec.verified),
                    'review_ply':cursor,'placement':placement,'reason':'earlier saved board, not a legal next move'})
                # Remove unconfirmed additions; no earlier accepted mainline is deleted.
                pending=[list(branch.moves) for branch in self.rec.branches if branch.moves]
                if pending:
                    self.store.audit('rewind pending additions removed',{'game_id':self.current_id,'moves':pending})
                self.rec.branches=[Branch(self.rec.board.fen(),())]
                self.rec.incomplete=False
                self._timed_base=None;self._timed_end=0
            self.rewind_state['cursor']=cursor
            self.rec.status=self.last_message='Review position • video rewind detected; PGN protected'
            return True
        if not self.rewind_state:return False
        # Seeking forward can skip the exact anchor image. Reconnect only when
        # it extends the live endpoint and is not just another review step.
        if direct.paths:
            self.rewind_state=None
            self.store.audit('video rewind ended',{'game_id':self.current_id,'reason':'legal next move from live endpoint'})
            return False
        cursor=chess.Board(self.rec.initial_fen)
        for uci in self.rec.verified[:self.rewind_state['cursor']]:cursor.push_uci(uci)
        review=LegalSearcher(2,4000,40,self.settings.min_confidence).search(cursor,obs,first_shortest=True)
        forward=LegalSearcher(self.settings.max_plies,min(12000,self.settings.search_nodes),
                             min(100,self.settings.search_ms),self.settings.min_confidence).search(self.rec.board,obs,first_shortest=True)
        if forward.paths and not review.paths:
            self.rewind_state=None
            self.store.audit('video rewind ended',{'game_id':self.current_id,'reason':'legal continuation beyond live endpoint'})
            return False
        self.rec.status=self.last_message='Review position • rewind in progress; PGN protected'
        return True

    def _revise_timed_hover(self, obs):
        """Prefer a corrected last drop over a reversible multi-move detour."""
        if (not self._timed_base or len(self.rec.verified)!=self._timed_end
                or obs.matches(self.rec.board,self.settings.min_confidence)):
            return
        probe=Reconstructor.restore(self._timed_base,self.searcher())
        result=LegalSearcher(1,min(2000,self.settings.search_nodes),min(30,self.settings.search_ms),
                            self.settings.min_confidence).search(probe.board,obs,first_shortest=True)
        if not result.paths:return
        before=len(probe.verified)
        self.rec=probe
        self.inferred_moves={k:v for k,v in self.inferred_moves.items() if int(k)<=before}
        self.move_clocks={k:v for k,v in self.move_clocks.items() if int(k)<=before}
        self._trim_timed_review(before)
        self._timed_base=None;self._timed_end=0
        self.store.audit('timed move corrected',{'game_id':self.current_id,'after_ply':before,
            'placement':obs.placement(),'reason':'alternate legal last drop; earlier prefix retained'})

    def _trim_timed_review(self, before):
        if not self.review_pgn:return
        game=chess.pgn.read_game(io.StringIO(self.review_pgn))
        if not game:return
        node=game
        for _ in range(before):
            if not node.variations:break
            node=node.variations[0]
        if node.variations:node.remove_variation(node.variations[0])
        self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))

    def _repair_inferred_suffix(self, obs, milliseconds, nodes):
        """Revisit at most eight recent plies, only starting at an inferred move.

        A guessed capture may remove a piece that later reappears. Forward
        search can never recreate it; retry from before the bad inferred suffix.
        No mutation is made until an exact legal endpoint has been found.
        """
        old=self.rec;started=time.monotonic();used=0
        candidates=[ply for ply in range(max(0,len(old.verified)-8),len(old.verified))
                    if str(ply+1) in self.inferred_moves]
        # Earlier guesses get the opportunity to explain away a false capture.
        for before in candidates:
            remaining_ms=milliseconds-(time.monotonic()-started)*1000
            if remaining_ms<=0 or nodes-used<=0:break
            probe=self.reconstructor(chess.Board(old.initial_fen))
            for uci in old.verified[:before]:
                probe.board.push_uci(uci);probe.verified.append(uci);probe.history.append(probe.board.board_fen())
            search=LegalSearcher(max(6,self.settings.max_plies),nodes-used,remaining_ms,self.settings.min_confidence)
            result=search.search(probe.board,obs,first_shortest=True);used+=result.nodes
            if not result.paths:continue
            base=probe.serialize()
            for move in result.paths[0]:
                probe.board.push(move);probe.verified.append(move.uci());probe.history.append(probe.board.board_fen())
            if probe.board.board_fen()!=obs.placement():continue
            if probe.verified==old.verified:continue
            probe.branches=[Branch(probe.board.fen(),())];probe.incomplete=False
            self.store.audit('inferred suffix repaired',{'game_id':self.current_id,'after_ply':before,
                'replaced':old.verified[before:],'replacement':probe.verified[before:],
                'placement':obs.placement(),'reason':'later visual evidence contradicted recent inferred moves'})
            return base,probe
        return None

    def _settle_position(self, obs):
        """Two seconds of board evidence permits a labeled, revisable guess."""
        now=self._clock();key=(self.current_id,obs.placement())
        if obs.confidence<.8 or obs.uncertain_squares(self.settings.min_confidence):
            self._settled_key=None;self._settled_since=None
            return
        if self._settled_key!=key:
            self._settled_key=key
            self._settled_since=(self._frame_since if self._frame_placement==obs.placement() and self._frame_since is not None else now)
            self._settled_error=None
        elapsed=now-self._settled_since
        if elapsed<.5 or self.terminal_message:return
        if obs.matches(self.rec.board,self.settings.min_confidence):return
        if obs.placement() in self.rec.history[:-1]:return  # review is not play
        # A reply that extends the committed suffix removes its rollback privilege.
        if self._timed_base and len(self.rec.verified)>self._timed_end:
            self._timed_base=None
        candidates=[b for b in self.rec.branches if b.moves and obs.matches(b.board(),self.settings.min_confidence)]
        base=None;chosen=None
        if candidates:
            # Preserve the existing capture-continuity ordering on known paths.
            branch=candidates[0]
            base=self.rec.serialize()
            probe=Reconstructor.restore(base,self.searcher())
            probe.incomplete=False
            probe.choose(self.rec.branches.index(branch))
            chosen=probe
        else:
            # Search only until the first shortest endpoint match. Exhausting all
            # equivalent move orders is unnecessary for an explicitly guessed line.
            states=([self._timed_base] if self._timed_base else [])+[self.rec.serialize()]
            budget_started=time.monotonic();used=0
            for state in states:
                probe=Reconstructor.restore(state,self.searcher())
                remaining_ms=self.settings.search_ms-(time.monotonic()-budget_started)*1000
                remaining_nodes=self.settings.search_nodes-used
                if remaining_ms<=0 or remaining_nodes<=0:break
                search=LegalSearcher(max(6,self.settings.max_plies),remaining_nodes,remaining_ms,self.settings.min_confidence)
                result=search.search(probe.board,obs,first_shortest=True)
                used+=result.nodes
                if not result.paths:continue
                before=len(probe.verified)
                for move in result.paths[0]:
                    probe.board.push(move);probe.verified.append(move.uci());probe.history.append(probe.board.board_fen())
                if not obs.matches(probe.board,self.settings.min_confidence):continue
                probe.branches=[Branch(probe.board.fen(),())];probe.incomplete=False
                base=state;chosen=probe
                break
        if chosen is None and not candidates:
            remaining_ms=self.settings.search_ms-(time.monotonic()-budget_started)*1000
            remaining_nodes=self.settings.search_nodes-used
            repaired=self._repair_inferred_suffix(obs,remaining_ms,remaining_nodes)
            if repaired:
                base,chosen=repaired
        if chosen is not None:
            before=len(base['verified'])
            if before<len(self.rec.verified):
                # Discard only annotations attached to the replaceable guessed suffix.
                self.inferred_moves={k:v for k,v in self.inferred_moves.items() if int(k)<=before}
                self.move_clocks={k:v for k,v in self.move_clocks.items() if int(k)<=before}
                self._trim_timed_review(before)
            self._timed_base=base;self._timed_end=len(chosen.verified)
            self.rec=chosen
            for ply in range(before,len(chosen.verified)):
                self.inferred_moves[str(ply+1)]={'uci':chosen.verified[ply],
                    'comment':'Inferred: position unchanged for at least 0.5 seconds; best-effort legal order, not independently verified.'}
            self.rec.status='recording • accepted after 0.5 seconds (inferred)'
            self.last_message=self.rec.status
            self.store.audit('settled position accepted',{'game_id':self.current_id,'after_ply':before,
                'moves':chosen.verified[before:],'placement':obs.placement(),'elapsed':elapsed})
            self.clear_position_recovery()
        elif elapsed>=3:
            self.last_message='Recovery error • position unresolved for 3 seconds; PGN kept; retrying legal gap'
            if self._settled_error!=key:
                self.store.audit('settled position recovery error',{'game_id':self.current_id,'placement':obs.placement(),
                    'elapsed':elapsed,'reason':'No legal connection found within resource limits; saved prefix retained'})
                self._settled_error=key

    def _track_unresolved_position(self,obs,status):
        """Treat legal history as review; split only a sustained unexplained board."""
        if not self.settings.split_unlinked_positions:
            self.clear_position_recovery();return
        threshold=max(.80,self.settings.min_confidence)
        eligible=(self.rec is not None
                  and status.startswith(("unmatched position","search limit","uncertain","review / rewind"))
                  and obs.placement()!=self.rec.board.board_fen()
                  and obs.confidence>=threshold
                  and not obs.uncertain_squares(threshold))
        if not eligible:
            self.clear_position_recovery()
            return

        if self._boundary_history_link==(self.current_id,tuple(self.rec.verified),obs.placement()):
            self.clear_position_recovery()
            self.last_message='Review position • linked to earlier PGN history'
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

    def _find_history_path(self,obs,max_plies=None,min_ply=0,time_limit_ms=45,node_limit=8000):
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
        depth=max_plies or min(3,self.settings.max_plies)
        max_changes=4*depth
        for index,position in enumerate(positions):
            if index<min_ply:continue
            distance=int(np.count_nonzero((board_labels(position)!=target)&confident))
            if distance<=max_changes:
                candidates.append((distance,-index,index,position))
        candidates.sort(key=lambda item:(item[0],item[1]))
        started=time.monotonic();used_nodes=0
        for _,__,index,position in candidates[:40]:
            remaining=node_limit-used_nodes
            milliseconds=time_limit_ms-(time.monotonic()-started)*1000
            if remaining<1000 or milliseconds<=0:break
            searcher=LegalSearcher(depth,min(5000 if max_plies else 1600,remaining),milliseconds,
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

    def observe_frame(self, obs):
        """Count settling from first captured evidence, before animation gating."""
        with self.lock:
            if obs.confidence<.8 or obs.uncertain_squares(self.settings.min_confidence):
                self.reset_settling();return
            if self._frame_placement!=obs.placement():
                self._frame_placement=obs.placement();self._frame_since=self._clock()

    def reset_settling(self):
        self._settled_key=None;self._settled_since=None;self._settled_error=None
        self._frame_placement=None;self._frame_since=None

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
            comment += (" Final move awaits a reply, 0.5 seconds unchanged, or explicit confirmation; only accepted moves are exported."
                        if self.rec.confirmation_plies and len(self.rec.branches)==1 and len(self.rec.branches[0].moves)==1
                        else " Unresolved observations exist; only the verified prefix is exported.")
        status = ("aborted" if self.terminal_message["reason"]=="aborted" else "complete") if self.terminal_message else ("complete" if self.ended and self.headers["Result"] != "*" else self.rec.status)
        if pending:status+=' • unresolved'
        data = self.rec.serialize()
        data["note"] = self.note
        data["timed_base"]=self._timed_base;data["timed_end"]=self._timed_end
        data.update(self._extra_state())
        data['lifecycle']=self.lifecycle.saved()
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
                return {"status":self.last_message,"game_id":None,"fen":None,"moves":[],"alternatives":[],"lifecycle":self.lifecycle.summary(self)}
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
                    "lifecycle":self.lifecycle.summary(self),
                    "recognition_ignored_squares":list(self._recognition_ignored_squares),
                    "fen":self.rec.board.fen(),"preview_fen":preview_board.fen(),
                    "preview_last_move":preview_last_move,"preview_moves":preview_moves,
                    "preview_candidates":preview_candidates,
                    "preview_confidence":(float(np.exp(ranked_branches[0][0])*100) if ranked_branches else None),
                    "preview_clock_support":(ranked_branches[0][1] if ranked_branches else 0),
                    "initial_fen":self.rec.initial_fen,"moves":san,
                    "guessed_plies":sorted(int(ply) for ply,item in self.inferred_moves.items()
                        if str(ply).isdigit() and 0<int(ply)<=len(san) and ('Guessed opening prefix' in item.get('comment','') or 'Inferred:' in item.get('comment',''))),
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
            self.start_separate_game(self.last_observation,'started manually from visible board')

    def repair_current(self,automatic=False):
        """Collapse removable excursions; retain the original PGN in the audit."""
        with self.lock:
            if not self.rec:
                self.last_message='Repair PGN • capture a board first';return 0
            if automatic and (self.terminal_message or self.rewind_state or self.premove_state
                    or self.rec.initial_fen!=chess.STARTING_FEN or len(self.rec.verified)>20
                    or not any('Guessed opening prefix' in item.get('comment','') for item in self.inferred_moves.values())):
                return 0
            old=list(self.rec.verified)
            eligible=({i for i in range(len(old)) if str(i+1) not in self.move_clocks}
                      if automatic else None)
            kept=simplify_shuffles(self.rec.initial_fen,old,eligible,time_limit_ms=80 if automatic else 250)
            if len(kept)==len(old):
                if not automatic:self.last_message='Repair PGN • no removable piece round trips found'
                return 0
            removed=set(range(len(old)))-set(kept)
            # Automatic cleanup needs inferred evidence or a back-rank ghost
            # excursion. Ordinary observed repetitions remain recorded.
            if automatic:
                if len(removed)>4:return 0
                board=chess.Board(self.rec.initial_fen);ghost=False
                for i,uci in enumerate(old):
                    move=chess.Move.from_uci(uci)
                    if i in removed and chess.square_rank(move.to_square)==(7 if board.turn else 0):ghost=True
                    board.push(move)
                if not ghost and not all(str(i+1) in self.inferred_moves for i in removed):return 0
            self.persist();previous=self.store.game(self.current_id)['pgn']
            review=retained_annotations(previous,kept)
            probe=self.reconstructor(chess.Board(self.rec.initial_fen))
            for index in kept:
                probe.board.push_uci(old[index]);probe.verified.append(old[index]);probe.history.append(probe.board.board_fen())
            probe.branches=[Branch(probe.board.fen(),branch.moves) for branch in self.rec.branches]
            mapping={index+1:new+1 for new,index in enumerate(kept)}
            def remap(values):
                return {str(mapping[int(key)] if int(key)<=len(old) else len(kept)+int(key)-len(old)):value
                        for key,value in values.items() if int(key)>len(old) or int(key) in mapping}
            self.store.audit('PGN piece shuffles repaired',{'game_id':self.current_id,'automatic':automatic,
                'removed':[old[i] for i in sorted(removed)],'previous_pgn':previous,
                'previous_state':self.rec.serialize(),'retained_indices':kept})
            self.rec=probe;self.review_pgn=review
            self.move_clocks=remap(self.move_clocks);self.inferred_moves=remap(self.inferred_moves)
            self.cancel_background_recovery();self.reset_settling()
            self._timed_base=None;self._timed_end=0;self.rewind_state=None;self.clock_evidence={}
            self.last_message=self.rec.status=f'Repaired PGN • removed {len(removed)} redundant plies; final position preserved'
            self.persist()
            return len(removed)

    def join_previous_recording(self):
        """One-click bounded join; keep both source records and pending preview."""
        with self.lock:
            if not self.rec:
                self.last_message='Join previous • capture a board first';return False
            self._analysis_retry=None
            if self._try_replay_recording(self.last_observation or Observation.from_board(self.rec.board)):
                return True
            self.persist();current=self.store.game(self.current_id)
            rows=self.store.query("SELECT * FROM games WHERE id!=? AND started<=? AND status!='imported' AND status NOT LIKE 'combined source%' AND status NOT LIKE 'reconnected%' ORDER BY started DESC,updated DESC LIMIT 2",
                                  (self.current_id,current['started']))
            pending=[branch.moves for branch in self.rec.branches]
            for previous in rows:
                if previous['id'] in self.separated_from:continue
                try:pgn=join_recordings([previous,current],LegalSearcher(6,60000,500,self.settings.min_confidence))
                except ValueError:continue
                self.cancel_background_recovery()
                self.combine_games([previous,current],pgn)
                branches=[]
                for moves in pending:
                    board=self.rec.board.copy()
                    for uci in moves:
                        move=chess.Move.from_uci(uci)
                        if move not in board.legal_moves:break
                        board.push(move)
                    else:branches.append(Branch(self.rec.board.fen(),moves))
                if branches:self.rec.branches=branches
                self.last_message='Joined previous PGN • combined recording is now active; originals kept'
                self.persist();return True
            self.last_message='Join previous • no compatible connection found in the two previous PGNs'
            return False

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
            self._timed_base=state.get("timed_base");self._timed_end=state.get("timed_end",0)
            self._settled_key=None;self._settled_since=None
            self._load_extras(state)
            self.lifecycle.load(state.get('lifecycle',{}),self)
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

    def combine_games(self, rows, pgn=None, *, activate=True):
        """Save a validated combined game; optionally leave live recording active."""
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
            if activate:
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
