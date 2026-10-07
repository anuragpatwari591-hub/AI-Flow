import re, difflib
BANNED = ["check out my", "please support", "subscribe", "listen to my", "please stream", "link in bio", "best song ever",
          "underrated masterpiece", "follow me", "sub4sub", "guys please"]


def check(comment, c, moods, past):
    """Returns list of failed checks (empty = pass). Implements the 9-question rubric as far as code can."""
    t = comment.lower()
    fails = []
    if any(b in t for b in BANNED):
        fails.append("contains banned marketing phrase")
    if not moods:
        fails.append("no detected relevance to content")
    if len(re.findall(r"https?://", comment)) > 1 or len(comment) > 280:
        fails.append("too long / too many links")
    if comment.count("!") > 2 or re.search(r"[🔥]{2,}", comment):
        fails.append("hype punctuation")
    for p in past:
        if difflib.SequenceMatcher(None, t, p.lower()).ratio() > 0.7:
            fails.append("too similar to a previous comment"); break
    base = re.sub(r"https?://\S+", "", t)
    if "teri roshni" in base and "rec_request" not in moods and not any(w in t for w in ("writing", "wrote", "made", "chasing")):
        fails.append("song mention not earned by context")
    return fails
