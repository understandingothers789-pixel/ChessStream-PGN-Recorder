"""Reversible game switches; never use a legal search to bridge a confirmed boundary."""
import io
import json

import chess
import chess.pgn

from .domain import Observation,utcnow
from .reconstruction import Branch,LegalSearcher


class GameBoundaries:
    def _resume_initial_identity(self,obs):
        names=self.lifecycle.names
        if len(names)<2 or self.lifecycle.reset_reads:return False
        matches=[]
        for row in self.store.query("SELECT * FROM games WHERE status NOT LIKE 'reconnected%' AND status NOT LIKE 'combined source%' ORDER BY started DESC LIMIT 2"):
            try:headers=json.loads(row['headers']);state=json.loads(row['state'])
            except (ValueError,TypeError):continue
            if any(''.join(headers.get(c.title(),'Unknown').casefold().split())!=''.join(n.casefold().split()) for c,n in names.items()):continue
            positions=[chess.Board(state['initial_fen'])]
            for uci in state['verified']:
                board=positions[-1].copy();board.push_uci(uci);positions.append(board)
            if not any(board.board_fen()==obs.placement() for board in positions):
                continue
            matches.append(row['id'])
        if len(matches)!=1:return False
        context=self.latest_context;self.recover(matches[0],persist=False);self.latest_context=context
        if context:self.lifecycle.metadata(context,context['timestamp'],self._clock(),self.headers)
        self.last_message='Saved game recognized by players and position';return True

    @staticmethod
    def _fen_roots(obs):
        if obs.placement()==chess.Board().board_fen():return chess.Board(),None
        roots=[chess.Board(f'{obs.placement()} {turn} - - 0 1').fen() for turn in ('w','b')
               if chess.Board(f'{obs.placement()} {turn} - - 0 1').is_valid()]
        if not roots:raise ValueError('Wait for a clear legal board before starting a game')
        return chess.Board(roots[0]),roots

    def lifecycle_gate(self,obs):
        with self.lock:
            self.last_observation=obs
            decision=self.lifecycle.evaluate(self,obs)
            if decision.action=='continue':return False
            self.cancel_background_recovery();self.reset_settling()
            if decision.action=='new':
                self.start_separate_game(obs,decision.reason);return True
            if decision.action=='return':
                context=self.latest_context;previous=self.current_id
                self.finish('preserved • switched to another saved game')
                self.recover(decision.game_id,persist=False)
                self.latest_context=context;self.lifecycle.bind(self,context)
                self.lifecycle.last_boundary={'previous':previous,'current':self.current_id,'created':False}
                self.lifecycle.set_phase('game in progress',decision.reason)
                self.last_message='Returned to saved game • players and board match';self.persist()
                self.store.audit('game identity returned',{'previous_game_id':previous,'game_id':self.current_id,'reason':decision.reason})
                return True
            if decision.action=='analysis':
                if not self._handle_saved_analysis(obs):
                    link=self._find_history_path(obs,max_plies=6,time_limit_ms=100,node_limit=12000)
                    if link:self._boundary_history_link=(self.current_id,tuple(self.rec.verified),obs.placement())
                    self.last_message='Analysis / replay selected • played PGN protected'
                self.persist();return True
            self.last_message=decision.reason+' • PGN protected'
            if self.rec:
                self.store.save_observation(self.session_id,self.current_id,obs,self.last_message,{'lifecycle':self.lifecycle.summary(self)})
                self.persist()
            return True

    def lifecycle_snapshot(self,obs):
        snapshot=self.snapshot()
        snapshot.update(preview_fen=obs.placement()+' w - - 0 1',preview_moves=[],preview_last_move=None)
        return snapshot

    def start_separate_game(self,obs,reason='started by user'):
        """Use observed FENs or a chain of witnessed single moves, never an invented opening."""
        previous=self.current_id;excluded=list(self.separated_from)
        incoming=self.latest_context or self.lifecycle.context
        names={color:value for color,value in self.lifecycle.names.items()
               if color in incoming.get('raw_names',incoming.get('names',{}))}
        frames=list(self.lifecycle.frames)
        if not frames or frames[-1][0].placement()!=obs.placement():frames.append((obs,incoming))
        starts=[index for index,(frame,_) in enumerate(frames) if frame.placement()==chess.Board().board_fen()]
        if starts:frames=frames[starts[-1]:]
        first=frames[0][0];board,roots=self._fen_roots(first);chosen=None
        for root in roots or [board.fen()]:
            trial=chess.Board(root);moves=[];clocks={}
            for frame,context in frames[1:]:
                if frame.placement()==trial.board_fen():continue
                result=LegalSearcher(1,2000,25,max(.8,self.settings.min_confidence)).search(trial,frame)
                if len(result.paths)!=1:break
                move=result.paths[0][0];mover='white' if trial.turn else 'black'
                trial.push(move);moves.append(move.uci())
                if context.get('timestamp')==frame.timestamp and mover in context.get('clocks',{}):clocks[str(len(moves))]=context['clocks'][mover]
            else:
                if trial.board_fen()==obs.placement():chosen=(root,moves,clocks);break
        if chosen is None:
            board,roots=self._fen_roots(obs);first=obs;chosen=(board.fen(),[],{})
        elif chosen[1]:board=chess.Board(chosen[0]);roots=None
        self.cancel_background_recovery()
        if self.rec:
            self.ended=self.ended or obs.timestamp
            self.finish('preserved • separate game confirmed')
        self.lifecycle.mode='auto'
        self._create(board,first.timestamp,roots,note=('Game boundary confirmed: '+reason+'. '+
            ('Recording starts from the visible FEN; earlier moves were not observed. Side to move is inferred from continuation; castling and en passant history were not assumed.' if board.fen()!=chess.STARTING_FEN else 'Starting position was observed.')))
        for uci in chosen[1]:
            self.rec.board.push_uci(uci);self.rec.verified.append(uci);self.rec.history.append(self.rec.board.board_fen())
        if chosen[1]:self.rec.branches=[Branch(self.rec.board.fen(),())]
        self.move_clocks=chosen[2];self.observed_names=names
        for color,name in names.items():self.headers[color.title()]=name
        self.latest_context=incoming
        self.separated_from=list(dict.fromkeys(([previous] if previous else [])+excluded))
        self.lifecycle.bind(self,incoming)
        self.lifecycle.last_boundary={'previous':previous,'current':self.current_id,'created':True}
        self.lifecycle.set_phase('new game detected',reason)
        self.rec.status='recording • separate game confirmed'
        self.last_message='New game started • previous PGN saved • '+reason
        self.persist()
        self.store.audit('game boundary confirmed',{'previous_game_id':previous,'game_id':self.current_id,
            'reason':reason,'names':names,'clocks':incoming.get('clocks',{}),'initial_fen':self.rec.initial_fen,
            'observed_plies':len(chosen[1]),'buffered_frames':len(frames)})

    def set_game_mode(self,mode):
        with self.lock:
            if mode=='new':
                if self.last_observation is None:raise ValueError('Capture a clear board first')
                self.start_separate_game(self.last_observation);return
            if mode=='undo':self.undo_game_switch();return
            if mode not in ('auto','continue','analysis'):raise ValueError('Unknown game mode')
            self.cancel_background_recovery();self.lifecycle.mode=mode
            self.lifecycle.candidate=None;self.lifecycle.frames.clear()
            if mode=='continue':
                self.lifecycle.pending_restart=False
                self.lifecycle.reset_reads=0;self.lifecycle.reset_confirmed=False;self.lifecycle.reset_since=None
                self.pending_identity=None;self.clock_reset_seen=False
            self.lifecycle.set_phase('analysis / replay' if mode=='analysis' else 'game in progress','Game mode selected: '+mode)
            self.last_message='Game mode: '+mode;self.persist()

    def undo_game_switch(self):
        with self.lock:
            boundary=self.lifecycle.last_boundary
            if not boundary or not boundary.get('previous'):raise ValueError('No previous game switch is available to undo')
            current=self.current_id;previous=boundary['previous']
            self.cancel_background_recovery();self.finish('preserved • game switch undone')
            backup=boundary.get('backup')
            if backup:
                rows=self.store.query('SELECT detail FROM audit WHERE id=?',(backup,))
                if not rows:raise ValueError('The original game backup is unavailable')
                row=json.loads(rows[0]['detail'])['record']
                self.store.save_game(row['id'],row['session_id'],row['name'],row['started'],row['status'],json.loads(row['headers']),json.loads(row['state']),row['pgn'],row['ended'])
            self.recover(previous,persist=False);self.lifecycle.mode='continue';self.lifecycle.last_boundary=None
            self.lifecycle.pending_restart=False
            self.lifecycle.set_phase('game in progress','Previous game restored by user')
            self.last_message='Game switch undone • original PGN restored; later recording kept separately';self.persist()
            self.store.audit('game switch undone',{'game_id':previous,'retained_game_id':current})

    def split_game_at(self,ply):
        with self.lock:
            if not self.rec or not 0<ply<len(self.rec.verified):raise ValueError('Select a move before the last move to split after it')
            self.persist();record=self.store.game(self.current_id)
            backup=self.store.audit('game before manual split',{'record':record})
            previous=self.current_id;old=self.rec.serialize();headers=dict(self.headers)
            original=chess.pgn.read_game(io.StringIO(record['pgn']));anchor=original
            for _ in range(ply):anchor=anchor.variations[0]
            game=chess.pgn.Game();game.setup(anchor.board())
            for key,value in headers.items():
                if key not in ('FEN','SetUp'):game.headers[key]=value
            pending=[(anchor,game)]
            while pending:
                source,target=pending.pop()
                for child in source.variations:
                    node=target.add_variation(child.move);node.comment=child.comment;node.nags=set(child.nags);node.starting_comment=child.starting_comment
                    pending.append((child,node))
            earlier_clocks={k:v for k,v in self.move_clocks.items() if int(k)<=ply}
            later_clocks={str(int(k)-ply):v for k,v in self.move_clocks.items() if int(k)>ply}
            later_inferred={str(int(k)-ply):v for k,v in self.inferred_moves.items() if int(k)>ply}
            self.cancel_background_recovery()
            self.rec=self.reconstructor(chess.Board(old['initial_fen']))
            for uci in old['verified'][:ply]:
                self.rec.board.push_uci(uci);self.rec.verified.append(uci);self.rec.history.append(self.rec.board.board_fen())
            self.rec.branches=[Branch(self.rec.board.fen(),())]
            self.headers['Result']='*';self.headers.pop('Termination',None);self.terminal_message=None
            self.move_clocks=earlier_clocks;self.inferred_moves={k:v for k,v in self.inferred_moves.items() if int(k)<=ply}
            self.review_pgn=record['pgn'];self.ended=utcnow();self.rec.status='split • first part preserved';self.persist()
            self._create(anchor.board(),utcnow(),note='Manually split from a saved PGN; known position and history rights retained.')
            for uci in old['verified'][ply:]:
                self.rec.board.push_uci(uci);self.rec.verified.append(uci);self.rec.history.append(self.rec.board.board_fen())
            self.rec.branches=[Branch(self.rec.board.fen(),())];self.headers=dict(game.headers)
            self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
            self.move_clocks=later_clocks;self.inferred_moves=later_inferred;self.separated_from=[previous]
            self.lifecycle.bind(self);self.lifecycle.last_boundary={'previous':previous,'current':self.current_id,'created':True,'backup':backup}
            self.last_message='PGN split • both parts saved; header names can be edited in the library';self.persist()
