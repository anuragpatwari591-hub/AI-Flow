"""SEARCH -> DEDUPE -> ANALYZE -> SCORE -> COMMENTS(5) -> BEST -> SPAM CHECK -> APPROVAL QUEUE"""
import json
from . import config, db, scoring, comments, spamcheck


def process(cands, demo=False):
    c = db.conn()
    stats = dict(seen=len(cands), dup=0, low=0, spam=0, creator_cap=0, queued=0)
    past = db.past_comments(c)
    for x in cands:
        if db.seen(c, x["url"]):
            stats["dup"] += 1; continue
        if db.creator_recent(c, x["platform"], x["creator"]) >= config.MAX_PER_CREATOR_PER_30D:
            stats["creator_cap"] += 1; continue
        total, parts, moods = scoring.score(x)
        if total < config.MIN_SCORE:
            stats["low"] += 1; continue
        opts = comments.draft(x, moods)
        best_key = comments.pick_best(opts, "rec_request" in moods)
        best = opts[best_key]
        fails = spamcheck.check(best, x, moods, past)
        if fails:   # try the other options before rejecting
            for k, v in opts.items():
                if not spamcheck.check(v, x, moods, past):
                    best_key, best, fails = k, v, []; break
        if fails:
            stats["spam"] += 1; continue
        past.append(best)
        kind = "recommendation_thread" if "rec_request" in moods else "comment"
        action = ("Post the comment from your own account after approving; add the link only if replying to a recommendation request."
                  if x["platform"] != "youtube" else "Approve to post via official API, or paste manually.")
        c.execute("""INSERT INTO opportunities(platform,url,creator,title,description,top_comments,kind,score,breakdown,reason,
                     comment,comment_link,alternatives,action,is_demo,found_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                  (x["platform"], x["url"], x["creator"], x["title"], x.get("description", ""), json.dumps(x.get("top_comments", [])),
                   kind, total, json.dumps(parts), f"Detected themes: {', '.join(moods)}; {x.get('comment_count',0)} comments, {x.get('age_days','?')}d old, creator ~{x.get('creator_subs',0)} subs",
                   best, comments.link_version(best, x["platform"]), json.dumps({k: v for k, v in opts.items() if k != best_key}),
                   action, int(demo), db.now()))
        stats["queued"] += 1
    c.commit()
    return stats
