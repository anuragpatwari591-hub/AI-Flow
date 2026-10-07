import html, json
from . import db, config, repurpose

CSS = "body{font:15px system-ui;max-width:860px;margin:2rem auto;padding:0 1rem;background:#111;color:#eee}.card{border:1px solid #333;border-radius:10px;padding:1rem;margin:1rem 0;background:#1a1a1a}.s{font-size:1.4rem;font-weight:700}.demo{background:#7a1f1f;padding:2px 8px;border-radius:6px}pre{white-space:pre-wrap;background:#0d0d0d;padding:.6rem;border-radius:6px}a{color:#8ab4ff}.m{color:#999}"


def render(path, status="pending", limit=20):
    c = db.conn()
    rows = c.execute("SELECT * FROM opportunities WHERE status=? ORDER BY score DESC LIMIT ?", (status, limit)).fetchall()
    h = [f"<html><meta charset=utf-8><style>{CSS}</style><h1>{config.SONG}: approval queue ({status})</h1>"
         f"<p class=m>Nothing publishes without `promoter approve ID` + `promoter publish ID`.</p>"]
    for r in rows:
        e = html.escape
        alts = json.loads(r["alternatives"] or "{}")
        h.append(f"<div class=card><span class=s>#{r['id']} · {r['score']}/100</span> "
                 f"{'<span class=demo>DEMO DATA, not a real post</span>' if r['is_demo'] else ''}"
                 f"<p><b>{e(r['platform'])}</b> · {e(r['creator'])}<br><a href='{e(r['url'])}'>{e(r['title'])}</a></p>"
                 f"<p class=m>{e(r['reason'])}<br>breakdown: {e(r['breakdown'])}</p><b>BEST COMMENT</b><pre>{e(r['comment'])}</pre>"
                 + (f"<b>LINK VERSION</b><pre>{e(r['comment_link'])}</pre>" if r['comment_link'] else "")
                 + "<b>ALTERNATIVES</b>" + "".join(f"<pre>{k}: {e(v)}</pre>" for k, v in alts.items())
                 + f"<p><b>ACTION</b> {e(r['action'])}<br><code>approve {r['id']} | reject {r['id']} | edit {r['id']} \"new text\"</code></p></div>")
    h.append("<h2>Content ideas</h2>")
    for i in repurpose.ideas(config.SONG):
        h.append("<div class=card>" + "<br>".join(f"<b>{k.upper()}</b>: {html.escape(v)}" for k, v in i.items()) + "</div>")
    open(path, "w").write("".join(h))
    return path
