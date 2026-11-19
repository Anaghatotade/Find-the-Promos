"""Small, auditable lexicons. Genre-level (microdrama), not show-specific.

These are deliberately transparent: every weight here can be read and changed by
an editor. Learned models sit on top of them (see models.py).
"""
import functools
import re

# Delivery/emotion tags -> arousal (0 calm .. 1 explosive). Matching is by stem.
TAG_AROUSAL = {
    "scream": 1.0, "shout": 0.95, "roar": 1.0, "furious": 0.95, "fury": 0.95, "rage": 1.0,
    "hysteric": 1.0, "maniacal": 1.0, "agoniz": 1.0, "shriek": 1.0, "thunder": 0.9, "booming": 0.85,
    "explod": 1.0, "frantic": 0.9, "panic": 0.9, "terrified": 0.9, "horrified": 0.9, "sob": 0.85,
    "outrag": 0.9, "enraged": 1.0, "crying out": 0.9, "yell": 0.95, "violent": 0.95, "gasping": 0.8,
    "desperate": 0.8, "pleading": 0.75, "begging": 0.8, "weeping": 0.75, "tearful": 0.65,
    "shocked": 0.8, "stunned": 0.75, "incredulous": 0.7, "accus": 0.75, "venom": 0.75,
    "threaten": 0.8, "menac": 0.8, "deadly": 0.8, "lethal": 0.85, "vicious": 0.85, "cruel": 0.7,
    "sinister": 0.7, "chilling": 0.75, "vengeful": 0.8, "vindictive": 0.75, "defiant": 0.7,
    "fierce": 0.75, "urgent": 0.75, "alarmed": 0.75, "breathless": 0.65, "trembling": 0.6,
    "shaking": 0.65, "heartbroken": 0.65, "devastat": 0.75, "betray": 0.75, "anguish": 0.85,
    "triumphant": 0.7, "gloat": 0.65, "mocking": 0.6, "taunt": 0.65, "spite": 0.65, "smug": 0.5,
    "scorn": 0.6, "condemn": 0.7, "demanding": 0.65, "commanding": 0.6, "icy": 0.6, "cold": 0.55,
    "steely": 0.55, "resolute": 0.5, "stern": 0.5, "harsh": 0.6, "sharp": 0.6, "bitter": 0.55,
    "dismissive": 0.45, "arrogant": 0.5, "condescend": 0.5, "authoritative": 0.5, "firm": 0.45,
    "grave": 0.45, "solemn": 0.35, "hesitant": 0.35, "whisper": 0.35, "low": 0.35, "quiet": 0.25,
    "soft": 0.2, "gentle": 0.15, "tender": 0.2, "warm": 0.15, "calm": 0.15, "reassuring": 0.15,
    "reflective": 0.15, "peaceful": 0.1, "amused": 0.3, "sincere": 0.3, "earnest": 0.35,
    "vulnerable": 0.4, "loving": 0.25, "content": 0.1, "relieved": 0.25, "melanchol": 0.25,
    "wail": 0.95, "bark": 0.8, "snarl": 0.85, "unhinged": 0.95, "howl": 0.95, "cry": 0.8,
    "agonized": 1.0, "despair": 0.8, "aghast": 0.8, "seeth": 0.8, "simmer": 0.6,
}

# Hook cues: things that stop a scroll in ~3s.
HOOK_ACTION = re.compile(r"\b(slap\w*|strik\w*|struck|punch\w*|shov\w*|grab\w*|seiz\w*|throw\w*|threw|hurl\w*|"
    r"smash\w*|shatter\w*|explod\w*|explosion|burst\w*|kick\w*|drag\w*|chok\w*|stab\w*|blood\w*|bleed\w*|"
    r"collaps\w*|fall\w*|fell|scream\w*|tear\w* (?:off|open|apart)|rip\w*|burn\w*|fire|flame\w*|"
    r"kneel\w*|knees|chain\w*|shackl\w*|whip\w*|crop|brand\w*|iron|gun|sword|blade|dagger|"
    r"crash\w*|slam\w*|bang\w*|storm\w* in|kiss\w*|embrace\w*|ring|gown|altar|veil|tears? (?:stream|spill))\b", re.I)
HOOK_LINE = re.compile(r"\b(how dare|you (?:are|were) nothing|get out|on your knees|kneel|liar|whore|witch|"
    r"marry(?:ing)? (?:me|her|him)|divorce|betray\w*|pregnant|dead|kill\w*|murder\w*|poison\w*|"
    r"disown\w*|banish\w*|never (?:loved|wanted)|worthless|plain|beggar|cripple\w*|monster|"
    r"the truth|secret\w*|who are you|i am (?:the|his|her)|duke|duchess|my (?:wife|husband)|"
    r"execut\w*|gallows|hang\w*|burn (?:her|you)|arrest\w*|guards?)\b", re.I)

# Cliffhanger cues: the clip should end with something UNRESOLVED.
CLIFF_LINE = re.compile(r"(\?\s*$|\.\.\.\s*$|—\s*$|-\s*$|\b(who|what|where|why|how)\b.*\?|"
    r"\b(unless|or else|before|until|if you|you will|you'll|i will|i'll|we will|tomorrow|tonight|"
    r"never|no one|nothing|everything|the truth|is coming|are coming|it's too late|too late|"
    r"what have you|look at|guards|take her|take him|seize|arrest|execute|gallows|burn|"
    r"choose|last chance|one more|now)\b)", re.I)
CLIFF_ACTION = re.compile(r"\b(door\w* (?:burst|bang|slam|fly|flies|creak|open)\w*|burst\w* (?:in|open|through)|"
    r"freez\w*|halt\w*|stops? (?:mere|inches|short)|raises? (?:the|her|his) (?:hand|iron|crop|sword|blade)|"
    r"draws? (?:a|his|her) (?:sword|blade|dagger|breath)|gasps?|stunned|shock\w*|horror|terror|dread|"
    r"reveal\w*|silhouett\w*|emerg\w*|enters?|appears?|turns? (?:slowly|sharply|around)|drag\w* (?:away|toward|off)|"
    r"realiz\w*|panic\w*|pales?|eyes widen\w*|jaw drops?|grips?|clench\w*)\b", re.I)
RESOLVE = re.compile(r"\b(smil\w*|laugh\w*|embrac\w*|hug\w*|relie\w*|peace\w*|safe|warm\w*|tender\w*|gentl\w*|"
    r"rest\w*|sleep\w*|together|thank\w*|home|happy|content|calm\w*|leans? (?:gently|against)|"
    r"walk\w* away|hand-in-hand)\b", re.I)

# Words that make a clip self-explanatory to a stranger (relationships/roles/premise).
RELATIONAL = re.compile(r"\b(husband|wife|sister|brother|father|mother|son|daughter|fianc\w*|bride|groom|"
    r"wedding|married|marry\w*|duke|duchess|lord|lady|maid|servant|soldier|veteran|family|"
    r"stepmother|cousin|heir\w*|king|queen|prince\w*|widow|orphan|boss|ceo|billionaire)\b", re.I)
DANGLING_START = re.compile(r"^\s*(\.\.\.|and\b|but\b|so\b|then\b|no\.?$|yes\.?$|it\b|that\b|this\b|"
    r"he\b|she\b|they\b|them\b|his\b|her\b|because\b|which\b|or\b)", re.I)

# Strings that only exist because the WRITER annotated the ending. Masked from model
# inputs to prevent label leakage when training on episode endings.
META_LEAK = re.compile(r"\b(cliffhanger|cut\w* (?:sharply )?to black|to black|fade\w*(?:[- ]out)?|"
    r"scene (?:freezes|holds)|holds? (?:on|into)|final(?:e)?|swell\w*|score|orchestral|music|"
    r"camera holds|screen)\b", re.I)


def tag_arousal(tags):
    return _tag_arousal_cached(tuple(tags)) if tags else None


@functools.lru_cache(maxsize=65536)
def _tag_arousal_cached(tags):
    vals = []
    for t in tags:
        t = t.lower()
        best = None
        for stem, v in TAG_AROUSAL.items():
            if stem in t:
                best = v if best is None else max(best, v)
        if best is not None:
            vals.append(best)
    return max(vals) if vals else None


# ---- Tag-free delivery inference ----------------------------------------------------
# When a show's screenplay has no "(Furious, Shouting)" tags, infer how a line is delivered
# from (a) the camera/action text written alongside it and (b) the line's own surface form.
VISUAL_AROUSAL = {
    "vein": 0.9, "bulg": 0.85, "contort": 0.9, "erupt": 0.9, "lunge": 0.9, "recoil": 0.75, "snarl": 0.85,
    "glar": 0.65, "tears": 0.6, "tear-": 0.6, "trembl": 0.6, "shak": 0.6, "pale": 0.7, "wide-eyed": 0.75,
    "eyes widen": 0.75, "eyes snap": 0.8, "jaw clench": 0.7, "clench": 0.6, "fist": 0.65, "storm": 0.75,
    "collaps": 0.85, "smirk": 0.5, "sneer": 0.55, "wild": 0.75, "frenzy": 0.95, "hyperventilat": 0.9,
    "pound": 0.75, "slam": 0.85, "seiz": 0.8, "yank": 0.85, "shove": 0.85, "grab": 0.75, "point": 0.5,
    "towering": 0.5, "menac": 0.8, "murderous": 0.95, "wrath": 0.95, "agony": 0.95, "horror": 0.85,
    "shock": 0.75, "devastat": 0.75, "weep": 0.75, "cries out": 0.9, "crying": 0.75,
}
SHOUT_RX = re.compile(r"\b[A-Z]{3,}\b")


def text_arousal(text):
    """Arousal implied by the line itself: punctuation, shouting caps, shock vocabulary."""
    t = text.strip(); v = 0.0
    if "!" in t:
        v = max(v, 0.7)
    if "?!" in t or "!!" in t:
        v = max(v, 0.85)
    if SHOUT_RX.search(t):
        v = max(v, 0.85)
    if HOOK_LINE.search(t):
        v = max(v, 0.7)
    return v


def visual_arousal(text):
    t = text.lower(); best = 0.0
    for table in (TAG_AROUSAL, VISUAL_AROUSAL):
        for stem, v in table.items():
            if stem in t and v > best:
                best = v
    return best
