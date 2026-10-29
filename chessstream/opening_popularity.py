"""Played-game frequencies for ranking inferred openings; entirely offline."""
from functools import lru_cache
import json
import logging
from pathlib import Path
import chess


@lru_cache(maxsize=1)
def database():
    path=Path(__file__).parent/'assets/opening-popularity.json'
    try:
        if path.stat().st_size>2_000_000:raise ValueError('Oversized popularity table')
        data=json.loads(path.read_text())
        if data.get('format_version')!=1 or data.get('depth')!=3:raise ValueError('Unsupported popularity table')
        if not isinstance(data.get('games'),int) or data['games']<1:raise ValueError('Invalid game count')
        counts=data['counts']
        if not isinstance(counts,dict):raise ValueError('Invalid frequency table')
        for line,count in counts.items():
            if not isinstance(count,int) or isinstance(count,bool) or not 0<=count<=data['games']:raise ValueError('Invalid game frequency')
            tokens=line.split()
            if not 1<=len(tokens)<=3:raise ValueError('Invalid opening depth')
            # Syntax only here; candidate legality is independently established
            # by the search before ranking, never by this frequency table.
            for token in tokens:chess.Move.from_uci(token)
        return data
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        logging.warning('Opening popularity unavailable; using deterministic legal fallback',exc_info=True)
        return {'source':'unavailable','games':0,'counts':{}}


def rank_openings(paths):
    """Rank complete candidate orders by observed frequency, then prefix counts.

    Missing entries are unknown, not proof that a legal order is impossible.
    This cannot add a candidate or authorize a move rejected by legal search.
    """
    counts=database()['counts']
    def key(line):
        count=lambda n:counts.get(' '.join(line[:n]),0)
        return (-count(len(line)),-count(1),-count(2),line[0] not in ('d2d4','e2e4'),line)
    return sorted(set(tuple(path) for path in paths),key=key)


def preference_note(line):
    data=database();count=data['counts'].get(' '.join(line))
    if count is None:return 'No database frequency for this order; deterministic inferred order used.'
    return (f"Database preference: this opening order occurs {count:,} times in the "
            f"{data['games']:,}-game {data['source']} sample. Popularity is not observed move history.")
