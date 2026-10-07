import sqlite3, datetime as dt
from .config import DB_PATH, DATA

SCHEMA = """
CREATE TABLE IF NOT EXISTS opportunities(
 id INTEGER PRIMARY KEY, platform TEXT, url TEXT UNIQUE, creator TEXT, title TEXT,
 description TEXT, top_comments TEXT, kind TEXT DEFAULT 'comment', score INTEGER,
 breakdown TEXT, reason TEXT, comment TEXT, comment_link TEXT, alternatives TEXT,
 outreach TEXT, action TEXT, status TEXT DEFAULT 'pending', is_demo INTEGER DEFAULT 0,
 found_at TEXT, decided_at TEXT, posted_at TEXT);
CREATE TABLE IF NOT EXISTS comment_log(comment TEXT, at TEXT);
"""


def conn():
    DATA.mkdir(exist_ok=True)
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    return c


def now():
    return dt.datetime.utcnow().isoformat(timespec="seconds")


def seen(c, url):
    return c.execute("SELECT 1 FROM opportunities WHERE url=?", (url,)).fetchone() is not None


def creator_recent(c, platform, creator, days=30):
    cut = (dt.datetime.utcnow() - dt.timedelta(days=days)).isoformat()
    return c.execute("SELECT COUNT(*) n FROM opportunities WHERE platform=? AND creator=? AND found_at>? AND status IN ('pending','approved','posted')",
                     (platform, creator, cut)).fetchone()["n"]


def past_comments(c):
    return [r[0] for r in c.execute("SELECT comment FROM opportunities WHERE comment IS NOT NULL")]
