"""Content ideas. SONG SECTION fields are placeholders: fill timestamps from the real track."""
IDEAS = [
 ("POV: the scene you wanted to be in a film", "POV: you finally say it. Cue the music.", "Chorus / hook", "Slow-mo walk, golden hour, handheld", "some moods need a soundtrack", "Soundtrack or no soundtrack? Comment."),
 ("Songwriting confession", "The line I rewrote 11 times", "Verse 1 (most personal line)", "Notes app typing, then the line sung", "How the hook of {song} was written", "Which line should I break down next?"),
 ("Late-night voice-note", "2am idea that became {song}", "First 15s demo vs final", "Phone-camera studio shot, dim light", "From voice note to release", "Want the full story? Say yes."),
 ("Lyric snippet card", "One line, one feeling", "Hook lyric", "Typography on dark cinematic still", "Save it for someone", "Send it to the person it fits."),
 ("Question post", "Which feels truer: loving quietly or saying it out loud?", "None (poll sticker)", "Plain text on aesthetic bg", "No right answer", "Vote, then listen to {song}."),
 ("Behind the scenes at AP STUDIOS", "How the vocals were recorded", "Vocal take", "Mic close-up, headphone shot", "Studio day, real take", "Follow for more process clips."),
 ("Meme: what I say vs what the song says", "Me: I'm fine. {song}:", "Emotional peak", "Split text meme over reaction cut", "We've all been there 😂", "Tag a friend who needs this."),
 ("Reaction prompt / duet", "React to the first 20 seconds", "Intro", "Duet layout, creator reaction", "Honest reactions welcome", "Duet with your honest first reaction."),
]


def ideas(song):
    return [dict(zip(("hook", "text", "song_section", "visual", "caption", "cta"), [s.format(song=song) for s in i])) for i in IDEAS]
