"""Bounded, local-only evidence buffering and background legal gap recovery."""
from collections import deque
from time import monotonic
import cv2
import numpy as np
import chess
from .reconstruction import Reconstructor,LegalSearcher


class PositionHistory:
    """Stable board evidence survives pixel churn; never written as images."""
    def __init__(self,capacity=96):self.positions=deque(maxlen=capacity)

    def add(self,obs,game_id,threshold=.8):
        if not game_id or obs.uncertain_squares(threshold):return
        evidence=copy_observation(obs)
        if self.positions and self.positions[-1][0]==game_id and self.positions[-1][1].placement()==obs.placement():
            self.positions[-1]=(game_id,evidence)
        else:self.positions.append((game_id,evidence))

    def observations(self,game_id):
        return [obs for identity,obs in self.positions if identity==game_id]


def copy_observation(obs):
    from .domain import Observation
    return Observation(obs.probabilities.copy(),obs.timestamp,obs.orientation,obs.quality)


def extend_recovery(result,target,following,threshold=.8,time_limit_ms=75,node_limit=8000):
    """Validate intervening forward frames before applying an older result.

    A rewind, repeated position, weak or inconsistent frame rejects the result.
    Ambiguous histories remain pending. Catch-up shares one small live budget.
    """
    base,state=result;probe=Reconstructor.restore(state)
    if not probe.branches or not all(target.matches(branch.board(),threshold) for branch in probe.branches):return None
    seen={target.placement()};chain=[]
    for obs in following:
        if obs.orientation!=target.orientation or obs.uncertain_squares(threshold):return None
        placement=obs.placement()
        if placement in seen:return None
        seen.add(placement);chain.append(obs)
    recovered,_=_follow_positions(state,chain,2,node_limit,time_limit_ms,threshold)
    return (base,recovered.serialize()) if recovered else None


def _follow_positions(state,frames,max_plies,node_limit,time_limit_ms,threshold,cancelled=None):
    """Use the normal multi-hypothesis commit policy under one total budget."""
    probe=Reconstructor.restore(state);confirmation=probe.confirmation_plies
    # Input positions were already stabilized by capture. This applies only
    # to the immutable trial; restore the user's hover policy in returned data.
    probe.confirmation_plies=0;started=monotonic();nodes=0
    for obs in frames:
        if cancelled and cancelled():return None,nodes
        remaining=time_limit_ms-(monotonic()-started)*1000
        if remaining<=0 or nodes>=node_limit or obs.uncertain_squares(max(.8,threshold)):return None,nodes
        probe.searcher=LegalSearcher(max_plies,node_limit-nodes,remaining,threshold,path_limit=32,cancelled=cancelled)
        update=probe.observe(obs);nodes+=update.nodes
        if (probe.incomplete or probe.gap_requires_confirmation or not probe.branches or
                not all(branch.board().board_fen()==obs.placement() for branch in probe.branches)):
            return None,nodes
    probe.confirmation_plies=confirmation
    return probe,nodes


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


def recover_gap(states,observed,max_plies,node_limit,time_limit_ms,evidence=(),threshold=.7,cancelled=None):
    """Return proven moves or complete pending histories; never choose a tie."""
    started=monotonic();used=0
    for state in states:
        if cancelled and cancelled():return None
        remaining=time_limit_ms-(monotonic()-started)*1000
        if remaining<=0 or node_limit-used<=0:break
        probe=Reconstructor.restore(state)
        # Try retained stable landmarks before a direct endpoint search.
        anchors=[i for i,frame in enumerate(evidence) if frame.placement()==probe.board.board_fen()]
        if anchors:
            chain=list(evidence[anchors[-1]+1:])+[observed]
            trial,nodes=_follow_positions(state,chain,max_plies,node_limit-used,remaining,threshold,cancelled)
            used+=nodes
            if trial:return state,trial.serialize()
        remaining=time_limit_ms-(monotonic()-started)*1000
        if remaining<=0 or node_limit-used<=0:break
        trial,nodes=_follow_positions(state,[observed],max_plies,node_limit-used,remaining,threshold,cancelled)
        used+=nodes
        if trial:return state,trial.serialize()
    return None
