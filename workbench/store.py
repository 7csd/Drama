import contextlib
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path


def uid():
    return uuid.uuid4().hex


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "media").mkdir(exist_ok=True)
        self.path = self.root / "workbench.sqlite3"
        with self.transaction() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY, kind TEXT NOT NULL, project_id TEXT,
                    episode_id TEXT, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS items_scope ON items(kind, project_id, episode_id);
                CREATE TABLE IF NOT EXISTS versions (
                    id TEXT, version INTEGER, kind TEXT, data TEXT,
                    PRIMARY KEY(id, version)
                );
            """)

    @contextlib.contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def get(self, db, kind, id):
        row = db.execute("SELECT data FROM items WHERE kind=? AND id=?", (kind, id)).fetchone()
        if not row:
            raise LookupError(f"找不到 {kind}: {id}")
        return json.loads(row[0])

    def list(self, db, kind, project_id=None, episode_id=None):
        sql, args = "SELECT data FROM items WHERE kind=?", [kind]
        for field, value in (("project_id", project_id), ("episode_id", episode_id)):
            if value is not None:
                sql += f" AND {field}=?"
                args.append(value)
        return [json.loads(row[0]) for row in db.execute(sql + " ORDER BY rowid", args)]

    def put(self, db, kind, data, bump=False):
        data = dict(data)
        data.setdefault("id", uid())
        data.setdefault("version", 1)
        data.setdefault("created_at", time.time())
        if bump:
            old = self.get(db, kind, data["id"])
            db.execute("INSERT OR IGNORE INTO versions VALUES(?,?,?,?)",
                       (old["id"], old["version"], kind, json.dumps(old, ensure_ascii=False)))
            data["version"] = old["version"] + 1
        data["updated_at"] = time.time()
        db.execute("INSERT OR REPLACE INTO items VALUES(?,?,?,?,?)", (
            data["id"], kind, data.get("project_id"), data.get("episode_id"),
            json.dumps(data, ensure_ascii=False)))
        return data

    def media_path(self, relative):
        path = (self.root / "media" / relative).resolve()
        if not path.is_relative_to(self.root / "media"):
            raise ValueError("无效的素材路径")
        return path
