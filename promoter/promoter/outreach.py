from . import config
from .comments import hook


def creator_message(c):
    """Personalised DM/email draft. Needs a human to add a genuine specific detail before sending."""
    return (f"Hey {c['creator']}, saw your recent post '{hook(c['title'])}'.\n\n"
            f"The mood reminded me of a song I just released, {config.SONG}. [ADD ONE SPECIFIC THING YOU ACTUALLY LIKED ABOUT THEIR WORK]\n\n"
            f"Here it is: {config.SONG_URL or '[SONG LINK]'}\n\nNo pressure at all, just thought it might suit your style.")
