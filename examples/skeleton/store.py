"""存储：一个 SQLite 文件，三张表。

    configs  每个指纹对应的完整配置，事后能查到“这个版本到底是什么”
    deploys  线上当前用哪个指纹（一个指针）；deploy_log 记下每次切换，发布和回滚都只是改这个指针
    jobs     任务的状态（queued / running / done / failed）、尝试次数、租约到期时间
    events   只追加的事件日志，按 (job_id, seq) 排序；恢复、轨迹、导出评测题都从这里读
"""
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager

SCHEMA = """
CREATE TABLE IF NOT EXISTS configs (config_id TEXT PRIMARY KEY, body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS deploys (name TEXT PRIMARY KEY, config_id TEXT, updated REAL);
CREATE TABLE IF NOT EXISTS deploy_log (ts REAL, name TEXT, config_id TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS jobs (
  job_id TEXT PRIMARY KEY, session_id TEXT, case_id TEXT, question TEXT, config_id TEXT,
  status TEXT, attempts INTEGER DEFAULT 0, lease_until REAL, worker TEXT,
  created REAL, started REAL, finished REAL, result TEXT, error TEXT);
CREATE TABLE IF NOT EXISTS events (
  job_id TEXT, seq INTEGER, ts REAL, type TEXT, payload TEXT, PRIMARY KEY (job_id, seq));
"""


class Store:
    def __init__(self, path):
        self.path = path
        with self.db() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    @contextmanager
    def db(self):
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def save_config(self, cid, cfg):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO configs VALUES (?, ?)", (cid, json.dumps(cfg, ensure_ascii=False)))

    def config(self, cid):
        with self.db() as db:
            row = db.execute("SELECT body FROM configs WHERE config_id = ?", (cid,)).fetchone()
        return json.loads(row["body"]) if row else None

    def deploy(self, name, cid, note=""):
        """发布或回滚：把线上指针指向另一个指纹。已经在跑的任务不受影响，它们钉在提交时的指纹上。"""
        now = time.time()
        with self.db() as db:
            db.execute("INSERT INTO deploys VALUES (?, ?, ?) ON CONFLICT(name) DO UPDATE SET config_id = excluded.config_id, "
                       "updated = excluded.updated", (name, cid, now))
            db.execute("INSERT INTO deploy_log VALUES (?, ?, ?, ?)", (now, name, cid, note))

    def active(self, name):
        with self.db() as db:
            row = db.execute("SELECT config_id FROM deploys WHERE name = ?", (name,)).fetchone()
        return row["config_id"] if row else None

    def submit(self, question, session_id, config_id, case_id=None):
        jid = uuid.uuid4().hex[:8]
        with self.db() as db:
            db.execute("INSERT INTO jobs (job_id, session_id, case_id, question, config_id, status, created) "
                       "VALUES (?, ?, ?, ?, ?, 'queued', ?)", (jid, session_id, case_id, question, config_id, time.time()))
        return jid

    def claim(self, worker, lease_s):
        """领一个任务：排队中的，或者租约过期的（领它的 worker 已经死了）。同一个会话已有任务在跑就跳过。"""
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM jobs WHERE (status = 'queued' OR (status = 'running' AND lease_until < ?)) "
                "AND session_id NOT IN (SELECT session_id FROM jobs WHERE status = 'running' AND lease_until >= ?) "
                "ORDER BY created LIMIT 1", (now, now)).fetchone()
            if row is None:
                db.execute("COMMIT")
                return None
            db.execute("UPDATE jobs SET status = 'running', attempts = attempts + 1, lease_until = ?, worker = ?, "
                       "started = COALESCE(started, ?) WHERE job_id = ?", (now + lease_s, worker, now, row["job_id"]))
            db.execute("COMMIT")
            return dict(row, attempts=row["attempts"] + 1, worker=worker)

    def renew(self, job_id, lease_s):
        with self.db() as db:
            db.execute("UPDATE jobs SET lease_until = ? WHERE job_id = ?", (time.time() + lease_s, job_id))

    def append(self, job_id, type_, payload):
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            seq = db.execute("SELECT COALESCE(MAX(seq), -1) + 1 FROM events WHERE job_id = ?", (job_id,)).fetchone()[0]
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?, ?)",
                       (job_id, seq, time.time(), type_, json.dumps(payload, ensure_ascii=False)))
            db.execute("COMMIT")

    def events(self, job_id):
        with self.db() as db:
            rows = db.execute("SELECT * FROM events WHERE job_id = ? ORDER BY seq", (job_id,)).fetchall()
        return [dict(r, payload=json.loads(r["payload"])) for r in rows]

    def finish(self, job_id, result):
        with self.db() as db:
            db.execute("UPDATE jobs SET status = 'done', finished = ?, result = ? WHERE job_id = ?",
                       (time.time(), json.dumps(result, ensure_ascii=False), job_id))

    def fail(self, job_id, error):
        with self.db() as db:
            db.execute("UPDATE jobs SET status = 'failed', finished = ?, error = ? WHERE job_id = ?",
                       (time.time(), error, job_id))

    def jobs(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY created").fetchall()]

    def pending(self):
        with self.db() as db:
            return db.execute("SELECT COUNT(*) FROM jobs WHERE status IN ('queued', 'running')").fetchone()[0]
