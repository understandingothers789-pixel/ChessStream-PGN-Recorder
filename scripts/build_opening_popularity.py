"""Build small frequency counts from a downloaded public PGN ZIP; no network.

Example: python scripts/build_opening_popularity.py /path/to/lichess_elite_2025-11.zip
Only standard-start games with three legal, unannotated opening plies on their
first movetext line are counted. Original games/player names are not bundled.
"""
import argparse
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile
import chess

SOURCE='https://database.nikonoel.fr/lichess_elite_2025-11.zip'
ARCHIVE_SHA256='1ffa577aa0a1352fa04c9a890a6706049a3a79edc52810b136758d1e2a1a2eab'
ROOT=Path(__file__).resolve().parents[1]


def opening(line):
    # These exports wrap at 80 columns; the first three plies fit on one line.
    text=re.sub(r'\d+\.(?:\.\.)?', ' ',line).strip()
    tokens=text.split()[:3]
    if len(tokens)!=3:return None
    board=chess.Board();moves=[]
    try:
        for san in tokens:
            move=board.parse_san(san)
            if move not in board.legal_moves:return None
            board.push(move);moves.append(move.uci())
    except ValueError:return None
    return moves


def build(path):
    counts=Counter();games=0;headers=0;rejected=0
    if path.stat().st_size>128*1024*1024:raise ValueError('Archive exceeds supported size')
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    if digest!=ARCHIVE_SHA256:raise ValueError('Archive differs from pinned source; review and update provenance first')
    with zipfile.ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist())>512*1024*1024:raise ValueError('PGN expansion exceeds supported size')
        for info in archive.infolist():
            if not info.filename.lower().endswith('.pgn'):continue
            pending=False;standard=True
            with archive.open(info) as raw:
                for line in io.TextIOWrapper(raw,encoding='utf-8-sig',errors='strict'):
                    if line.startswith('[Event '):pending=True;standard=True;headers+=1
                    if line.startswith('[FEN ') or line.startswith('[SetUp "1"'):standard=False
                    if line.startswith('[Variant ') and '"Standard"' not in line:standard=False
                    if not pending or not line.strip() or line.startswith('['):continue
                    pending=False
                    moves=opening(line) if standard else None
                    if moves is None:rejected+=1;continue
                    games+=1
                    for depth in (1,2,3):counts[' '.join(moves[:depth])]+=1
    return {'format_version':1,'source':'Lichess Elite Database, November 2025',
            'source_url':SOURCE,'source_page':'https://database.nikonoel.fr/',
            'archive_sha256':digest,
            'selection':'Standard-start games with three legal unannotated opening plies on first movetext line; elite 2500+ vs 2300+, excluding bullet per source publisher.',
            'games':games,'game_headers':headers,'rejected_openings':rejected,
            'depth':3,'counts':dict(sorted(counts.items()))}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('archive',type=Path)
    parser.add_argument('--output',type=Path,default=ROOT/'chessstream/assets/opening-popularity.json')
    args=parser.parse_args();data=build(args.archive)
    args.output.write_text(json.dumps(data,separators=(',',':'))+'\n')
    print(json.dumps({key:value for key,value in data.items() if key!='counts'},indent=2))
    for line in ('d2d4','c2c4','d2d4 g8f6 c2c4','c2c4 g8f6 d2d4'):print(line,data['counts'].get(line,0))
