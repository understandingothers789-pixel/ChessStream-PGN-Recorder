from __future__ import annotations
import argparse
import logging
import os
import hashlib
import tempfile
from pathlib import Path
import sys
from platformdirs import user_data_path


def gui_lock_path():
    """One live GUI recorder per OS user, independent of extraction/data dir."""
    user_token=hashlib.sha256(os.path.normcase(str(Path.home())).encode('utf-8')).hexdigest()[:20]
    return Path(tempfile.gettempdir())/f'ChessStream-recorder-{user_token}.lock'


def main():
    parser=argparse.ArgumentParser(description='ChessStream PGN Recorder — local screen-to-PGN desktop application')
    parser.add_argument('--data-dir',type=Path,help='Override the default local application data folder')
    parser.add_argument('--smoke',type=Path,help='Render the live desktop view to an image and exit (GUI verification)')
    parser.add_argument('--replay',type=Path,help='Process a local prerecorded video instead of opening the GUI')
    parser.add_argument('--region',help='Video board crop: x,y,width,height')
    parser.add_argument('--interval',type=float,default=1.0,help='Permanent screenshot interval for replay')
    parser.add_argument('--orientation',choices=['auto','white','black'],default='auto')
    args=parser.parse_args()
    root=args.data_dir or user_data_path('ChessStream PGN Recorder',appauthor=False)
    root.mkdir(parents=True,exist_ok=True)
    from .diagnostics import configure_logging
    configure_logging(root)
    from .capture import enable_dpi_awareness
    enable_dpi_awareness()
    from .desktop import set_application_identity
    set_application_identity()
    if args.replay:
        from .replay import replay_video
        replay_video(args.replay,root,args.region,args.interval,args.orientation)
        return
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, QLockFile
    from PySide6.QtGui import QIcon
    from .gui import MainWindow
    app=QApplication(sys.argv[:1]);app.setApplicationName('ChessStream PGN Recorder');app.setStyle('Fusion')
    app.setWindowIcon(QIcon(str(Path(__file__).parent/'assets/icon.ico')))
    # Prevent simultaneous live captures of the same monitor from *any*
    # portable builds or data folders for the same Windows user.  A per-data-
    # folder lock did not stop the two independent recorders in the Oct 20 log.
    # Explicit video --replay remains a separate headless workflow.
    global_lock_path=gui_lock_path()
    lock=QLockFile(str(global_lock_path))
    lock.setStaleLockTime(0)  # Living PID owns the lock; don't time out a slow stream.
    if not lock.tryLock(100):
        from PySide6.QtWidgets import QMessageBox
        logging.error('ChessStream GUI already active for this user; current PID=%d, lock=%s',
                      os.getpid(),global_lock_path)
        QMessageBox.warning(None,'ChessStream already running',
            'A ChessStream recorder is already running, possibly from another '
            'extracted build or a different data folder.\n\n'
            'Close all other ChessStream instances before starting another. '
            'Running two recorders simultaneously can create separate PGNs '
            'and make analysis/replay indicators appear to flicker.')
        return
    logging.info('Exclusive ChessStream GUI acquired: pid=%d data_dir=%s lock=%s',
                 os.getpid(),root,global_lock_path)
    window=MainWindow(root);window.show()
    if args.smoke:
        window.resize(1460,940)
        def save():
            args.smoke.parent.mkdir(parents=True,exist_ok=True)
            window.grab().save(str(args.smoke));window.close();app.quit()
        QTimer.singleShot(700,save)
    try:
        sys.exit(app.exec())
    finally:
        lock.unlock()


if __name__=='__main__':
    main()
