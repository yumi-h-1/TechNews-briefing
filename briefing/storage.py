"""Persistent edition state; provider acceptance is distinct from inbox delivery."""
import json
import sqlite3
from datetime import timedelta
from pathlib import Path


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "briefing.sqlite3"
        with self.connect() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS editions (
 day TEXT PRIMARY KEY, status TEXT NOT NULL, generation_attempts INTEGER NOT NULL DEFAULT 0,
 send_attempts INTEGER NOT NULL DEFAULT 0, cutoff TEXT, payload TEXT,
 provider_id TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS sent_stories (
 day TEXT NOT NULL, url TEXT NOT NULL, event_key TEXT NOT NULL, headline TEXT NOT NULL,
 evidence TEXT NOT NULL, delivered_at TEXT NOT NULL, PRIMARY KEY(day,url));
CREATE TABLE IF NOT EXISTS recovery_audit (
 day TEXT NOT NULL, action TEXT NOT NULL, note TEXT NOT NULL, occurred_at TEXT NOT NULL);
''')

    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        return db

    def get(self, day):
        with self.connect() as db:
            row = db.execute("SELECT * FROM editions WHERE day=?", (day,)).fetchone()
            return dict(row) if row else None

    def begin_generation(self, day):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM editions WHERE day=?", (day,)).fetchone()
            if row and (row["payload"] or row["status"] in {"accepted", "sending", "uncertain"}
                        or row["generation_attempts"] >= 3):
                return False
            db.execute("INSERT INTO editions(day,status,generation_attempts) VALUES (?,'generating',1) "
                       "ON CONFLICT(day) DO UPDATE SET status='generating', error=NULL, "
                       "generation_attempts=generation_attempts+1", (day,))
            return True

    def prepare(self, day, cutoff, payload):
        with self.connect() as db:
            db.execute("UPDATE editions SET status='prepared',cutoff=?,payload=?,error=NULL WHERE day=?",
                       (cutoff.isoformat(), json.dumps(payload, ensure_ascii=False), day))

    def begin_send(self, day):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute("UPDATE editions SET status='sending',send_attempts=send_attempts+1 "
                                "WHERE day=? AND status='prepared' AND send_attempts<3 AND payload IS NOT NULL", (day,))
            return cursor.rowcount == 1

    def status(self, day, status, error=None):
        with self.connect() as db:
            db.execute("UPDATE editions SET status=?,error=? WHERE day=?", (status, error, day))

    def _accepted(self, db, day, provider_id):
        row = db.execute("SELECT * FROM editions WHERE day=?", (day,)).fetchone()
        if not row or not row["payload"]:
            raise ValueError("Edition has no saved payload")
        payload = json.loads(row["payload"])
        for item in payload["history"]:
            db.execute("INSERT OR IGNORE INTO sent_stories VALUES (?,?,?,?,?,?)",
                       (day, item["url"], item["event_key"], item["headline"], item["evidence"], row["cutoff"]))
        db.execute("UPDATE editions SET status='accepted',provider_id=?,error=NULL WHERE day=?", (provider_id, day))

    def accepted(self, day, provider_id):
        with self.connect() as db:
            self._accepted(db, day, provider_id)

    def window(self, now):
        with self.connect() as db:
            cutoff = db.execute("SELECT MAX(cutoff) FROM editions WHERE status='accepted'").fetchone()[0]
        from briefing.collection import instant
        return instant(cutoff) if cutoff else now - timedelta(hours=24)

    def history(self, now):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM sent_stories WHERE delivered_at>=? "
                                               "ORDER BY delivered_at DESC LIMIT 100",
                                               ((now-timedelta(days=14)).isoformat(),))]

    def recover(self, day, action, note, now, provider_id=None):
        """Caller must hold the same worker lock used for generation and delivery."""
        if not note.strip():
            raise ValueError("Provider-log evidence is required")
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM editions WHERE day=?", (day,)).fetchone()
            if not row or row["status"] not in {"sending", "uncertain"}:
                raise ValueError("Only sending/uncertain editions need reconciliation")
            if action == "accepted":
                if not provider_id:
                    raise ValueError("Provider message ID required")
                self._accepted(db, day, provider_id)
            elif action == "not-accepted":
                db.execute("UPDATE editions SET status='prepared', error='Operator confirmed no acceptance' WHERE day=?", (day,))
            else:
                raise ValueError("Unknown reconciliation action")
            db.execute("INSERT INTO recovery_audit VALUES (?,?,?,?)", (day, action, note, now.isoformat()))
