"""Official YouTube Data API v3 (read-only discovery with an API key; posting needs OAuth + approval)."""
import json, urllib.parse, urllib.request, datetime as dt
from . import config

API = "https://www.googleapis.com/youtube/v3"
QUERIES = ["hindi romantic reel", "hindi indie song", "hindi poetry shayari", "romantic edit hindi", "new hindi song recommendation",
           "late night hindi songs", "hinglish love story", "underrated hindi songs", "hindi lyrics aesthetic", "heartbreak hindi"]


def _get(path, **p):
    p["key"] = config.YOUTUBE_API_KEY
    with urllib.request.urlopen(f"{API}/{path}?{urllib.parse.urlencode(p)}", timeout=20) as r:
        return json.load(r)


def discover(queries=QUERIES, per_query=8, days=30):
    if not config.YOUTUBE_API_KEY:
        raise RuntimeError("YOUTUBE_API_KEY not set (see README). Use --demo or `import` instead.")
    after = (dt.datetime.utcnow() - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out, seen_ids = [], set()
    for q in queries:
        res = _get("search", part="snippet", q=q, type="video", maxResults=per_query, order="date",
                   publishedAfter=after, relevanceLanguage="hi", regionCode="IN")
        ids = [i["id"]["videoId"] for i in res.get("items", []) if i["id"]["videoId"] not in seen_ids]
        seen_ids.update(ids)
        if not ids:
            continue
        vids = _get("videos", part="snippet,statistics", id=",".join(ids))
        for v in vids.get("items", []):
            sn, st = v["snippet"], v.get("statistics", {})
            try:
                cm = _get("commentThreads", part="snippet", videoId=v["id"], maxResults=10, order="relevance")
                tops = [x["snippet"]["topLevelComment"]["snippet"]["textDisplay"] for x in cm.get("items", [])]
            except Exception:   # comments disabled
                tops = []
            ch = _get("channels", part="statistics", id=sn["channelId"])["items"][0]["statistics"]
            age = (dt.datetime.utcnow() - dt.datetime.strptime(sn["publishedAt"][:19], "%Y-%m-%dT%H:%M:%S")).days
            out.append(dict(platform="youtube", url=f"https://www.youtube.com/watch?v={v['id']}", creator=sn["channelTitle"],
                            title=sn["title"], description=sn.get("description", "")[:500], top_comments=tops,
                            comment_count=int(st.get("commentCount", 0)), creator_subs=int(ch.get("subscriberCount", 0)),
                            age_days=age, video_id=v["id"]))
    return out


def publish_comment(video_id, text):
    """Top-level comment via commentThreads.insert. Caller must have human approval."""
    if not config.YOUTUBE_OAUTH_TOKEN:
        raise RuntimeError("YOUTUBE_OAUTH_TOKEN not set; post manually instead.")
    body = {"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": text}}}}
    req = urllib.request.Request(f"{API}/commentThreads?part=snippet", data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {config.YOUTUBE_OAUTH_TOKEN}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)
