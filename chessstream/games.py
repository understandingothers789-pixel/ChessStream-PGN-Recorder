from __future__ import annotations

from datetime import datetime
from pathlib import Path
import io
import json
import threading
import time
import logging
import uuid
import chess
import chess.pgn
from .domain import Settings, Observation, utcnow, atomic_text
from .reconstruction import Reconstructor, LegalSearcher
from .storage import Store
from .game_extras import GameExtras
from .pgn_tools import merge_annotations


def export_pgn(initial_fen: str, moves: list[str], headers: dict, comment="", review_pgn="", clocks=None) -> str:
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
        if obs.placement() == chess.Board().board_fen():
            self._create(chess.Board(), obs.timestamp)
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

    def _visible_roots(self, obs):
        threshold=max(.80,self.settings.min_confidence)
        if obs.confidence<threshold or obs.uncertain_squares(threshold):
            raise ValueError("Wait for a clear, stable board before starting from its FEN")
        if obs.placement()==chess.Board().board_fen():
            return chess.Board(),None,""
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

    def _start_from_visible(self, obs, reason, since=None):
        board,roots,note=self._visible_roots(obs)
        previous_id=self.current_id
        if self.rec:
            self.note += " A separate PGN segment was started from the visible board FEN; this game's saved moves remain unchanged."
            self.finish("preserved • continued from visible FEN")
        self.rec=None
        self.reset_candidate=None
        self._create(board,obs.timestamp,roots,note)
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
                    update = self.rec.observe(obs)
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
        """Checkpoint an unchanged, clear unmatched board as a fresh FEN PGN."""
        seconds=float(self.settings.unresolved_fen_seconds)
        eligible=(seconds>0 and self.rec is not None
                  and status.startswith(("unmatched position","search limit","uncertain","review / rewind"))
                  and obs.placement()!=self.rec.board.board_fen()
                  and obs.confidence>=max(.80,self.settings.min_confidence)
                  and not obs.uncertain_squares(max(.80,self.settings.min_confidence)))
        if not eligible:
            self.clear_position_recovery()
            return
        now=self._clock()
        if self._unresolved_position!=obs.placement():
            self._unresolved_position=obs.placement()
            self._unresolved_since=now
            self._unresolved_timestamp=obs.timestamp
        elapsed=now-self._unresolved_since
        if elapsed>=seconds:
            try:
                self._start_from_visible(obs,"stable board remained unresolved for configured timeout",self._unresolved_timestamp)
            except ValueError:
                self.clear_position_recovery()
                self.last_message=status+' • visible pieces do not form a valid FEN; existing game preserved'
                logging.warning(self.last_message)
        else:
            remaining=max(1,int(seconds-elapsed+.999))
            self.last_message=f"{status} • will start a new FEN recording in {remaining}s if this clear position remains unresolved"

    def clear_position_recovery(self):
        self._unresolved_position=self._unresolved_since=self._unresolved_timestamp=None

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
        pgn = export_pgn(self.rec.initial_fen, self.rec.verified, self.headers, comment,self.review_pgn,self.move_clocks)
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
            for branch in self.rec.branches:
                if branch.moves or len(self.rec.branches)>1:
                    leaf = chess.Board(branch.root_fen)
                    line = []
                    for uci in branch.moves:
                        line.append(leaf.san(chess.Move.from_uci(uci)))
                        leaf.push_uci(uci)
                    alternatives.append(" ".join(line) or ("White to move" if leaf.turn else "Black to move"))
            return {"status":self.last_message,"game_id":self.current_id,"name":self.name,
                    "fen":self.rec.board.fen(),"initial_fen":self.rec.initial_fen,"moves":san,
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

    def recover(self, gid):
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
                pgn = export_pgn(state["initial_fen"],state["verified"],headers,state.get("note",""),state.get("review_pgn",""),state.get("move_clocks",{}))
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
