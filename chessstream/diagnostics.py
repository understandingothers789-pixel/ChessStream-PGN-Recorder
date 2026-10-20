"""Bounded persistent diagnostics and a user-exported support bundle."""
from pathlib import Path
import json
import logging
from logging.handlers import RotatingFileHandler
import platform
import sys
import threading
import zipfile
from .domain import utcnow


def configure_logging(root):
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    logger=logging.getLogger();logger.setLevel(logging.INFO)
    target=(root/'application.log').resolve()
    if not any(isinstance(h,RotatingFileHandler) and Path(h.baseFilename)==target for h in logger.handlers):
        handler=RotatingFileHandler(target,maxBytes=2_000_000,backupCount=3,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s pid=%(process)d thread=%(threadName)s %(name)s %(message)s'))
        logger.addHandler(handler)
    def exception_hook(kind,value,traceback):
        logging.critical('Unhandled application exception',exc_info=(kind,value,traceback))
    sys.excepthook=exception_hook
    threading.excepthook=lambda args:exception_hook(args.exc_type,args.exc_value,args.exc_traceback)
    logging.info('ChessStream started on %s; Python %s; data folder %s',platform.platform(),sys.version.split()[0],root)


def export_diagnostics(store,path):
    """No screenshots, screen pixels or database file locks are included."""
    for handler in logging.getLogger().handlers:handler.flush()
    report={'created':utcnow(),'platform':platform.platform(),'python':sys.version,
            'observations':store.query('SELECT * FROM observations ORDER BY id DESC LIMIT 5000'),
            'audit':store.query('SELECT * FROM audit ORDER BY id DESC LIMIT 2000')}
    games=store.games()
    report['games']=[{k:g[k] for k in ['id','name','started','ended','status','headers','state','plies']} for g in games]
    with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('diagnostics.json',json.dumps(report,indent=2,default=str))
        for log in store.root.glob('application.log*'):
            if log.is_file():archive.write(log,'logs/'+log.name)
        settings=store.root/'settings.json'
        if settings.exists():archive.write(settings,'settings.json')
        for game in games:archive.writestr('pgn/'+game['id']+'.pgn',game['pgn'])
    return Path(path)
