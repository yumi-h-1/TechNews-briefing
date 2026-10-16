import json
import sqlite3
from datetime import datetime, timedelta, timezone


class Store:
    def __init__(self, directory):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "briefing.sqlite3"
        with self.connect() as db:
            db.executescript('''
CREATE TABLE IF NOT EXISTS deliveries (
 day TEXT PRIMARY KEY, status TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
 cutoff TEXT, payload TEXT, provider_id TEXT, error TEXT
);
CREATE TABLE IF NOT EXISTS stories (
 url TEXT PRIMARY KEY, event_key TEXT NOT NULL, headline TEXT NOT NULL,
 delivered_at TEXT NOT NULL
);
''')

    def connect(self):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def get(self, day):
        with self.connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE day=?", (day,)).fetchone()
            return dict(row) if row else None

    def begin(self, day):
        with self.connect() as db:
            row = db.execute("SELECT * FROM deliveries WHERE day=?", (day,)).fetchone()
            if row and (row["status"] in {"sent", "sending", "uncertain"} or row["attempts"] >= 3):
                return False
            db.execute("INSERT INTO deliveries(day,status,attempts) VALUES (?, 'generating',1) "
                       "ON CONFLICT(day) DO UPDATE SET attempts=attempts+1, "
                       "status=CASE WHEN payload IS NULL THEN 'generating' ELSE 'prepared' END", (day,))
            return True

    def prepare(self, day, cutoff, payload):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET status='prepared',cutoff=?,payload=? WHERE day=?",
                       (cutoff.isoformat(), json.dumps(payload, ensure_ascii=False), day))

    def status(self, day, status, error=None):
        with self.connect() as db:
            db.execute("UPDATE deliveries SET status=?,error=? WHERE day=?", (status, error, day))

    def sent(self, day, provider_id):
        with self.connect() as db:
            row = db.execute("SELECT payload,cutoff FROM deliveries WHERE day=?", (day,)).fetchone()
            payload = json.loads(row["payload"])
            for item in payload["history"]:
                db.execute("INSERT OR IGNORE INTO stories VALUES (?,?,?,?)",
                           (item["url"], item["event_key"], item["headline"], row["cutoff"]))
            db.execute("UPDATE deliveries SET status='sent',provider_id=?,error=NULL WHERE day=?", (provider_id, day))

    def window(self, now):
        with self.connect() as db:
            row = db.execute("SELECT MAX(cutoff) FROM deliveries WHERE status='sent'").fetchone()
        start = datetime.fromisoformat(row[0]) if row[0] else now - timedelta(hours=24)
        return max(start, now - timedelta(hours=72))

    def history(self, now):
        since = (now - timedelta(days=14)).astimezone(timezone.utc).isoformat()
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT url,event_key,headline FROM stories "
                                               "WHERE delivered_at>=? ORDER BY delivered_at DESC LIMIT 200", (since,))]

    def sent_urls(self):
        with self.connect() as db:
            return {r[0] for r in db.execute("SELECT url FROM stories")}
