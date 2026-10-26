"""Follow replay/analysis positions in the saved PGN tree, apart from live play."""
import io
import json
import time

import chess
import chess.pgn

from .domain import board_labels, utcnow
from .pgn_tools import node_at
from .reconstruction import LegalSearcher
from .reconstruction import Branch
from .commitment import assess_search


def tree_positions(game):
    stack=[(game,(),game.board())]
    while stack:
        node,path,board=stack.pop()
        yield node,path,board
        for index,child in reversed(list(enumerate(node.variations))):
            following=board.copy();following.push(child.move)
            stack.append((child,path+(index,),following))


class AnalysisTracking:
    def _promote_inferred_correction(self,game,node,obs):
        """Prefer supported continuations over short, abandoned inferred tails."""
        if (self.lifecycle.mode!='auto' or self.terminal_message or self.headers.get('Result','*')!='*'
                or not self.lifecycle.same_visible_players(self)
                or not obs.matches(node.board(),max(.8,self.settings.min_confidence))):return False
        chain=[];cursor=node
        while cursor.parent is not None:
            chain.append(cursor);cursor=cursor.parent
        chain.reverse();moves=[child.move.uci() for child in chain]
        common=0
        for old,new in zip(self.rec.verified,moves):
            if old!=new:break
            common+=1
        tail=len(self.rec.verified)-common
        if not 1<=tail<=2 or not all(str(ply) in self.inferred_moves for ply in range(common+1,len(self.rec.verified)+1)):
            return False
        mate=node.board().is_checkmate()
        if not mate:
            # Length alone cannot distinguish live play from analysis. Require
            # a single abandoned guess, an opponent reply and another move,
            # plus clocks for BOTH players below the last accepted values.
            baseline={}
            board=chess.Board(self.rec.initial_fen)
            for ply,uci in enumerate(self.rec.verified,1):
                mover='white' if board.turn else 'black'
                if str(ply) in self.move_clocks:baseline[mover]=self.move_clocks[str(ply)]
                board.push_uci(uci)
            clocks=self.lifecycle.clocks
            if (tail!=1 or len(moves)-common<3 or self.clocks_recently_reset()
                    or not all(color in baseline and color in clocks and clocks[color]<baseline[color]
                               for color in ('white','black'))):return False
        reason=('observed legal checkmate' if mate else 'longer observed continuation with both clocks advancing')
        self.store.audit('checkmate corrected inferred mainline' if mate else 'hover corrected inferred mainline' ,{'game_id':self.current_id,
            'previous_pgn':self.store.game(self.current_id)['pgn'],'after_ply':common,
            'replaced':self.rec.verified[common:],'replacement':moves[common:],
            'reason':'same visible players; '+reason+' contradicts short inferred suffix'})
        displaced=game
        for _ in range(common+1):displaced=displaced.variations[0]
        displaced.comment=(displaced.comment+' Previous inferred mainline retained as an alternative after supported continuation correction.').strip()
        for child in chain:
            child.parent.promote_to_main(child)
            child.comment=child.comment.replace('Observed analysis variation; excluded from the played main line.',
                'Observed continuation; promoted after later play corrected an inferred suffix.').replace(
                'Observed analysis variation; inferred legal order across missing frames.',
                'Observed continuation; inferred legal order across missing frames.')
        probe=self.reconstructor(game.board())
        for uci in moves:
            probe.board.push_uci(uci);probe.verified.append(uci);probe.history.append(probe.board.board_fen())
        probe.branches=[Branch(probe.board.fen(),())]
        self.rec=probe
        self.move_clocks={key:value for key,value in self.move_clocks.items() if int(key)<=common}
        self.inferred_moves={key:value for key,value in self.inferred_moves.items() if int(key)<=common}
        self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
        self.analysis_cursor=None;self.rewind_state=None;self._analysis_pending=None
        self._timed_base=None;self._timed_end=0;self.cancel_background_recovery();self.reset_settling()
        for ply,uci in enumerate(moves[common:],common+1):
            self.inferred_moves[str(ply)]={'uci':uci,'comment':'Inferred: selected observed continuation after correcting an abandoned inferred move.'}
        if mate:self.headers['Result']=probe.board.result();self.ended=obs.timestamp
        self.rec.status='complete' if mate else 'recording'
        self.last_message=('Checkmate' if mate else 'Live continuation')+' • inferred mainline corrected; previous line kept as variation'
        self.lifecycle.set_phase('game completed' if mate else 'game in progress',self.last_message)
        return True

    def _analysis_game(self):
        row=self.store.game(self.current_id)
        return chess.pgn.read_game(io.StringIO(row['pgn'])) if row else None

    def _analysis_boundary(self,headers=None,state=None):
        """Names support a replay; changed opponents, resets and aborts oppose it."""
        if self.lifecycle.mode=='analysis':return False
        if self.pending_identity or self.clocks_recently_reset():return True
        if self.terminal_message and self.terminal_message.get('reason')=='aborted':return True
        if state and (state.get('terminal_message') or {}).get('reason')=='aborted':return True
        expected=headers or self.headers
        visible=(self.latest_context or {}).get('names',{})
        for color,name in visible.items():
            old=expected.get(color.title(),'Unknown')
            if old!='Unknown' and self._name_key(name)!=self._name_key(old):return True
        return False

    @staticmethod
    def _name_key(name):return ''.join(name.casefold().split())

    def _same_analysis_players(self,headers):
        for color in ('White','Black'):
            current=self.headers.get(color,'Unknown');previous=headers.get(color,'Unknown')
            if current=='Unknown' or previous=='Unknown' or self._name_key(current)!=self._name_key(previous):return False
        return True

    def _analysis_link(self,game,obs,cursor=None,search=True):
        """Search close tree positions under one shared time/node budget."""
        positions=list(tree_positions(game));placement=obs.placement()
        exact=[entry for entry in positions if entry[2].board_fen()==placement]
        if exact:
            exact.sort(key=lambda entry:(entry[1]!=tuple(cursor or ()), -len(entry[1])))
            return exact[0][1],()
        if not search:return None
        labels=obs.labels
        positions.sort(key=lambda entry:(entry[1]!=tuple(cursor) if cursor is not None else True,
            sum(board_labels(entry[2])!=labels),-len(entry[1])))
        started=time.monotonic();remaining=18000;links=[]
        # Once a replay cursor exists, an unseen route from another tree node
        # cannot establish what happened after it. Exact historical positions
        # were handled above; only extend this observed cursor automatically.
        if cursor is not None:
            positions=[entry for entry in positions if entry[1]==tuple(cursor)]
        for _,path,board in positions[:32]:
            ms=140-(time.monotonic()-started)*1000
            if ms<=0 or remaining<500:return None
            result=LegalSearcher(6,min(5000,remaining),ms,max(.8,self.settings.min_confidence)).search(
                board,obs)
            remaining-=result.nodes
            decision=assess_search(board,result,obs,max(.8,self.settings.min_confidence))
            if decision.kind in ('incomplete','ambiguous','speculative','invalid'):return None
            if decision.automatic:links.append((path,tuple(move.uci() for move in decision.path)))
        # Exhausting only a subset of anchors cannot certify a unique link.
        if len(positions)>32:return None
        if not links:return None
        shortest=min(len(moves) for _,moves in links)
        links=[link for link in links if len(link[1])==shortest]
        return links[0] if len(links)==1 else None

    @staticmethod
    def _append_analysis(game,path,moves):
        node=node_at(game,path);path=list(path)
        for uci in moves:
            move=chess.Move.from_uci(uci)
            if move not in node.board().legal_moves:raise ValueError('Illegal analysis continuation')
            child=next((child for child in node.variations if child.move==move),None)
            if child is None:
                # An alternative must branch before the played endpoint.
                if node.is_mainline() and node.is_end():raise ValueError('Analysis cannot extend played main line')
                child=node.add_variation(move)
            path.append(node.variations.index(child));node=child
        return node,tuple(path)

    def _activate_analysis_cursor(self,game,path):
        node=node_at(game,path)
        self.analysis_cursor={'path':list(path),'fen':node.board().fen()}
        anchor=0
        for index in path:
            if index:break
            anchor+=1
        self.rewind_state={'anchor_ply':len(self.rec.verified),'cursor':min(anchor,len(self.rec.verified))}
        self.cancel_background_recovery()
        self.last_message='Review position • replay linked to main PGN' if node.is_mainline() else 'Review position • analysis variation saved in main PGN'

    def _copy_fragment_tree(self,game,source,path=()):
        for child in source.variations:
            try:target,following=self._append_analysis(game,path,(child.move.uci(),))
            except ValueError:continue
            if not target.is_mainline():
                if child.comment and child.comment not in target.comment:
                    target.comment=(target.comment+' '+child.comment).strip()
                target.nags.update(child.nags)
                if child.starting_comment:target.starting_comment=child.starting_comment
            self._copy_fragment_tree(game,child,following)

    def _try_replay_recording(self,obs):
        """Fold a recognizable short replay/checkpoint into a recent longer game."""
        if ('Temporary visible board FEN segment' not in self.note and not self.rewind_state
                and not self.analysis_cursor and self.lifecycle.phase!='analysis / replay'):
            return False
        if (not self.rec or self._analysis_boundary() or len(self.rec.verified)>12
                or not any(text in self.note for text in ('Temporary visible board FEN segment','visible midgame FEN','visible board FEN','Recording began midgame'))):
            return False
        signature=(self.current_id,tuple(self.rec.verified),obs.placement(),tuple(sorted(self.headers.items())))
        if self._analysis_retry and self._analysis_retry[0]==signature and self._clock()-self._analysis_retry[1]<2:return False
        self._analysis_retry=(signature,self._clock())
        rows=self.store.query("SELECT * FROM games WHERE id!=? AND status!='imported' AND status NOT LIKE 'reconnected%' AND status NOT LIKE 'combined source%' ORDER BY started DESC,updated DESC LIMIT 2",(self.current_id,))
        rows.sort(key=lambda row:-row['plies'])
        for row in rows:
            try:
                headers=json.loads(row['headers']);state=json.loads(row['state'])
                previous_length=len(state['verified'])
            except (TypeError,ValueError,KeyError):continue
            if (row['id'] in self.separated_from or not self._same_analysis_players(headers)
                    or self._analysis_boundary(headers,state) or previous_length<=len(self.rec.verified)
                    or ((state.get('terminal_message') or headers.get('Result','*')!='*') and not self.settings.review_seconds)):
                continue
            game=chess.pgn.read_game(io.StringIO(row['pgn']))
            if game is None or game.errors:continue
            # Keep the played line and comments untouched. A short replay can
            # transpose a guessed opening and therefore need its own variation.
            path=None
            if self.rec.initial_fen==game.board().fen() and self.rec.verified:
                common=0
                for left,right in zip(self.rec.verified,state['verified']):
                    if left!=right:break
                    common+=1
                if common>=1:
                    try:
                        replay,path=self._append_analysis(game,(),self.rec.verified)
                        source=self._analysis_game()
                        if source and not source.errors:self._copy_fragment_tree(game,source)
                        if not replay.is_mainline():
                            replay.comment=(replay.comment+' Replay fragment attached as analysis; earlier move order may be inferred.').strip()
                    except ValueError:path=None
            link=self._analysis_link(game,obs,cursor=path)
            if link is None:continue
            link_path,moves=link
            # A differing FEN checkpoint must be legally connected, never
            # attached merely because its player names match.
            try:
                if moves:
                    attached,link_path=self._append_analysis(game,link_path,moves)
                    if not attached.is_mainline():
                        attached.comment=(attached.comment+' Inferred legal connection to a visible analysis checkpoint.').strip()
            except ValueError:continue
            old=self.current_id;context=self.latest_context
            self.cancel_background_recovery();self.recover(row['id'],persist=False)
            self.latest_context=context;self.last_observation=obs
            self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
            self._activate_analysis_cursor(game,link_path)
            self.persist()
            with self.store.transaction() as db:
                db.execute('UPDATE games SET status=?,ended=?,updated=? WHERE id=?',
                    ('reconnected analysis • see '+self.current_id,utcnow(),utcnow(),old))
                db.execute('UPDATE observations SET game_id=? WHERE game_id=?',(self.current_id,old))
                db.execute('UPDATE screenshots SET game_id=? WHERE game_id=?',(self.current_id,old))
            self.store.audit('replay fragment attached as analysis',{'game_id':self.current_id,'fragment_id':old,
                'path':list(link_path),'inferred_gap':list(moves),'original_fragment':self.store.game(old)['pgn']})
            return True
        return False

    def _handle_saved_analysis(self,obs):
        threshold=max(.8,self.settings.min_confidence)
        if obs.confidence<threshold or obs.uncertain_squares(threshold):return False
        if (self.terminal_message or self.headers.get('Result','*')!='*') and not self.settings.review_seconds:return False
        if self._analysis_boundary():
            self.analysis_cursor=None;self._analysis_pending=None
            return False
        if (obs.placement()==chess.Board().board_fen()
                and (self.terminal_message or self.headers.get('Result','*')!='*')
                and any(self.headers.get(color,'Unknown')=='Unknown' for color in ('White','Black'))):
            return False
        # Live capture is not analysis. A future screen position may happen
        # to match a legal variation from six moves ago, but this is no
        # evidence that the streamer is reviewing rather than continuing.
        # The actual backward-seek detector runs later in process() and sets
        # rewind_state based on a witnessed earlier position. Once witnessed,
        # existing analysis tracking works as before. Explicit Analysis mode
        # always remains available.
        if self._try_replay_recording(obs):return True
        if self.lifecycle.mode!='analysis' and not self.rewind_state:
            self.analysis_cursor=None
            self._analysis_pending=None
            return False
        if obs.matches(self.rec.board,threshold):
            self.analysis_cursor=None;self._analysis_pending=None
            return False
        game=self._analysis_game()
        if game is None or game.errors:return False
        cursor=tuple(self.analysis_cursor['path']) if self.analysis_cursor else None
        # Actual forward play has priority over discovering a historical link.
        if cursor is None and not self.rewind_state:
            direct=LegalSearcher(1,2000,25,threshold).search(self.rec.board,obs,first_shortest=True)
            if direct.paths:return False
        cached_link=self._boundary_history_link==(self.current_id,tuple(self.rec.verified),obs.placement())
        link=self._analysis_link(game,obs,cursor=cursor,search=cursor is not None or bool(self.rewind_state) or cached_link)
        if link is None:return False
        path,moves=link
        if not moves:
            if self._promote_inferred_correction(game,node_at(game,path),obs):return True
            if cursor is None and not any(path) and not self.terminal_message:
                before=len(self.rec.verified)
                self._handle_rewind(obs)
                if len(self.rec.verified)!=before:
                    self.persist();game=self._analysis_game()
                    found=self._analysis_link(game,obs,search=False)
                    if found is None:return False
                    path,_=found
            self._analysis_pending=None
            self._activate_analysis_cursor(game,path)
            return True
        # A replay reached from an actual recorded fragment or rewind keeps
        # its analysis branch functionality. Ordinary live play is filtered
        # before this point unless it has an explicit analysis context.
        signature=(self.current_id,obs.placement(),path,moves)
        if not self._analysis_pending or self._analysis_pending[0]!=signature:
            self._analysis_pending=(signature,self._clock())
            self.last_message='Review position • checking analysis continuation'
            return True
        if self._clock()-self._analysis_pending[1]<.5:return True
        try:node,new_path=self._append_analysis(game,path,moves)
        except ValueError:return False
        if not node.is_mainline():
            note='Observed analysis variation; inferred legal order across missing frames.' if len(moves)>1 else 'Observed analysis variation; excluded from the played main line.'
            if note not in node.comment:node.comment=(node.comment+' '+note).strip()
            self.review_pgn=game.accept(chess.pgn.StringExporter(headers=True,variations=True,comments=True))
            self.store.audit('analysis continuation recorded',{'game_id':self.current_id,'path':list(path),'moves':list(moves)})
        if self._promote_inferred_correction(game,node,obs):return True
        self._activate_analysis_cursor(game,new_path);self._analysis_pending=None
        return True
