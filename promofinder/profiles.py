"""Promo angles and audience profiles.

A show's genre is fixed, but the same show can be sold to different audiences from different angles:
a jilted-bride-marries-a-stranger show is a romance to one viewer and a revenge story to another. Paid social is
bought against interest-based audiences and creatives are A/B-tested, so the useful question is not
"which genre is this show?" but "which clip sells THIS show to THAT audience?".

* angle_vector(clip)  - share of romance / revenge / power / danger / mystery / family / humor cues in a clip
                        (dialogue, action lines and delivery tags; transparent regexes, show-agnostic).
* Profile             - a named audience: which angles it responds to, and small changes to the component
                        weights (e.g. thriller fans weight the cliffhanger more). Factor range is 0.85-1.15,
                        so a profile re-orders close calls; it never rescues a clip with no hook or no cut.
* portfolio()         - the best non-overlapping clip per angle: a ready-made set of creatives to A/B test.

Humor has little support in microdrama scripts; the profile exists but will often find few clips.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

ANGLES = {
    "romance": (r"\b(love\w*|kiss\w*|my (?:heart|darling|love|wife|husband)|marry me|hold (?:me|her|him)|embrac\w*|"
                r"tender\w*|caress\w*|beautiful|jealous\w*|protect you|never (?:leave|let) you|together|forehead|cheek|"
                r"lips|hand in hand|intimate|blush\w*|longing)\b",
                ("tender", "loving", "longing", "intimate", "affection", "soft", "gentle", "warm", "husky")),
    "revenge": (r"\b(humiliat\w*|betray\w*|revenge|pay for (?:this|it)|regret|disown\w*|slap\w*|kneel\w*|beg\w*|"
                r"worthless|how dare|mock\w*|laugh(?:s|ing)? at|trash|beggar|disgrace\w*|shame\w*|cast (?:you|her) out|"
                r"spit\w*|throw\w* (?:her|you|it) (?:out|into)|stripped|ruin\w*|crawl\w*)\b",
                ("mocking", "cruel", "smug", "triumphant", "vengeful", "spite", "gloat", "scorn", "venom", "taunt", "vindictive")),
    "power": (r"\b(do you know who i am|ceo|billionaire|duke|duchess|heir\w*|rightful|bow (?:down|before)|your grace|"
              r"my lord|inheritance|fortune|title|crown|throne|kneel before|owner|chairman|regalia|command\w*|"
              r"salute\w*|obey|by order of|stand down)\b",
              ("commanding", "authoritative", "regal", "imperious", "thunderous", "booming", "steely")),
    "danger": (r"\b(kill\w*|die|dying|dead|death|blood\w*|gun|knife|blade|sword|poison\w*|guards?|arrest\w*|execut\w*|"
               r"gallows|hang\w*|fire|flames?|burn\w*|escape|run|attack\w*|threat\w*|weapon|chain\w*|dungeon|"
               r"explosion|wound\w*|bleed\w*|torture\w*|choke\w*)\b",
               ("terrified", "panic", "menac", "deadly", "lethal", "frantic", "violent", "alarmed", "threaten")),
    "mystery": (r"\b(secret\w*|truth|who (?:are|is|was)|why did|lie[sd]?|lying|hiding|hidden|evidence|missing|"
                r"disappear\w*|signal|clue|identity|mask\w*|stranger|mysterious|unknown|suspect\w*|what really)\b",
                ("suspicious", "cryptic", "guarded", "hushed", "conspirator", "probing", "wary")),
    "family": (r"\b(mother|father|mom|dad|sister|brother|son|daughter|family|child|children|baby|parents?|"
               r"grandmother|grandfather|stepmother|home)\b",
               ("pleading", "heartbroken", "tearful", "weeping", "sob")),
    "humor": (r"\b(haha|ha!|joke\w*|funny|ridiculous|giggl\w*|chuckl\w*|grin\w*|wink\w*|silly|tease\w*|teasing)\b",
              ("amused", "playful", "teasing", "sarcastic", "wry", "deadpan", "cheeky")),
}
_RX = {k: re.compile(p, re.I) for k, (p, _) in ANGLES.items()}
_TAGS = {k: t for k, (_, t) in ANGLES.items()}
ANGLE_LABEL = {"romance": "Romance", "revenge": "Revenge & humiliation", "power": "Status / power reveal",
               "danger": "Danger & suspense", "mystery": "Mystery & secrets", "family": "Family drama", "humor": "Humor"}


def block_angles(b) -> Dict[str, float]:
    """Angle cue counts for one block (cached on the block: a block appears in thousands of windows)."""
    v = b.__dict__.get("_angles")
    if v is None:
        v = {}
        txt = b.text
        for k, rx in _RX.items():
            n = len(rx.findall(txt))
            if b.kind == "dialogue" and b.tags:
                n += sum(0.75 for t in b.tags for s in _TAGS[k] if s in t)
            if n:
                v[k] = float(n) * (1.0 if b.kind == "dialogue" else 0.6)
        b.__dict__["_angles"] = v
    return v


def angle_vector(blocks) -> Dict[str, float]:
    tot: Dict[str, float] = {}
    for b in blocks:
        for k, n in block_angles(b).items():
            tot[k] = tot.get(k, 0.0) + n
    s = sum(tot.values())
    if s <= 0:
        return {}
    # family words are everywhere in microdrama: down-weight so they only win when nothing else does
    if "family" in tot:
        tot["family"] *= 0.6
        s = sum(tot.values())
    return {k: round(v / s, 3) for k, v in sorted(tot.items(), key=lambda x: -x[1])}


def primary(vec: Dict[str, float]) -> str:
    if not vec:
        return "mixed"
    k, v = next(iter(vec.items()))
    return k if v >= 0.34 else "mixed"


@dataclass
class Profile:
    key: str
    label: str
    angles: Dict[str, float]                       # angle -> affinity weight (sums ~1)
    weights: Dict[str, float] = field(default_factory=dict)   # multiplicative changes to component weights
    description: str = ""
    strength: float = 0.3                          # factor range: 1 +- strength/2

    def affinity(self, vec: Dict[str, float]) -> float:
        return sum(vec.get(k, 0.0) * w for k, w in self.angles.items())

    def factor(self, c) -> float:
        if not self.angles:
            return 1.0
        a = self.affinity(c.angle.get("vector", {}))
        return 1.0 - self.strength / 2 + self.strength * min(1.0, a / 0.6)

    def apply_weights(self, W: Dict[str, float]) -> Dict[str, float]:
        return {k: round(v * self.weights.get(k, 1.0), 4) for k, v in W.items()}


PROFILES: Dict[str, Profile] = {
    "general": Profile("general", "General audience", {}, {},
                       "The default ranking: hook, cliffhanger, clarity, intensity and premise only."),
    "romance": Profile("romance", "Romance seekers", {"romance": 1.0}, {"arc": 1.2, "standalone": 1.1},
                       "Viewers who follow couples: tender or charged moments between the leads, protection, jealousy."),
    "revenge": Profile("revenge", "Revenge & underdog drama fans", {"revenge": 0.7, "power": 0.3}, {"hook": 1.15},
                       "Humiliation, betrayal and the moment the tables turn. The classic microdrama ad."),
    "thriller": Profile("thriller", "Suspense & thriller fans", {"danger": 0.7, "mystery": 0.3}, {"cliff": 1.25},
                        "Threats, danger and ticking clocks; the cliffhanger matters most."),
    "mystery": Profile("mystery", "Mystery fans", {"mystery": 0.8, "danger": 0.2}, {"cliff": 1.2, "standalone": 1.1},
                       "Secrets, hidden identities and questions the viewer needs answered."),
    "power": Profile("power", "Status-reveal / glow-up fans", {"power": 0.8, "revenge": 0.2}, {"premise": 1.2},
                     "Hidden status revealed, the underestimated hero commanding the room."),
    "family": Profile("family", "Family drama audience", {"family": 0.7, "romance": 0.3}, {"standalone": 1.15},
                      "Parents, siblings, children: loyalty and betrayal inside the family."),
    "humor": Profile("humor", "Light / humor audience", {"humor": 1.0}, {"arc": 0.85},
                     "Playful or comic beats. Rare in microdrama scripts, so expect few strong matches."),
}


def get_profile(key: Optional[str], series=None) -> Optional[Profile]:
    if not key or key == "general":
        return None
    return PROFILES.get(key)


def portfolio(cands, n_per_angle=1, exclude_overlap=True):
    """Best clip for each angle (by score), not overlapping each other: creatives for A/B testing."""
    chosen, out = [], {}
    for ang in ANGLES:
        best = [c for c in cands if c.angle.get("primary") == ang]
        for c in best:
            if exclude_overlap and any(_ov(c, d) for d in chosen):
                continue
            out.setdefault(ang, []).append(c); chosen.append(c)
            if len(out[ang]) >= n_per_angle:
                break
    return out


def _ov(a, b):
    return any(x.episode == y.episode and x.start < y.end - 0.5 and y.start < x.end - 0.5 for x in a.segments for y in b.segments)
