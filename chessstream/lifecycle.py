"""One game-identity gate shared by capture, reconstruction and gap recovery."""
from collections import deque
from dataclasses import dataclass
from difflib import SequenceMatcher
import json
import logging
import time

import chess

from .reconstruction import LegalSearcher


def name_key(value):return ''.join(value.casefold().split())


def probable_ocr_variant(left,right):
    """One interior OCR character error is not evidence of a new opponent.

    Do not equate different trailing ID suffixes (OpponentA/OpponentB).
    An actual game reset is evaluated separately using board and clocks.
    """
    a,b=name_key(left),name_key(right)
    if a==b:return True
    if min(len(a),len(b))<8 or abs(len(a)-len(b))>1:return False
    changes=[(tag,i,j,x,y) for tag,i,j,x,y in SequenceMatcher(None,a,b).get_opcodes() if tag!='equal']
    if len(changes)!=1:return False
    tag,i,j,x,y=changes[0]
    if i==0 or x==0 or j==len(a) or y==len(b):return False
    if tag in ('insert','delete'):return max(j-i,y-x)==1
    if tag=='replace' and j-i==y-x==1:
        pair={a[i],b[x]}
        return any(pair<=group for group in ({'i','l','1'},{'o','0'},{'b','8'},{'s','5'},{'g','q'}))
    return False


@dataclass(frozen=True)
class Decision:
    action: str = 'continue'
    reason: str = ''
    game_id: str | None = None


class GameLifecycle:
    def __init__(self):
        self.phase='waiting for a game';self.reason='Waiting for a visible board';self.mode='auto'
        self.name_reads={};self.names={};self.raw_names={};self.context={}
        self.clocks={};self.clock_baseline=None;self.reset_reads=0;self.reset_since=None
        self.reset_confirmed=False;self.clock_running=False;self.metadata_time=None
        self.candidate=None;self.since=None;self.frames=deque(maxlen=24)
        self.last_boundary=None;self.generation=0;self._links={};self._logged=None
        self.reset_board_seen=False;self.ignored_names={}
        self.clock_seek=False
        self.pending_restart=False;self._metadata_pending=False

    def metadata(self,context,timestamp,now,headers):
        if timestamp==self.metadata_time:return
        self.metadata_time=timestamp;self.context={**context,'timestamp':timestamp}
        self.raw_names=dict(context.get('raw_names',context.get('names',{})))
        self.raw_names={color:name for color,name in self.raw_names.items() if context.get('name_confidence',{}).get(color,1.)>=.9}
        self._metadata_pending=any(headers.get(color.title(),'Unknown')!='Unknown' and name_key(value)!=name_key(headers[color.title()]) and not probable_ocr_variant(value,headers[color.title()]) for color,value in self.raw_names.items())
        confirmed=context.get('names',{}) if context.get('names_stable') else {}
        for color in ('white','black'):
            value=self.raw_names.get(color)
            if not value:
                self.name_reads.pop(color,None);continue
            key=name_key(value);old,count=self.name_reads.get(color,('',0))
            count=count+1 if old==key else 1;self.name_reads[color]=(key,count)
            if color in confirmed or count>=3:
                self.names[color]=confirmed.get(color,value);self.pending_restart=False
        # Compare with the last readable pair, including across a missing overlay.
        clocks=context.get('clocks',{})
        if all(color in clocks for color in ('white','black')):
            pair={color:float(clocks[color]) for color in ('white','black')}
            if self.clocks:
                drops=[self.clocks[c]-pair[c] for c in pair]
                if any(.2<=drop<=15 for drop in drops) and not all(drop<0 for drop in drops):self.clock_running=True
            if self.clock_baseline is None:self.clock_baseline=pair
            rises=[pair[c]-self.clock_baseline[c] for c in pair]
            if self.reset_reads and any(pair[c]<=self.clock_baseline[c]+20 for c in pair):
                self.reset_reads=0;self.reset_since=None;self.reset_confirmed=False;self.clock_seek=False
            if all(rise>max(20,self.clock_baseline[c]*.12) for rise,c in zip(rises,pair)):
                if self.reset_since is None:self.reset_since=now;self.clock_running=False
                self.reset_reads+=1;self.reset_confirmed=self.reset_reads>=2
            elif not self.reset_confirmed:
                self.clock_baseline=pair;self.reset_reads=0;self.reset_since=None
            self.clocks=pair
            if self.reset_confirmed and self.clock_running and self.reset_board_seen:self.pending_restart=False
        # Evidence does not silently expire after a six-second OCR delay.

    def changed_names(self,manager,raw=False):
        names=self.raw_names if raw else self.names
        return {color:value for color,value in names.items()
                if manager.headers.get(color.title(),'Unknown')!='Unknown'
                and name_key(value)!=name_key(manager.headers[color.title()])
                and not (not self.reset_confirmed and probable_ocr_variant(value,manager.headers[color.title()]))
                and name_key(value)!=self.ignored_names.get(color)}

    def same_visible_players(self,manager):
        """Require current OCR evidence for *both* unchanged player identities.

        The last known player names alone do not prove continuity: they may
        survive a hidden overlay when the streamer starts a different game.
        """
        if len(self.raw_names)<2:return False
        return all(
            name_key(manager.headers.get(color.title(),'Unknown'))!='unknown'
            and name_key(self.raw_names.get(color,''))==name_key(manager.headers[color.title()])
            for color in ('white','black')
        )

    def set_phase(self,phase,reason):
        self.phase=phase;self.reason=reason
        key=(phase,reason)
        if key!=self._logged:
            logging.info('Game lifecycle: %s • %s',phase,reason);self._logged=key

    def hold(self,manager,obs,reason,key,delay=None):
        now=manager._clock()
        if self.candidate!=key:self.candidate=key;self.since=now
        if not self.frames or (self.frames[-1][0].timestamp,self.frames[-1][0].placement())!=(obs.timestamp,obs.placement()):
            self.frames.append((obs,self.context.copy()))
        self.set_phase('uncertain transition',reason)
        if delay is not None and now-self.since>=delay:return Decision('new',reason)
        return Decision('hold',reason)

    def _return_game(self,manager,obs):
        if self.reset_reads:return None
        visible={c:n for c,n in self.names.items() if c in self.raw_names and name_key(self.raw_names[c])==name_key(n)}
        # A short replay can be saved as its own PGN before the replay linker
        # has had enough observations to attach it to the longer recording.
        # Do not switch away from the active game just because the current
        # board equals that fragment's endpoint when its full line is already
        # present contiguously in the active main line.
        active_line=self._active_position_line(manager)
        matches=[]
        rows=manager.store.query("SELECT id,headers,state FROM games WHERE id!=? AND status NOT LIKE 'reconnected%' AND status NOT LIKE 'combined source%' ORDER BY started DESC LIMIT 8",(manager.current_id,))
        for row in rows:
            try:
                headers=json.loads(row['headers']);state=json.loads(row['state'])
                if len(state['verified'])<4 and state['initial_fen']==chess.STARTING_FEN:continue
                if not visible or any(name_key(headers.get(c.title(),'Unknown'))!=name_key(n) for c,n in visible.items()):continue
                board=chess.Board(state['initial_fen'])
                candidate_line=[board.board_fen()]
                for move in state['verified']:board.push_uci(move)
                candidate_line.extend(self._positions_after(board, state['verified'], state['initial_fen']))
                if self._is_replay_subline(candidate_line,active_line):continue
                # Specific established endpoints, not generic opening matches.
                if obs.placement()==board.board_fen():matches.append(row['id'])
            except (ValueError,TypeError,KeyError):continue
        return matches[0] if len(matches)==1 else None

    @staticmethod
    def _positions_after(board, moves, initial_fen):
        """Return each successive placement for a saved main-line move list."""
        current=chess.Board(initial_fen);positions=[]
        for uci in moves:
            current.push_uci(uci);positions.append(current.board_fen())
        return positions

    @staticmethod
    def _active_position_line(manager):
        if not manager.rec:return []
        board=chess.Board(manager.rec.initial_fen);positions=[board.board_fen()]
        try:
            for uci in manager.rec.verified:
                board.push_uci(uci);positions.append(board.board_fen())
        except (ValueError,chess.IllegalMoveError):
            return []
        return positions

    @staticmethod
    def _is_replay_subline(candidate, active):
        """Whether candidate's whole observed line is a contiguous active line."""
        if len(candidate)<5 or len(candidate)>len(active):return False
        width=len(candidate)
        return any(active[index:index+width]==candidate
                   for index in range(len(active)-width+1))

    def _linked(self,manager,obs):
        key=(manager.current_id,tuple(manager.rec.verified),obs.placement())
        cache_key=(key,tuple((manager.analysis_cursor or {}).get('path',())),hash(manager.review_pgn))
        if cache_key not in self._links:
            linked=False;started=time.monotonic();nodes=8000
            origins={board.fen():board for board in [manager.rec.board]+[branch.board() for branch in manager.rec.branches]}
            for origin in list(origins.values())[:8]:
                remaining=65-(time.monotonic()-started)*1000
                if remaining<=0 or nodes<=0:break
                result=LegalSearcher(min(4,manager.settings.max_plies),nodes,remaining,max(.8,manager.settings.min_confidence)).search(origin,obs,first_shortest=True)
                nodes-=result.nodes
                if result.paths:linked=True;break
            if not linked and manager.analysis_cursor:
                game=manager._analysis_game()
                linked=bool(game and manager._analysis_link(game,obs,cursor=tuple(manager.analysis_cursor['path'])))
            if not linked and manager.settings.infer_unseen_opening:
                from .opening import infer_visible_opening
                linked=bool(infer_visible_opening(obs,start_board=manager.rec.board,max_plies=14,time_limit_ms=150,node_limit=16000))
            if not linked:
                path=manager._find_history_path(obs,max_plies=6,min_ply=2 if len(manager.rec.verified)>6 else 0,time_limit_ms=100,node_limit=12000)
                linked=path is not None
                if linked and not any(str(ply+1) in manager.inferred_moves for ply in range(max(0,len(manager.rec.verified)-8),len(manager.rec.verified))):manager._boundary_history_link=key
            if len(self._links)>16:self._links.clear()
            self._links[cache_key]=linked
        return self._links[cache_key]

    def evaluate(self,manager,obs):
        if not manager.rec:return Decision()
        if obs.confidence<.8 or obs.uncertain_squares(max(.8,manager.settings.min_confidence)):
            self.set_phase('temporarily uncertain','Board is obscured or recognition is uncertain')
            return Decision('hold',self.reason) if self.changed_names(manager,True) or self.reset_reads else Decision()
        placement=obs.placement();start=placement==chess.Board().board_fen()
        current=placement==manager.rec.board.board_fen()
        established=bool(len(manager.rec.verified)>=2 or manager.rec.initial_fen!=chess.STARTING_FEN
                         or manager.terminal_message or manager.headers.get('Result','*')!='*')
        if self.mode=='analysis':
            self.set_phase('analysis / replay','Analysis selected by user');return Decision('analysis',self.reason)
        if self.pending_restart and self.mode!='continue':
            return self.hold(manager,obs,'Checking game identity after restart; waiting for confirmed player context',('restart-identity',))
        raw_change=self.changed_names(manager,True);changed=self.changed_names(manager)
        if self.mode=='continue':
            raw_change=changed={}
        if changed:
            prior=self._return_game(manager,obs)
            if prior:return Decision('return','Visible players and established board match a saved game',prior)
            near=all(SequenceMatcher(None,name_key(manager.headers[c.title()]),name_key(n)).ratio()>.88 for c,n in changed.items())
            reason='opponent changed'+(' and both clocks reset' if self.reset_confirmed else '')
            if near and current and not self.reset_confirmed and min(self.name_reads.get(c,('',0))[1] for c in changed)<5:
                return self.hold(manager,obs,'Possible player-name OCR mismatch; current board unchanged',('near-name',tuple(sorted(changed.items()))))
            return self.hold(manager,obs,'Possible new game: '+reason,('names',tuple(sorted(changed.items()))),.5)
        if raw_change:
            return self.hold(manager,obs,'Possible new game: checking a player-name change',('raw-names',tuple(sorted(raw_change.items()))))
        known=placement in manager.rec.history
        if self.reset_reads and established:
            # A static jump to historical clocks can be a video seek. A fresh
            # running clock or changed identity distinguishes the common rematch.
            reason='Possible new game: both clocks reset'
            if known and not start and not current and not self.reset_board_seen and not manager.terminal_message:
                self.clock_seek=True
            if self.clock_seek and not self.reset_board_seen and (known or self._linked(manager,obs)):
                if start:return self.hold(manager,obs,'Opening review after a video seek; awaiting game identity',('seek-reset',))
                self.set_phase('analysis / replay','Historical position and clock discontinuity indicate a video seek')
                return Decision()
            live_continuation=current
            if not current and not self.reset_board_seen and not manager.terminal_message:
                live_continuation=bool(LegalSearcher(4,4000,45,max(.8,manager.settings.min_confidence)).search(
                    manager.rec.board,obs,first_shortest=True).paths)
            if self.reset_confirmed and live_continuation and not self.reset_board_seen and not manager.terminal_message:
                self.reset_reads=0;self.reset_confirmed=False;self.reset_since=None
                self.clock_baseline=dict(self.clocks);manager.clock_reset_seen=False
                self.set_phase('game in progress','Clock increase with continuous play; treating it as increment or correction')
                return Decision()
            if self.reset_confirmed and (self.clock_running or (manager.terminal_message and not known)):
                return self.hold(manager,obs,reason+(' and the board reset' if start or self.reset_board_seen else ''),('clock-reset',),.5)
            if start or self.reset_board_seen or not current:
                self.reset_board_seen|=start
                return self.hold(manager,obs,reason+'; waiting for live play or confirmation',('clock-reset',))
        # Merely showing the initial position after a result is ambiguous.
        if start and established:
            if not manager.terminal_message and manager.headers.get('Result','*')=='*':
                direct=LegalSearcher(1,2000,25,max(.8,manager.settings.min_confidence)).search(manager.rec.board,obs)
                if direct.paths:return Decision()
            self.reset_board_seen=True
            if manager.terminal_message and manager.terminal_message.get('reason')=='aborted':
                decision=self.hold(manager,obs,'Aborted game; waiting for a fresh opening',('aborted-reset',))
                self.set_phase('between games',decision.reason);return decision
            return self.hold(manager,obs,'Starting position revisited; awaiting game identity',('reset',))
        # When the displayed players still match this *ongoing* game, a
        # historical endpoint is often a video seek, not a request to switch
        # between short PGN fragments with identical headers.
        previous_game_allowed = (self.reset_board_seen or self.reset_confirmed
                                 or manager.terminal_message is not None
                                 or not self.same_visible_players(manager))
        prior=(self._return_game(manager,obs)
               if not current and self.names and previous_game_allowed else None)
        if prior:return Decision('return','Visible players and established board match a saved game',prior)
        if current or known or any(placement==b.board().board_fen() for b in manager.rec.branches):
            self.candidate=None;self.since=None;self.frames.clear()
            self.set_phase('analysis / replay' if known and not current else 'game completed' if manager.terminal_message or manager.headers.get('Result','*')!='*' else 'game in progress','Recognized saved position' if known else 'Tracking current game')
            return Decision()
        if not established:return Decision()
        if not manager.terminal_message and not manager.rewind_state and not manager.analysis_cursor and manager._handle_premove(obs):
            self.set_phase('game in progress','Possible premove; played PGN protected');return Decision()
        if ((self.reset_board_seen or (manager.terminal_message or {}).get('reason')=='aborted') and (manager.terminal_message or manager.headers.get('Result','*')!='*')
                and not self.raw_names and not manager.analysis_cursor and not manager.rewind_state
                and len(chess.Board(f'{placement} w - - 0 1').piece_map())>=30):
            return self.hold(manager,obs,'Possible new game: completed game, observed reset and fresh opening',('fresh-after-end',),1.)
        if self._linked(manager,obs):
            self.candidate=None;self.since=None;self.frames.clear()
            self.set_phase('analysis / replay' if manager.rewind_state else 'game in progress','Legal connection to this game')
            return Decision()
        if self.mode=='continue':return Decision('hold','Position is not linked to the current PGN; choose New game or Analysis')
        if not manager.settings.split_unlinked_positions:return Decision()
        # IMPORTANT: a failed four-ply search is *absence of a connection*,
        # not positive evidence of a new game. Video rewinds, fast playback,
        # and unobserved captures routinely create larger gaps. If both player
        # names are visibly unchanged, preserve the same PGN until a true
        # boundary (new player, confirmed opening reset, or user action).
        # Once matching names triggered a hold, transient missing OCR must
        # not change it back into a timed auto-split.
        same_pair = self.same_visible_players(manager)
        pending_same_pair = bool(self.candidate and self.candidate[0]=='same-pair-unlinked')
        if ((same_pair or pending_same_pair) and not self.changed_names(manager,True)
                and not self.reset_board_seen):
            return self.hold(manager,obs,
                'Same players, unlinked position: possible video seek or missed moves; PGN preserved. '
                'Use New game to split, or return to the live board.',
                ('same-pair-unlinked',))
        visible=chess.Board(f'{placement} w - - 0 1')
        if not any(chess.Board(f'{placement} {turn} - - 0 1').is_valid() for turn in ('w','b')):return Decision('hold','Recovery error: visible position is not a valid FEN')
        changed_squares=sum(manager.rec.board.piece_at(s)!=visible.piece_at(s) for s in chess.SQUARES)
        if changed_squares<manager.settings.new_game_min_changed_squares:
            reason='Position mismatch; preserving the played PGN while collecting evidence'
            warning_after=manager.settings.unresolved_fen_seconds
            if self.candidate==('small-mismatch',placement) and warning_after and manager._clock()-self.since>=warning_after:
                reason='Persistent position mismatch; use the Game menu to choose New game, Continue or Analysis'
            return self.hold(manager,obs,reason,('small-mismatch',placement))
        opening=len(visible.piece_map())>=30
        delay=1. if opening and self.reset_board_seen and manager.terminal_message else manager.settings.new_game_change_seconds
        return self.hold(manager,obs,'Possible new game: stable board cannot be linked to the current PGN',('board',placement),delay)

    def bind(self,manager,context=None):
        boundary=self.last_boundary;generation=self.generation+1;mode=self.mode
        self.__init__();self.last_boundary=boundary;self.generation=generation;self.mode=mode
        self.names={c:manager.headers[c.title()] for c in ('white','black') if manager.headers.get(c.title(),'Unknown')!='Unknown'}
        if context:
            self.context=context;self.clocks=dict(context.get('clocks',{}));self.clock_baseline=self.clocks or None
            self.raw_names=dict(context.get('raw_names',context.get('names',{})))
        if manager.rec:self.set_phase('game in progress','Tracking selected game')

    def saved(self):
        return {'phase':self.phase,'reason':self.reason,'mode':self.mode,'last_boundary':self.last_boundary,'clocks':self.clocks,
                'clock_baseline':self.clock_baseline,'reset_board_seen':self.reset_board_seen,
                'pending_identity_check':self.pending_restart or self._metadata_pending or bool(self.reset_reads)}

    def load(self,data,manager):
        self.bind(manager)
        self.mode=data.get('mode','auto');self.last_boundary=data.get('last_boundary')
        self.clocks=data.get('clocks',{});self.clock_baseline=data.get('clock_baseline') or self.clocks or None
        self.reset_board_seen=data.get('reset_board_seen',False)
        self.pending_restart=data.get('pending_identity_check',False)

    def summary(self,manager):
        phase=self.phase
        if not manager.rec:phase='waiting for a game'
        elif phase not in ('uncertain transition','temporarily uncertain','new game detected','between games'):
            if manager.rewind_state or manager.analysis_cursor or self.mode=='analysis':phase='analysis / replay'
            elif manager.terminal_message or manager.headers.get('Result','*')!='*':phase='game completed'
        return {'state':phase,'reason':self.reason,'mode':self.mode,
                'identity':'pending' if phase=='uncertain transition' else 'confirmed' if len(self.names)==2 else 'board only',
                'buffered_observations':len(self.frames),'can_undo':bool(self.last_boundary)}
