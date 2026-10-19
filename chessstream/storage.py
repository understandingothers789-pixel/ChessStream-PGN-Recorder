"""Durable SQLite metadata; image retention is independent of games and PGNs."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from pathlib import PureWindowsPath
import hashlib
import json
import logging
import shutil
import sqlite3
import threading
import uuid
import cv2
from .domain import utcnow, atomic_text


class Store:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.images = self.root / "screenshots"
        self.images.mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(root/"recordings.sqlite3", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, started TEXT NOT NULL, ended TEXT);
        CREATE TABLE IF NOT EXISTS games(
          id TEXT PRIMARY KEY, session_id TEXT REFERENCES sessions(id), name TEXT NOT NULL,
          started TEXT NOT NULL, updated TEXT NOT NULL, ended TEXT, status TEXT NOT NULL,
          headers TEXT NOT NULL, state TEXT NOT NULL, pgn TEXT NOT NULL, plies INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS screenshots(
          id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT REFERENCES sessions(id),
          game_id TEXT REFERENCES games(id) ON DELETE SET NULL, timestamp TEXT NOT NULL,
          sequence INTEGER NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL,
          bytes INTEGER NOT NULL, fen TEXT, confidence REAL, move_ply INTEGER, deleted INTEGER DEFAULT 0);
        CREATE INDEX IF NOT EXISTS shots_game_time ON screenshots(game_id,timestamp);
        CREATE INDEX IF NOT EXISTS shots_session ON screenshots(session_id,timestamp);
        CREATE TABLE IF NOT EXISTS observations(
          id INTEGER PRIMARY KEY, session_id TEXT, game_id TEXT REFERENCES games(id) ON DELETE SET NULL,
          timestamp TEXT NOT NULL, placement TEXT, confidence REAL, status TEXT, evidence TEXT);
        CREATE TABLE IF NOT EXISTS deletion_jobs(
          id INTEGER PRIMARY KEY, due TEXT NOT NULL, scope TEXT NOT NULL, completed TEXT, error TEXT);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, timestamp TEXT, action TEXT, detail TEXT);
        """)
        self.db.commit()

    @contextmanager
    def transaction(self):
        with self.lock:
            with self.db:
                yield self.db

    def query(self, sql, params=()) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    def session(self) -> str:
        sid = uuid.uuid4().hex
        with self.transaction() as db:
            db.execute("INSERT INTO sessions(id,started) VALUES(?,?)", (sid, utcnow()))
        return sid

    def finish_session(self, sid):
        with self.transaction() as db:
            db.execute("UPDATE sessions SET ended=? WHERE id=?", (utcnow(),sid))

    def save_game(self, gid, sid, name, started, status, headers, state, pgn, ended=None):
        with self.transaction() as db:
            db.execute("""INSERT INTO games VALUES(?,?,?,?,?,?,?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET name=excluded.name,updated=excluded.updated,
              ended=excluded.ended,status=excluded.status,headers=excluded.headers,
              state=excluded.state,pgn=excluded.pgn,plies=excluded.plies""",
              (gid,sid,name,started,utcnow(),ended,status,json.dumps(headers),json.dumps(state),pgn,len(state["verified"])))
        # Atomic autosave is recoverable even if a reader has the previous file open.
        atomic_text(self.root/"pgn"/(gid+".pgn"), pgn+"\n")

    def games(self) -> list[dict]:
        return self.query("SELECT * FROM games ORDER BY started DESC")

    def game(self, gid) -> dict | None:
        rows = self.query("SELECT * FROM games WHERE id=?", (gid,))
        return rows[0] if rows else None

    def save_observation(self, sid, gid, obs, status, evidence=None):
        with self.transaction() as db:
            db.execute("INSERT INTO observations(session_id,game_id,timestamp,placement,confidence,status,evidence) VALUES(?,?,?,?,?,?,?)",
                       (sid,gid,obs.timestamp,obs.placement(),obs.confidence,status,json.dumps(evidence) if evidence else None))

    def associate_screenshots(self, sid, gid, since=None, initial_placement=None):
        clauses=['session_id=?'];args=[sid]
        if since:clauses.append('timestamp>=?');args.append(since)
        if initial_placement:clauses.extend(['game_id IS NULL','fen=?']);args.append(initial_placement)
        with self.lock:
            rows=self.query('SELECT * FROM screenshots WHERE '+' AND '.join(clauses),args)
            for row in rows:
                old=(self.root/row['path']).resolve()
                if not old.is_relative_to(self.images.resolve()):raise ValueError('Invalid screenshot path')
                target=self.images/sid/gid/old.name
                if not row['deleted'] and old.exists():
                    target.parent.mkdir(parents=True,exist_ok=True)
                    if old!=target:old.replace(target)
                    relative=str(target.relative_to(self.root))
                else:relative=row['path']
                with self.transaction() as db:
                    db.execute('UPDATE screenshots SET game_id=?,path=? WHERE id=?',(gid,relative,row['id']))

    def save_screenshot(self, sid, gid, image, timestamp, fen=None, confidence=None, ply=0, deduplicate=False, deduplicate_position=False):
        digest = hashlib.sha256(image.tobytes()).hexdigest()
        with self.lock:
            # Compare against the last recognized position, not just the last
            # image. Fullscreen/layout transitions can generate temporary
            # unrecognized frames, and a recovered game can be associated with
            # a different game id while retaining the same board position.
            last_position = self.query("SELECT fen FROM screenshots WHERE session_id=? AND deleted=0 AND fen IS NOT NULL ORDER BY id DESC LIMIT 1", (sid,))
            if deduplicate_position and fen and last_position and last_position[0]['fen']==fen:
                return None
            last = self.query("SELECT sha256,game_id FROM screenshots WHERE session_id=? AND deleted=0 ORDER BY id DESC LIMIT 1", (sid,))
            if deduplicate and last and last[0]['game_id']==gid and last[0]["sha256"] == digest:
                return None
            sequence = self.query("SELECT COALESCE(MAX(sequence),0)+1 AS n FROM screenshots WHERE session_id=?", (sid,))[0]["n"]
            folder = self.images / sid / (gid or "unassigned")
            folder.mkdir(parents=True, exist_ok=True)
            stamp = timestamp.replace(":", "-").replace("+", "_")
            path = folder / f"{sequence:07d}_{stamp}.png"
            success, encoded = cv2.imencode(".png", image, [cv2.IMWRITE_PNG_COMPRESSION, 3])
            if not success:
                raise OSError("Could not encode captured screenshot")
            tmp = path.with_suffix(".tmp")
            with tmp.open("wb") as f:
                f.write(encoded.tobytes())
                f.flush()
            tmp.replace(path)
            with self.transaction() as db:
                cur = db.execute("INSERT INTO screenshots(session_id,game_id,timestamp,sequence,path,sha256,bytes,fen,confidence,move_ply) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (sid,gid,timestamp,sequence,str(path.relative_to(self.root)),digest,len(encoded),fen,confidence,ply))
            return cur.lastrowid

    def screenshot_filter(self, scope: dict) -> tuple[str, list]:
        unknown=set(scope)-{'game_id','session_id','before','after'}
        if unknown:raise ValueError('Unknown screenshot scope: '+', '.join(sorted(unknown)))
        if any(value is None for value in scope.values()):return '0=1',[]
        if any(not isinstance(value,str) or not value for value in scope.values()):
            raise ValueError('Screenshot scope values must be nonempty strings')
        clauses, args = ["deleted=0"], []
        # Strict allowlist; the caller cannot supply arbitrary SQL or filesystem paths.
        for key, column, op in [("game_id","game_id","="),("session_id","session_id","="),
                                 ("before","timestamp","<"),("after","timestamp",">=")]:
            if scope.get(key):
                clauses.append(f"{column}{op}?")
                args.append(scope[key])
        return " AND ".join(clauses), args

    def screenshots(self, scope=None, limit=2000):
        where,args = self.screenshot_filter(scope or {})
        return self.query(f"SELECT * FROM screenshots WHERE {where} ORDER BY timestamp DESC LIMIT ?", (*args,limit))

    def screenshot_file(self, relative: str) -> Path:
        """Resolve an app-created PNG inside screenshot storage before UI decoding."""
        if not isinstance(relative, str) or not relative:
            raise ValueError("Screenshot path is invalid")
        rel = Path(relative)
        windows_rel = PureWindowsPath(relative)
        if (rel.is_absolute() or windows_rel.is_absolute() or windows_rel.drive
                or ".." in rel.parts or ".." in windows_rel.parts):
            raise ValueError("Screenshot path must stay inside screenshot storage")
        candidate = self.root / rel
        if candidate.is_symlink():
            raise ValueError("Screenshot must not be a symbolic link")
        resolved = candidate.resolve(strict=True)
        if not resolved.is_relative_to(self.images.resolve(strict=True)) or not resolved.is_file():
            raise ValueError("Screenshot path must stay inside screenshot storage")
        if resolved.stat().st_size < 24 or resolved.stat().st_size > 256 * 1024 * 1024:
            raise ValueError("Screenshot file size is outside the supported range")
        with resolved.open("rb") as stream:
            header = stream.read(24)
        if header[:8] != b"\x89PNG\r\n\x1a\n" or header[8:16] != b"\x00\x00\x00\rIHDR":
            raise ValueError("Saved screenshot is not a valid PNG")
        width = int.from_bytes(header[16:20], "big")
        height = int.from_bytes(header[20:24], "big")
        if width < 1 or height < 1 or max(width, height) > 16_384 or width * height > 64 * 1024 * 1024:
            raise ValueError("Screenshot dimensions exceed the 64-megapixel limit")
        return resolved

    def deletion_estimate(self, scope):
        where,args = self.screenshot_filter(scope)
        return self.query(f"SELECT COUNT(*) AS count,COALESCE(SUM(bytes),0) AS bytes FROM screenshots WHERE {where}",args)[0]

    def delete_screenshots(self, scope: dict) -> dict:
        where,args = self.screenshot_filter(scope)
        count, size = 0, 0
        rows = self.query(f"SELECT id FROM screenshots WHERE {where}", args)
        for candidate in rows:
            # One file per critical section lets live capture save new evidence
            # while a large deletion runs. Recheck scope after any reassignment.
            with self.lock:
                current=self.query(f'SELECT id,path,bytes FROM screenshots WHERE id=? AND {where}',[candidate['id'],*args])
                if not current:continue
                row=current[0]
                path = (self.root/row["path"]).resolve()
                if not path.is_relative_to(self.images.resolve()):
                    raise ValueError("Refusing to delete a path outside screenshot storage")
                # Mark each file only after unlink succeeds. Partial jobs can retry safely.
                path.unlink(missing_ok=True)
                with self.transaction() as db:
                    db.execute("UPDATE screenshots SET deleted=1 WHERE id=?", (row["id"],))
                count += 1
                size += row["bytes"]
        self.audit("delete screenshots", {"scope":scope,"count":count,"bytes":size})
        return {"count":count,"bytes":size}

    def schedule_deletion(self, due: str, scope: dict) -> int:
        # Dates are stored in one UTC format for correct lexical ordering.
        value = datetime.fromisoformat(due)
        if value.tzinfo is None:
            raise ValueError("Scheduled deletion time needs a timezone")
        due = value.astimezone(timezone.utc).isoformat(timespec="milliseconds")
        with self.transaction() as db:
            cur = db.execute("INSERT INTO deletion_jobs(due,scope) VALUES(?,?)", (due,json.dumps(scope)))
            return cur.lastrowid

    def cancel_deletion(self, job_id):
        with self.transaction() as db:
            db.execute("DELETE FROM deletion_jobs WHERE id=? AND completed IS NULL", (job_id,))

    def run_retention(self, days=0, now=None):
        now = now or datetime.now(timezone.utc)
        now_text = now.isoformat(timespec="milliseconds")
        results = []
        if days > 0:
            cutoff = (now-timedelta(days=days)).isoformat(timespec="milliseconds")
            results.append(self.delete_screenshots({"before":cutoff}))
        for job in self.query("SELECT * FROM deletion_jobs WHERE completed IS NULL AND due<=?", (now_text,)):
            try:
                results.append(self.delete_screenshots(json.loads(job["scope"])))
                with self.transaction() as db:
                    db.execute("UPDATE deletion_jobs SET completed=?,error=NULL WHERE id=?",(now_text,job["id"]))
            except (OSError,ValueError) as e:
                with self.transaction() as db:
                    db.execute("UPDATE deletion_jobs SET error=? WHERE id=?", (str(e),job["id"]))
        return results

    def usage(self):
        result = self.deletion_estimate({})
        disk = shutil.disk_usage(self.root)
        return {**result,"free":disk.free,"total":disk.total}

    def audit(self, action, detail):
        logging.info("Audit %s %s",action,json.dumps(detail))
        with self.transaction() as db:
            db.execute("INSERT INTO audit(timestamp,action,detail) VALUES(?,?,?)",(utcnow(),action,json.dumps(detail)))

    def delete_game(self, gid):
        with self.transaction() as db:
            db.execute("DELETE FROM games WHERE id=?", (gid,))
        (self.root/"pgn"/(gid+".pgn")).unlink(missing_ok=True)
        self.audit("delete game data", {"game_id":gid,"screenshots":"kept"})

    def delete_pgn_files(self, game_ids, export_dir=""):
        """Delete selected app-managed PGN copies; keep game records intact."""
        pgn_dir=(self.root/"pgn").resolve()
        pgn_dir.mkdir(parents=True,exist_ok=True)
        export_root=Path(export_dir).expanduser().resolve() if export_dir else None
        deleted=[]
        for gid in dict.fromkeys(game_ids):
            if not isinstance(gid,str) or len(gid)!=32:
                raise ValueError("Invalid game ID")
            try:
                if uuid.UUID(hex=gid).hex!=gid:raise ValueError
            except (ValueError,AttributeError):
                raise ValueError("Invalid game ID") from None
            if not self.game(gid):
                raise ValueError("The selected game no longer exists")
            paths=[(pgn_dir/(gid+".pgn"),pgn_dir)]
            if export_root:paths.append((export_root/(gid+".pgn"),export_root))
            removed=False
            for path,allowed_root in paths:
                if path.resolve().parent!=allowed_root:
                    raise ValueError("PGN path is outside its app-managed PGN folder")
                if path.is_file():path.unlink();removed=True
            if removed:deleted.append(gid)
        self.audit("delete saved PGN files",{"game_ids":deleted,"game_data":"kept"})
        return deleted

    def close(self):
        with self.lock:
            self.db.close()
