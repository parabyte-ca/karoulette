"""Engine constants and the error type every part of the engine raises."""
from __future__ import annotations

import hashlib

JOIN_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
SEED_THEMES = [
    ("80s", "Anything released in the 1980s.", 1.0),
    ("Duets", "Grab a partner and share the mic.", 1.0),
    ("From a Soundtrack", "Songs from films, TV or musicals.", 1.0),
    ("Canadiana", "Canadian artists, coast to coast to coast.", 1.0),
    ("90s", "Anything released in the 1990s.", 1.0),
    ("Power Ballads", "Big hair, bigger choruses.", 1.0),
    ("Guilty Pleasures", "The song you secretly know every word to.", 1.0),
    ("One-Hit Wonders", "Artists famous for exactly one song.", 1.0),
]
# Search ideas offered on phones for each starter theme (hosts can edit them in Host admin → Themes).
SEED_IDEAS = {
    "80s": "Bon Jovi, Whitney Houston, a-ha, Cyndi Lauper, Journey, Madonna",
    "Duets": "Islands in the Stream, Don't Go Breaking My Heart, Shallow, Summer Nights",
    "From a Soundtrack": "Let It Go, My Heart Will Go On, Mamma Mia, Greased Lightnin', Footloose",
    "Canadiana": "Shania Twain, Bryan Adams, Alanis Morissette, Celine Dion, The Tragically Hip, Avril Lavigne",
    "90s": "Spice Girls, Oasis, Backstreet Boys, TLC, No Doubt, Mariah Carey",
    "Power Ballads": "Bonnie Tyler, Heart, Foreigner, Aerosmith, Celine Dion",
    "Guilty Pleasures": "Barbie Girl, MMMBop, Macarena, Call Me Maybe, Mambo No. 5",
    "One-Hit Wonders": "Come On Eileen, Tainted Love, Ice Ice Baby, Who Let the Dogs Out, Macarena",
}
ACTIVE_QUEUE_STATUSES = ("queued", "playing")
COLOUR_SCHEMES = ("neon", "onair", "synthwave", "velvet", "aurora", "disco", "stage")
# Main Stage's built-in banner (a big one for the TV, a small one for phones, a 1200x630 link-preview crop).
STAGE_BANNER = {"banner": "/banners/main-stage.jpg", "banner_small": "/banners/main-stage-800.jpg",
                "og_image": "/banners/main-stage-og.jpg"}
DEFAULT_SCHEME = "neon"
REACTIONS = ("👏", "🔥", "😂", "❤️", "🎉", "🤘")
VIDEO_COMMANDS = ("toggle", "volume_up", "volume_down")
UNKNOWN_DURATION_S = 240  # what the recap and wait estimates assume when YouTube gave no length


class EngineError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
