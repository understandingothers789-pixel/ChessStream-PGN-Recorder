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
        # The mean of 64 scores hides missing pieces and queen/knight mistakes.
        # Every square must be sufficiently supported before freezing a root FEN.
        uncertain = obs.uncertain_squares(max(.80, self.settings.min_confidence))
        if uncertain:
            self.last_message = ("Waiting for reliable recognition • uncertain squares: "
                                 + ", ".join(uncertain[:8])
                                 + (f" (+{len(uncertain)-8} more)" if len(uncertain)>8 else ""))
            return False
        if self.settings.initial_fen:
            b = chess.Board(self.settings.initial_fen)
            if not obs.matches(b, self.settings.min_confidence):
                self.last_message = "Observed board does not match the configured initial FEN"
                return False
            self._create(b, obs.timestamp)
            return True
        if self._resume_latest_game_at_position(obs):
            return True
        if obs.placement() == chess.Board().board_fen():
            self._create(chess.Board(), obs.timestamp)
            return True
        opening_moves = self._infer_short_opening(obs)
        if opening_moves:
            note = ("A unique shortest legal opening sequence from the standard starting position was inferred "
                    "from the first visible board. A different earlier history that transposed to this position "
                    "cannot be ruled out.")
            self._create(chess.Board(), obs.timestamp, note=note)
            self._seed_opening(opening_moves)
            self.last_message = "Recording • inferred unique shortest opening line: " + " ".join(
                self._san_line(chess.Board(), opening_moves))
            self.store.audit("opening prefix inferred", {"game_id":self.current_id,
                "moves":opening_moves,"method":"unique shortest legal path, exact visible placement"})
            return True
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

    def _resume_latest_game_at_position(self, obs):
        """Reuse the newest PGN on an exact match or shortest legal bridge.

        The visible image gives us piece placement, but not side to move,
        castling rights, en-passant state, or counters. Match placement against
        the verified/pending endpoint, or infer a bounded continuation from
        the verified prefix. Equal shortest histories stay as alternatives.
        """
        rows=self.store.query("SELECT id,state,headers FROM games WHERE status!='imported' ORDER BY started DESC,updated DESC LIMIT 1")
        if not rows:return False
        row=rows[0]
        try:
            state=json.loads(row["state"])
            saved=Reconstructor.restore(state,self.searcher())
            placements={saved.board.board_fen()}
            placements.update(branch.board().board_fen() for branch in saved.branches)
        except (KeyError,TypeError,ValueError,chess.IllegalMoveError):
            logging.warning("Could not compare latest saved game position for automatic resume",exc_info=True)
            return False
        before=len(saved.verified)
        previous_pending=[branch.moves for branch in saved.branches]
        bridged=False
        review=obs.placement() not in placements and obs.placement() in saved.history[:-1]
        if obs.placement() not in placements and not review:
            # A completed result, changed opponent or reset clocks is stronger
            # evidence of a new game than a coincidental short legal bridge.
            if (json.loads(row['headers']).get('Result','*')!='*' or state.get('terminal_message')
                    or self.pending_identity or self.clocks_recently_reset()):return False
            saved.confirmation_plies=int(self.settings.confirm_on_reply)
            if saved.bridge_gap(obs,self.searcher()) is None:return False
            bridged=True
        unused_session=self.session_id
        self.recover(row["id"],persist=False)
        if bridged:
            self.rec=saved
            self._mark_inferred_gap(before,previous_pending)
        if unused_session!=self.session_id:
            self.store.finish_session(unused_session)
        self.last_observation=obs
        self.last_message=("Review position • linked to latest saved PGN history" if review else
                           "Gap linked to latest PGN • shortest legal continuation • "+self.rec.status if bridged else
                           "Continued latest saved PGN • visible board matches its verified or pending position")
        self.persist()
        self.store.audit("latest PGN resumed by visible position",{
            "game_id":self.current_id,"placement":obs.placement(),
            "matched_pending":obs.placement()!=saved.board.board_fen(),"bridged":bridged,"review":review})
        logging.info("Resumed latest saved PGN %s from matching visible board placement",self.current_id)
        return True

    def _mark_inferred_gap(self, before, previous_pending):
        """Annotate only the common new path; ties stay as pending alternatives."""
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

    def _visible_roots(self, obs):
        threshold=max(.80,self.settings.min_confidence)
        if obs.confidence<threshold or obs.uncertain_squares(threshold):
            raise ValueError("Wait for a clear, stable board before starting from its FEN")
        if obs.placement()==chess.Board().board_fen():
            return chess.Board(),None,""
        moves=self._infer_short_opening(obs)
        if moves:
            sans=self._san_line(chess.Board(),moves)
            note=("The visible position has a unique shortest legal sequence from the standard starting position: "
                  + " ".join(sans) + ". This inferred line is included in the PGN; a different earlier history "
                  "that transposed to the same position cannot be ruled out.")
            return chess.Board(),None,note
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

    def _infer_short_opening(self, obs):
        """Return only a unique, exact, short legal path from the normal start.

        This recovers a missed opening frame such as 1.e4 e6 without guessing
        an arbitrary midgame history. Ambiguous, incomplete, or longer searches
        retain the ordinary visible-FEN behavior.
        """
        if self.settings.initial_fen or obs.uncertain_squares(max(.80,self.settings.min_confidence)):
            return []
        search=LegalSearcher(max_plies=min(4,max(2,self.settings.max_plies)),
            node_limit=min(30000,max(1000,self.settings.search_nodes)),
            time_limit_ms=min(150,max(50,self.settings.search_ms)),
            threshold=max(.80,self.settings.min_confidence),path_limit=2)
        result=search.search(chess.Board(),obs)
        if not result.exhaustive or len(result.paths)!=1 or not result.paths[0]:
            return []
        moves=[move.uci() for move in result.paths[0]]
        board=chess.Board()
        for uci in moves:
            board.push_uci(uci)
        return moves if obs.matches(board,max(.80,self.settings.min_confidence)) else []

    @staticmethod
    def _san_line(board, moves):
        result=[]
        for uci in moves:
            move=chess.Move.from_uci(uci)
            result.append(board.san(move));board.push(move)
        return result

    def _seed_opening(self, moves):
        if not self.rec or not moves:return
        for uci in moves:
            self.rec.board.push_uci(uci)
            self.rec.verified.append(uci)
            self.rec.history.append(self.rec.board.board_fen())
        self.rec.branches=[Branch(self.rec.board.fen(),())]
        self.rec.status="recording • opening reconstructed from visible position"
        self._persisted_fingerprint=None

    def _start_from_visible(self, obs, reason, since=None):
        opening_moves=self._infer_short_opening(obs)
        board,roots,note=self._visible_roots(obs)
        previous_id=self.current_id
        if self.rec:
            self.note += " A separate PGN segment was started from the visible board FEN; this game's saved moves remain unchanged."
            self.finish("preserved • continued from visible FEN")
        self.rec=None
        self.reset_candidate=None
        self._create(board,obs.timestamp,roots,note)
        self._seed_opening(opening_moves)
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
            # An aborted game can end before a single move. A clear legal
            # opening after its popup disappears starts a fresh recording.
            if (self.rec and self.terminal_message and not self.rec.verified
                    and self.rec.initial_fen==chess.STARTING_FEN
                    and obs.placement()!=self.rec.board.board_fen()
                    and not obs.uncertain_squares(max(.8,self.settings.min_confidence))):
                opening=LegalSearcher(1,self.settings.search_nodes,self.settings.search_ms,self.settings.min_confidence).search(chess.Board(),obs)
                if opening.exhaustive and len(opening.paths)==1:
                    self._create(chess.Board(),obs.timestamp)
            if self.rec and self.pending_identity and obs.confidence>=.8 and not obs.uncertain_squares(max(.8,self.settings.min_confidence)):
                names=self.pending_identity
                self._start_from_visible(obs,'visible player names changed')
                self.observed_names=names
                for color,name in names.items():self.headers[color.title()]=name
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
                    paths=[tuple(self.rec.verified[before:])+branch.moves for branch in self.rec.branches]
                    unseen=min((len(path)-max((len(old) for old in previous_pending
                               if path[:len(old)]==old),default=0) for path in paths),default=0)
                    if (not self.rec.incomplete and unseen>1
                            and all(branch.board().board_fen()==obs.placement() for branch in self.rec.branches)):
                        self._mark_inferred_gap(before,previous_pending)
                    if update.recovered:
                        self.store.audit("transient candidate replaced",{"game_id":self.current_id,
                            "placement":obs.placement(),"reason":"clear shorter legal continuation from the verified board; no verified moves rewritten"})
                    self.last_message = update.status
                    self._track_unresolved_position(obs,update.status)
                    outcome = self.rec.board.outcome(claim_draw=False)
                    if outcome and not self.result_override:
                        self.headers["Result"] = outcome.result()
                        self.ended = self.ended or obs.timestamp
                        self.last_message = "Complete • " + outcome.termination.name.replace("_"," ").lower()
            if self.rec:
                self._record_clocks(obs)
                self.persist()
            signature=(self.current_id,obs.placement(),self.last_message,obs.orientation)
            if signature!=self._last_evidence_signature:
                logging.info('Recorder state %s',json.dumps({'game_id':self.current_id,'status':self.last_message,'placement':obs.placement(),'plies':len(self.rec.verified) if self.rec else 0,'uncertain_squares':obs.uncertain_squares(max(.8,self.settings.min_confidence))}))
                self.store.save_observation(self.session_id, self.current_id, obs, self.last_message,
                    {"labels":obs.labels.tolist(), "confidence":[round(float(v),3) for v in obs.probabilities.max(axis=1)],
                     "orientation":obs.orientation})
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
            try:
                self._start_from_visible(obs,reason,self._unresolved_timestamp)
            except ValueError:
                self.clear_position_recovery()
                self.last_message=status+' • visible pieces do not form a valid FEN; existing game preserved'
                logging.warning(self.last_message)
        else:
            remaining=max(1,int(seconds-elapsed+.999))
            label="possible new game" if large_change else "unresolved position"
            self.last_message=f"{status} • {label} ({changed} changed squares); new FEN recording in {remaining}s if stable"

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
                    "fen":self.rec.board.fen(),"preview_fen":preview_board.fen(),
                    "preview_last_move":preview_last_move,"preview_moves":preview_moves,
                    "preview_candidates":preview_candidates,
                    "preview_confidence":(float(np.exp(ranked_branches[0][0])*100) if ranked_branches else None),
                    "preview_clock_support":(ranked_branches[0][1] if ranked_branches else 0),
                    "initial_fen":self.rec.initial_fen,"moves":san,
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
            self.rec.confirmation_plies=int(self.settings.confirm_on_reply)
            self.clear_position_recovery()
            self.rec.status = "recovered • ready to resume"
            self.last_message = self.rec.status
            if persist:self.persist()

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
