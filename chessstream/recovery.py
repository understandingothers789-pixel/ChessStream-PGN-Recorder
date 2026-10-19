"""Bounded, local-only evidence buffering and background legal gap recovery."""
from collections import deque
from time import monotonic
import cv2
import numpy as np
import chess
from .reconstruction import Reconstructor,LegalSearcher,Branch


class RecentFrames:
    """At most 12 changed frames in RAM; repeats refresh evidence timestamps."""
    def __init__(self,capacity=12):self.frames=deque(maxlen=capacity)

    def add(self,image,observation):
        h,w=image.shape[:2];scale=min(1.,768/max(h,w))
        tile=cv2.resize(image,(round(w*scale),round(h*scale))) if scale<1 else image.copy()
        if self.frames and np.array_equal(tile,self.frames[-1]['image']):
            self.frames[-1]['last_seen']=observation.timestamp
            self.frames[-1]['comparisons']+=1
            return
        # Keep only bounded-size pixels and model distributions. No files are written.
        self.frames.append({'image':tile,'observation':observation,'last_seen':observation.timestamp,'comparisons':1,'game_id':None,'usable':False})

    def mark(self,game_id,usable):
        if self.frames:self.frames[-1].update(game_id=game_id,usable=usable)

    def observations(self,game_id):
        return [entry['observation'] for entry in self.frames if entry['usable'] and entry['game_id']==game_id]


def recover_gap(states,observed,max_plies,node_limit,time_limit_ms,evidence=(),threshold=.7):
    """Pure worker: never reads the database or mutates the live recording."""
    started=monotonic();used=0
    for state in states:
        remaining=time_limit_ms-(monotonic()-started)*1000
        if remaining<=0 or node_limit-used<=0:break
        probe=Reconstructor.restore(state)
        # If the retained images contain the source, first reconstruct through
        # their intermediate positions instead of jumping straight to the end.
        anchors=[i for i,frame in enumerate(evidence) if frame.placement()==probe.board.board_fen()]
        if anchors:
            trial=Reconstructor.restore(state)
            chain=list(evidence[anchors[-1]+1:])+[observed]
            complete=True
            for frame in chain:
                if frame.uncertain_squares(max(.8,threshold)):continue
                remaining=time_limit_ms-(monotonic()-started)*1000
                if remaining<=0 or node_limit-used<=0:complete=False;break
                step=LegalSearcher(max_plies,node_limit-used,remaining,threshold).search(trial.board,frame,first_shortest=True)
                used+=step.nodes
                if not step.paths:complete=False;break
                for move in step.paths[0]:
                    trial.board.push(move);trial.verified.append(move.uci());trial.history.append(trial.board.board_fen())
            if complete and trial.board.board_fen()==observed.placement():
                trial.branches=[Branch(trial.board.fen(),())]
                return state,trial.serialize()
        remaining=time_limit_ms-(monotonic()-started)*1000
        if remaining<=0 or node_limit-used<=0:break
        result=LegalSearcher(max_plies,node_limit-used,remaining,threshold).search(probe.board,observed,first_shortest=True)
        used+=result.nodes
        if not result.paths:continue
        for move in result.paths[0]:
            probe.board.push(move);probe.verified.append(move.uci());probe.history.append(probe.board.board_fen())
        if probe.board.board_fen()!=observed.placement():continue
        probe.branches=[Branch(probe.board.fen(),())];probe.incomplete=False
        return state,probe.serialize()
    return None
