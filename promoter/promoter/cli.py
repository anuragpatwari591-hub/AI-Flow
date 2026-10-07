import argparse, json, sys
from . import config, db, pipeline, dashboard, outreach

DEMO = config.ROOT / "data" / "demo_candidates.json"


def cmd_promote(a):
    if a.demo:
        cands = json.loads(DEMO.read_text()); demo = True
    elif a.file:
        cands = json.loads(open(a.file).read()); demo = False
    else:
        from . import sources_youtube
        cands = sources_youtube.discover(); demo = False
    print("cycle:", pipeline.process(cands, demo))
    p = dashboard.render(str(config.ROOT / "data" / "report.html"))
    cmd_queue(a)
    print("report:", p)


def cmd_queue(a):
    for r in db.conn().execute("SELECT * FROM opportunities WHERE status='pending' ORDER BY score DESC LIMIT 20"):
        print(f"━━━━━━━━\n#{r['id']} [{r['score']}/100] {r['platform']} · {r['creator']}{'  (DEMO)' if r['is_demo'] else ''}\n{r['url']}\nWHY: {r['reason']}\nBEST: {r['comment']}")
        if r['comment_link']: print(f"LINK VERSION: {r['comment_link']}")
        print(f"ACTION: {r['action']}")


def _set(i, status, text=None):
    c = db.conn()
    if text:
        c.execute("UPDATE opportunities SET comment=? WHERE id=?", (text, i))
    c.execute("UPDATE opportunities SET status=?, decided_at=? WHERE id=?", (status, db.now(), i)); c.commit()


def cmd_publish(a):
    c = db.conn()
    r = c.execute("SELECT * FROM opportunities WHERE id=?", (a.id,)).fetchone()
    if not r or r["status"] != "approved": sys.exit("Only APPROVED items can be published.")
    if r["is_demo"]: sys.exit("Demo item: not a real post.")
    n = c.execute("SELECT COUNT(*) FROM opportunities WHERE status='posted' AND posted_at>=date('now')").fetchone()[0]
    if n >= config.MAX_PUBLISH_PER_DAY: sys.exit("Daily publish cap reached.")
    text = r["comment_link"] if a.with_link and r["comment_link"] else r["comment"]
    if r["platform"] != "youtube" or not config.YOUTUBE_OAUTH_TOKEN:
        print("MANUAL ACTION: open", r["url"], "and post:\n\n" + text)
    else:
        if input(f"Post to {r['url']}?\n{text}\n[type yes] ") != "yes": sys.exit("cancelled")
        from . import sources_youtube
        sources_youtube.publish_comment(r["url"].split("v=")[-1], text)
    c.execute("UPDATE opportunities SET status='posted', posted_at=? WHERE id=?", (db.now(), a.id)); c.commit()


def main():
    p = argparse.ArgumentParser(prog="promoter"); s = p.add_subparsers(dest="cmd", required=True)
    x = s.add_parser("promote"); x.add_argument("--demo", action="store_true"); x.add_argument("--file", help="JSON of manually found public posts"); x.set_defaults(f=cmd_promote)
    s.add_parser("queue").set_defaults(f=cmd_queue)
    for n in ("approve", "reject"):
        y = s.add_parser(n); y.add_argument("id", type=int); y.set_defaults(f=lambda a, n=n: _set(a.id, "approved" if n == "approve" else "rejected"))
    y = s.add_parser("edit"); y.add_argument("id", type=int); y.add_argument("text"); y.set_defaults(f=lambda a: _set(a.id, "pending", a.text))
    y = s.add_parser("publish"); y.add_argument("id", type=int); y.add_argument("--with-link", action="store_true"); y.set_defaults(f=cmd_publish)
    y = s.add_parser("outreach"); y.add_argument("id", type=int); y.set_defaults(f=lambda a: print(outreach.creator_message(dict(db.conn().execute("SELECT * FROM opportunities WHERE id=?", (a.id,)).fetchone()))))
    a = p.parse_args(); a.f(a)
