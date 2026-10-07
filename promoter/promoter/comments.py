"""Drafts 5 comment options (A funny, B relatable, C subtle discovery, D Hinglish, E punchline)
adapted to the detected mood and a hook phrase pulled from the actual title. Drafts only: edit before posting."""
import hashlib, re
from . import config

STOP = set("the a an of and in on to for with is are this that my our your you i we it its at by from reel reels short shorts video official hd 4k new".split())


def hook(title):
    words = [w for w in re.findall(r"[A-Za-zऀ-ॿ']+", title) if w.lower() not in STOP]
    return " ".join(words[:4]).strip() or "this"


def _pick(options, seed):
    return options[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(options)]


def draft(c, moods):
    h, S = hook(c["title"]), config.SONG
    m = moods[0] if moods else "cinematic"
    seed = c["url"]
    T = {
     "romantic": dict(
       A=["'{h}' has no business being this cinematic 😂 someone please score this scene.", "The way this scene is begging for a soundtrack, I'm emotionally invested for no reason 😂"],
       B=["Everyone says they're not romantic until a scene like '{h}' shows up at 1am.", "This is that exact feeling where you don't need dialogue, just the right background music."],
       C=["This mood is very close to what I was chasing while writing {S}. Still figuring out if I got it right.",],
       D=["Yaar ye scene ko background music chahiye tha, aur dil ko thoda sa sukoon 😅", "Ye wali feeling ko hi toh Hindi gaano mein dhoondhte hain na."],
       E=["Directed by feelings. 🎬", "Scene: set. Soundtrack: pending. 😂"]),
     "poetry": dict(
       A=["Your poetry just made my overthinking sound underqualified 😂", "Reading '{h}' at this hour was a mistake and I regret nothing."],
       B=["Some lines hit differently when you've been thinking about the same person for three songs straight.", "Lines like these are why I keep a notes app full of half-written lyrics."],
       C=["Lines like this are what I try to chase when writing — {S} came from a similar place."],
       D=["Ye lines padh ke lagta hai kisi ne meri diary khol di 😅", "Shabd kam, ehsaas zyada. Bahut sundar."],
       E=["Notes app, meet this line. 📝", "This one's getting saved."]),
     "heartbreak": dict(
       A=["Me pretending I'm over it while this plays in my head 😂", "My playlist and I have been through a lot, this fits right in."],
       B=["The quiet kind of sad that doesn't need explaining.", "Best songs usually come out of exactly this feeling."],
       C=["This feeling is where I wrote from for {S}. Glad it resonates with someone else's version too."],
       D=["Kuch feelings gaane mein hi samajh aati hain, baaki sab chup rehta hai.", "Ye mood kaafi jaana-pehchana laga."],
       E=["Felt that. 🫠", "Too real for a Tuesday."]),
     "latenight": dict(
       A=["This deserves a soundtrack and my sleep schedule is volunteering 😂", "Nothing like a 2am thought spiral with a good background track."],
       B=["Late nights are when the best lines and worst decisions both show up.", "The 'one more reel and then sleep' lie, again."],
       C=["Late-night mood is basically the whole reason I started writing {S}."],
       D=["Raat ke is time pe sab kuch thoda zyada emotional lagta hai 😅", "Neend aur feelings ka ye clash hamesha hota hai."],
       E=["Sleep can wait. 🌙", "Another night, another playlist."]),
     "cinematic": dict(
       A=["Bro accidentally directed a music video. 🎬", "This has no business being this cinematic 😂"],
       B=["The framing alone tells a whole story, don't need captions.", "Some edits feel like they belong to a film that doesn't exist yet."],
       C=["The visuals here match the cinematic romantic mood I was going for in {S}."],
       D=["Ye frames toh seedha film ke trailer jaise lag rahe hain 🎥", "Editing kaafi clean hai, mood bilkul set."],
       E=["Cut. Print. Replay. 🎞️", "Okay, that was smooth."]),
     "rec_request": dict(
       A=["Asking for song recs is the real way to find new favourites, my playlist thanks everyone in advance 😂", "Fellow music-hoarders, assemble."],
       B=["Best recs always come from random comment sections, not algorithms.", "Looking for something soft, Hindi and slightly heartbreaking? Same."],
       C=["If you like Hindi romantic indie, I put out {S} recently. Not sure it's your thing, but happy to hear honest takes."],
       D=["Mujhe bhi naye Hindi gaane chahiye, comments mein fire list aani chahiye 😅", "Koi soft Hindi indie suggest karo yaar."],
       E=["Adding to my playlist. ➕", "Saving this thread."]),
    }
    t = T.get(m, T["cinematic"])
    opts = {k: _pick(v, seed + k).format(h=h, S=S) for k, v in t.items()}
    return opts


def pick_best(opts, has_rec_request):
    # Promotion only when it is the natural fit. Otherwise lead with a no-song reaction (C only for rec threads).
    return "C" if has_rec_request else "B"


def link_version(text, platform):
    if not config.SONG_URL:
        return None
    if platform in ("instagram", "reddit_nolinks"):
        return None   # links in IG comments aren't clickable and read as spam; use profile
    return f"{text}\n\n{config.SONG_URL}"
