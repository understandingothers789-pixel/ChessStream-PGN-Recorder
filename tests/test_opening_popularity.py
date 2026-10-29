import json
from pathlib import Path
import chess
from chessstream import opening_popularity as popularity
from scripts.build_opening_popularity import opening

D4=('d2d4','g8f6','c2c4')
C4=('c2c4','g8f6','d2d4')


def test_real_counts_prefer_reported_d4_order():
    data=popularity.database()
    assert data['games']==279942
    assert data['counts'][' '.join(D4)]==26419
    assert data['counts'][' '.join(C4)]==94
    assert popularity.rank_openings([C4,D4])==[D4,C4]
    assert '26,419' in popularity.preference_note(D4)
    assert 'not observed' in popularity.preference_note(D4)


def test_popularity_can_reverse_old_central_pawn_heuristic(monkeypatch):
    monkeypatch.setattr(popularity,'database',lambda:{'counts':{' '.join(D4):3,' '.join(C4):1000}})
    assert popularity.rank_openings([D4,C4])==[C4,D4]


def test_missing_candidates_use_deterministic_fallback_without_dropping_orders(monkeypatch):
    monkeypatch.setattr(popularity,'database',lambda:{'counts':{},'games':0,'source':'unavailable'})
    assert popularity.rank_openings([C4,D4])==[D4,C4]
    assert 'No database frequency' in popularity.preference_note(D4)


def test_corpus_counts_are_consistent_and_have_source_provenance():
    data=popularity.database()
    assert len(data['archive_sha256'])==64 and data['source_url'].startswith('https://')
    assert data['games']+data['rejected_openings']==data['game_headers']
    for depth in (1,2,3):
        assert sum(count for key,count in data['counts'].items() if len(key.split())==depth)==data['games']
    for line in data['counts']:
        board=chess.Board()
        for uci in line.split():
            move=chess.Move.from_uci(uci);assert move in board.legal_moves;board.push(move)


def test_offline_database_loading_and_ranking_need_no_socket(monkeypatch):
    import socket
    def forbidden(*args,**kwargs):raise AssertionError('Network access is not required')
    monkeypatch.setattr(socket,'socket',forbidden)
    popularity.database.cache_clear()
    assert popularity.rank_openings([C4,D4])==[D4,C4]


def test_corrupt_table_falls_back_without_interrupting_recording(monkeypatch):
    popularity.database.cache_clear()
    with monkeypatch.context() as patch:
        patch.setattr(Path,'read_text',lambda *args,**kwargs:'{"format_version":1,"depth":3,"games":10,"counts":{"bad":99}}')
        assert popularity.rank_openings([C4,D4])==[D4,C4]
        assert popularity.database()['source']=='unavailable'
    popularity.database.cache_clear()


def test_builder_accepts_legal_prefix_and_rejects_annotations_or_illegal_moves():
    assert opening('1. d4 Nf6 2. c4 e6 3. Nc3')==list(D4)
    assert opening('1. d4 {comment} Nf6 2. c4') is None
    assert opening('1. e5 Nf6 2. c4') is None
