"""A portable ChessStream copy must not write to a data folder already
owned by another running GUI instance, even if their executable paths differ.
"""
from PySide6.QtCore import QLockFile


def test_only_one_gui_writer_lock_per_library(tmp_path):
    path=str(tmp_path/'.chessstream-gui.lock')
    a=QLockFile(path)
    b=QLockFile(path)
    assert a.tryLock(100)
    try:
        assert not b.tryLock(0)
    finally:
        a.unlock()
    assert b.tryLock(100)
    b.unlock()
