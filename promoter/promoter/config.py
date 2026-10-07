"""Config: env vars first, then promoter/data/config.json. No secrets in code."""
import json, os, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "promoter.db"

_file = {}
_p = DATA / "config.json"
if _p.exists():
    _file = json.loads(_p.read_text())


def get(key, default=""):
    return os.environ.get(key) or _file.get(key) or default


SONG = get("SONG_TITLE", "TERI ROSHNI")
ARTIST = get("ARTIST", "ANURAG")
LABEL = get("PRODUCTION", "AP STUDIOS")
SONG_URL = get("SONG_URL")            # official YouTube video link
CHANNEL_URL = get("CHANNEL_URL")
INSTAGRAM_URL = get("INSTAGRAM_URL")
YOUTUBE_API_KEY = get("YOUTUBE_API_KEY")        # read-only discovery
YOUTUBE_OAUTH_TOKEN = get("YOUTUBE_OAUTH_TOKEN")  # only needed to publish approved comments

MIN_SCORE = 75
MAX_PER_CREATOR_PER_30D = 1
MAX_LINK_COMMENTS_PER_DAY = 3
MAX_PUBLISH_PER_DAY = 5
