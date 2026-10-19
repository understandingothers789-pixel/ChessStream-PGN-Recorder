from chessstream.capture import rank_youtube_windows


def test_youtube_chess_title_ranks_before_generic_video_and_non_youtube_is_excluded():
    windows=[
        (1,"YouTube - Brave"),
        (2,"MASTER SLOWKARU RAPID EDUCATIONAL SPEEDRUN | YouTube - Brave"),
        (3,"Hikaru plays Chess.com Blitz on YouTube - Chrome"),
        (4,"ChessStream PGN Recorder - File Explorer"),
    ]
    assert [hwnd for hwnd,_ in rank_youtube_windows(windows)]==[3,2,1]


def test_youtube_windows_without_chess_terms_keep_enumeration_order():
    windows=[(1,"Music Mix - YouTube - Chrome"),(2,"Cooking - YouTube - Brave")]
    assert rank_youtube_windows(windows)==windows


def test_youtube_title_match_is_case_insensitive_and_token_based():
    assert rank_youtube_windows([(1,"CHESS.COM rapid — YOUTUBE — Brave")])==[
        (1,"CHESS.COM rapid — YOUTUBE — Brave")
    ]
    assert rank_youtube_windows([(2,"MyVideoTube - Brave")])==[]
