"""Pure saved-PGN work: immutable requests, no database or recorder access."""
import time
from .gap_join import join_recordings, AmbiguousGapError
from .reconstruction import LegalSearcher


def search_previous(rows, current, threshold, cancelled):
    started=time.monotonic();blockers=[]
    deadline=started+5.
    for previous in rows:
        if cancelled():return {'message':'Join previous canceled • source PGNs preserved'}
        try:
            pgn=join_recordings([previous,current],LegalSearcher(6,60000,500,threshold),
                               cancelled=cancelled,deadline=deadline)
        except AmbiguousGapError as error:
            blockers.append(f'{len(error.alternatives)} plausible move orders need confirmation')
            continue
        except ValueError as error:
            if 'inconclusive' in str(error) or 'limit' in str(error):blockers.append('gap search limits reached')
            continue
        return {'pgn':pgn,'sources':[previous,current],'elapsed_ms':(time.monotonic()-started)*1000}
    return {'message':'Join previous • '+(blockers[0] if blockers else 'no compatible connection found in the two previous PGNs')+
            '; source PGNs preserved','elapsed_ms':(time.monotonic()-started)*1000}
