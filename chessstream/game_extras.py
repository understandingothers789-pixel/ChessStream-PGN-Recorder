"""Result boundaries, clock evidence and review annotations for GameManager."""
from datetime import datetime
import io
import json
import logging
import chess
import chess.pgn
from .domain import utcnow,board_labels
from .pgn_tools import node_at
from .lifecycle import probable_ocr_variant


class GameExtras:
    def _reset_extras(self):
        self.review_pgn='';self.terminal_message=None;self.player_color=None
        self.review_tracker=None;self.review_anchor=None;self.rewind_state=None;self.premove_state=None
        self.analysis_cursor=None;self._analysis_pending=None;self._analysis_retry=None
        self._held_result_key=None
        self.separated_from=[]
        self.move_clocks={};self.inferred_moves={};self.clock_evidence={};self.latest_context=None;self._clock_samples=[]
        self.observed_names={};self.pending_identity=None;self.clock_reset_seen=False

    def _extra_state(self):
        return {key:getattr(self,key) for key in ['review_pgn','terminal_message','player_color','move_clocks','inferred_moves','clock_evidence','observed_names','rewind_state','premove_state','analysis_cursor','separated_from']}

    def _load_extras(self,state):
        self._reset_extras()
        for key in self._extra_state():
            if key in state:setattr(self,key,state[key])

    def result_player(self):
        configured=self.settings.result_player_color
        return self.player_color if configured=='initial-bottom' else (configured if configured in ['white','black'] else None)

    def observe_context(self,context,timestamp):
        with self.lock:
            context={**context,'timestamp':timestamp}
            self.lifecycle.metadata(context,timestamp,self._clock(),self.headers)
            context={**context,'names':{color:name for color,name in self.lifecycle.names.items()
                if color in self.lifecycle.raw_names and self.lifecycle.raw_names[color].casefold().replace(' ','')==name.casefold().replace(' ','')}}
            if self.lifecycle.changed_names(self,True) or self.lifecycle.reset_reads:self.cancel_background_recovery()
            previous=self.latest_context
            self.latest_context=context
            clocks=context.get('clocks',{})
            if all(color in clocks for color in ('white','black')):
                sample=(timestamp,float(clocks['white']),float(clocks['black']))
                if not self._clock_samples or self._clock_samples[-1][0]!=timestamp:
                    self._clock_samples.append(sample)
                    self._clock_samples=self._clock_samples[-12:]
            if previous and all(c in clocks and c in previous.get('clocks',{}) and clocks[c]-previous['clocks'][c]>20 for c in ['white','black']):
                self.clock_reset_seen=self._clock()
                logging.info('Both visible clocks reset: %s',clocks)
            names=context.get('names',{})
            if not self.rec:return
            changed=any(self.headers.get(color.title(),'Unknown')!='Unknown' and ''.join(self.headers[color.title()].casefold().split())!=''.join(name.casefold().split()) and not (not self.lifecycle.reset_confirmed and probable_ocr_variant(self.headers[color.title()],name)) for color,name in names.items())
            if changed:
                self.pending_identity=names
                logging.info('Stable visible player identity changed: %s -> %s',self.observed_names,names)
                self.persist()
                return
            if not self.lifecycle.changed_names(self):self.pending_identity=None
            for color,name in names.items():
                if color not in self.observed_names:
                    self.observed_names[color]=name
                    if self.headers.get(color.title(),'Unknown')=='Unknown':self.headers[color.title()]=name
                    self.store.audit('visible player name',{'game_id':self.current_id,'color':color,'name':name})
            self.persist()

    def clocks_recently_reset(self):
        return bool(self.clock_reset_seen and self._clock()-self.clock_reset_seen<6)

    def active_clock_turn(self):
        """Return the side whose clock is visibly running, when the evidence is clear."""
        if len(self._clock_samples)<2:return None
        try:
            from datetime import datetime
            recent=self._clock_samples[-1]
            prior=next((sample for sample in reversed(self._clock_samples[:-1])
                        if 0 < (datetime.fromisoformat(recent[0])-datetime.fromisoformat(sample[0])).total_seconds() <= 8),None)
            if prior is None:return None
            white_drop=prior[1]-recent[1];black_drop=prior[2]-recent[2]
            # Clock increments, OCR jitter and resets make small or simultaneous
            # changes ambiguous. In that case leave visual likelihood in charge.
            if white_drop>=0.25 and white_drop>black_drop+0.15:return True
            if black_drop>=0.25 and black_drop>white_drop+0.15:return False
        except (TypeError,ValueError):
            return None
        return None

    def _record_clocks(self,obs):
        if self.player_color is None and obs.orientation in ['white','black']:self.player_color=obs.orientation
        context=self.latest_context
        if context and context['timestamp']==obs.timestamp:
            for branch in self.rec.branches:
                board=branch.board()
                if (branch.moves or self.rec.verified) and obs.matches(board,self.settings.min_confidence):
                    mover='black' if board.turn else 'white'
                    seconds=context.get('clocks',{}).get(mover)
                    if seconds is not None and board.fen() not in self.clock_evidence:
                        self.clock_evidence[board.fen()]={'seconds':seconds,'timestamp':obs.timestamp,'color':mover}
                        self.store.audit('observed move clock',{'game_id':self.current_id,'fen':board.fen(),**self.clock_evidence[board.fen()]})
        self._sync_move_clocks()

    def _sync_move_clocks(self):
        board=chess.Board(self.rec.initial_fen)
        for ply,uci in enumerate(self.rec.verified,1):
            board.push_uci(uci)
            if str(ply) not in self.move_clocks and board.fen() in self.clock_evidence:
                self.move_clocks[str(ply)]=self.clock_evidence[board.fen()]['seconds']

    def _confirm_terminal_pending(self,obs):
        if not self.rec or len(self.rec.branches)!=1:return False
        branch=self.rec.branches[0]
        if len(branch.moves)!=1:return False
        if self.premove_state and branch.moves[-1]==self.premove_state['move']:return False
        final=branch.board();before=board_labels(self.rec.board);after=board_labels(final)
        changed=[s for s in chess.SQUARES if before[s]!=after[s]]
        # A popup may hide most of the board. The move's changed squares still
        # need independent positive support; a result alone cannot prove a path.
        if not changed or any(obs.probabilities[s,after[s]]<max(.8,self.settings.min_confidence) for s in changed):return False
        self.rec.incomplete=False
        self.rec.choose(0);self._sync_move_clocks()
        self.store.audit('final move confirmed by game-end evidence',{'game_id':self.current_id,'move':self.rec.verified[-1],'changed_squares':[chess.square_name(s) for s in changed]})
        return True

    def declare_end(self,message,obs=None):
        with self.lock:
            if not self.rec or self.terminal_message:return False
            observed=obs or self.last_observation
            if observed:
                decision=self.lifecycle.evaluate(self,observed)
                if decision.action in ('hold','new','return','analysis'):
                    self.cancel_background_recovery();self.reset_settling()
                    self.last_message='Result attribution pending • '+decision.reason
                    key=(self.current_id,message.result,message.reason,decision.reason)
                    if key!=self._held_result_key:
                        self.store.audit('result held during game transition',{'game_id':self.current_id,
                            'result':message.result,'text':message.text,'reason':decision.reason})
                        self._held_result_key=key
                    self.persist();return False
            confirmed=self._confirm_terminal_pending(observed) if observed and message.reason!='aborted' else False
            if self.premove_state:
                self.store.audit('premove discarded at game end',{'game_id':self.current_id,**self.premove_state})
                self.premove_state=None
            self.terminal_message={'result':message.result,'reason':message.reason,'text':message.text,'confidence':message.confidence,'color_basis':message.color_basis,'timestamp':utcnow()}
            if not self.result_override:self.headers['Result']=message.result
            if message.reason in ['aborted','abandoned','resignation','timeout','checkmate','stalemate']:self.headers['Termination']={'aborted':'abandoned','abandoned':'abandoned','timeout':'time forfeit'}.get(message.reason,message.reason)
            self.ended=utcnow();self.clear_position_recovery()
            self.rec.status='aborted' if message.reason=='aborted' else 'complete'
            self.last_message=f"Game ended • {self.headers['Result']} • {message.reason}; review stays with this game, ready for a new board"
            self.note+=' Game-end message detected: '+message.text+'. '+message.color_basis+'.'
            if confirmed:self.note+=' The final provisional move was confirmed by the result message and visible changed squares.'
            self.store.audit('game-end message',{**self.terminal_message,'game_id':self.current_id,'final_move_confirmed':confirmed})
            logging.info('Game-end evidence %s',json.dumps({**self.terminal_message,'game_id':self.current_id,'final_move_confirmed':confirmed}))
            self.persist();return True

    def _observe_review(self,obs):
        self.last_message=f"Game ended • {self.headers['Result']} • review only; waiting for a new game"
        if not self.settings.review_seconds:return
        elapsed=(datetime.fromisoformat(obs.timestamp)-datetime.fromisoformat(self.terminal_message['timestamp'])).total_seconds()
        if elapsed>self.settings.review_seconds:return
        if obs.placement()==self.rec.board.board_fen():return
        board=chess.Board(self.rec.initial_fen)
        known=[board.copy()]
        for uci in self.rec.verified:board.push_uci(uci);known.append(board.copy())
        matches=[i for i,b in enumerate(known) if obs.matches(b,max(.8,self.settings.min_confidence))]
        if matches:
            anchor=matches[-1]
            self.review_anchor=anchor;self.review_tracker=self.reconstructor(known[anchor])
            return
        if self.review_tracker is None:return
        self.review_tracker.searcher=self.searcher()
        self.review_tracker.observe(obs)
        if not self.review_tracker.verified:return
        trial=chess.Board(self.review_tracker.initial_fen);sans=[]
        for uci in self.review_tracker.verified:sans.append(trial.san(chess.Move.from_uci(uci)));trial.push_uci(uci)
        try:
            self.annotate(self.current_id,[0]*self.review_anchor,' '.join(sans),comment='Observed post-game analysis; not part of the played main line.',automatic=True)
            self.last_message=f"Game ended • {self.headers['Result']} • review variation recorded"
        except ValueError:pass  # Extensions without an actual main-line alternative are not recorded as play.

    def annotate(self,gid,path,san_text='',comment=None,delete=False,automatic=False,expected_fen=None):
        with self.lock:
            row=self.store.game(gid)
            if not row:raise ValueError('Game not found')
            game=chess.pgn.read_game(io.StringIO(row['pgn']))
            try:anchor=node_at(game,path)
            except (IndexError,TypeError):raise ValueError('The review changed. Select the position again.')
            if expected_fen and anchor.board().fen()!=expected_fen:raise ValueError('The review changed. Select the position again.')
            if delete:
                if anchor.is_mainline() or anchor.parent is None:raise ValueError('Only an alternative line can be deleted here.')
                anchor.parent.remove_variation(anchor)
            else:
                trial=anchor.board();moves=[]
                for token in san_text.split():
                    move=trial.parse_san(token);moves.append(move);trial.push(move)
                if moves and anchor.is_mainline() and anchor.is_end():raise ValueError('Choose a position before an existing move to add an alternative. The recorded main line cannot be extended by a review annotation.')
                node=anchor
                for move in moves:
                    next_node=next((n for n in node.variations if n.move==move),None)
                    if next_node is None:
                        if node.is_mainline() and node.is_end():raise ValueError('A review line cannot extend the recorded main line.')
                        next_node=node.add_variation(move)
                    node=next_node
                if automatic and node.is_mainline():return
                if comment is not None:node.comment=comment
            pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
            if pgn==row['pgn']:return
            state=json.loads(row['state']);state['review_pgn']=pgn
            if gid==self.current_id:
                self.review_pgn=pgn
                if not path and comment is not None and not san_text:self.note=comment
                self.persist()
            else:
                if not path and comment is not None and not san_text:state['note']=comment
                self.store.save_game(gid,row['session_id'],row['name'],row['started'],row['status'],json.loads(row['headers']),state,pgn,row['ended'])
            self.store.audit('review annotation',{'game_id':gid,'path':path,'san':san_text,'delete':delete,'automatic':automatic})
