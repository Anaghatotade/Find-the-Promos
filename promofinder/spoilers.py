"""Spoiler-aware scoring: does a clip give away a plot twist or the ending?

Position alone (the old "late episode" prior) is a weak proxy: episode 40 can be harmless and episode 12
can unmask the villain. This module looks at *content*:

1. Reveal cues (show-agnostic). Dialogue/action that states hidden information: identity ("I am your
   son", "the rightful heir"), culpability ("the Voss brothers paid us", "it was you"), life/death ("she's
   alive"), hidden crimes ("poisoned", "framed"), confessions and exposure; plus resolution cues
   (arrests, "it's over", sentences carried out) in the final stretch of the series.
2. The writers' own summary. Kuku screenplays carry an EPISODE LOGLINE. When it uses a reveal verb
   ("unmasks", "discovers", "confesses", "exposes"...), the episode holds a major turn, and the lines
   most similar to that clause are boosted. When there is no logline, only the cues are used.
3. Premise exemption. A reveal the TITLE already promises is not a spoiler but the promise being paid off
   ("The Maid Who Married a Billionaire" -> showing the billionaire reveal is the point of the ad). Lines
   whose reveal content is covered by the title / first-episode logline are marked "premise payoff".
4. Free-episode exemption. Anything in the first episodes (default 3) is what a new viewer sees first.

Output per candidate: spoiler_risk in [0, 1] with the line that triggered it, used as a multiplicative
penalty whose strength is the user's spoiler tolerance (strict / balanced / off).
"""
from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

REVEAL_LINE = [
    # (pattern, strength, kind)
    (r"\b(?:i am|i'm|you are|you're|he is|he's|she is|she's|he was|she was|it was|they are)\s+(?:the|your|my|his|her|their)\s+"
     r"(?:real|true|rightful|long-lost|lost|secret|biological)?\s*(?:son|daughter|father|mother|brother|sister|heir\w*|wife|husband|"
     r"duke|duchess|king|queen|prince\w*|lord|owner|ceo|boss|killer|murderer|traitor|spy|twin)\b", 0.9, "identity"),
    (r"\b(?:real|true)\s+(?:name|identity|father|mother|heir|parents?)\b", 0.8, "identity"),
    (r"\brightful\s+\w+", 0.75, "identity"),
    (r"\b(?:paid|hired|sent|ordered|bribed)\s+(?:us|them|me|him|her|those men)\b", 0.85, "culprit"),
    (r"\bit (?:was|is) (?:you|him|her|them)\b", 0.75, "culprit"),
    (r"\b(?:behind|responsible for) (?:this|it all|everything|the (?:fire|attack|poison\w*|accident))\b", 0.8, "culprit"),
    (r"\b(?:poison\w*|arsenic|framed|frame (?:her|him|you)|forged|faked (?:his|her) death)\b", 0.7, "secret"),
    (r"\b(?:is|was|are|still|been) alive\b|\bnot dead\b|\bsurvived\b", 0.8, "alive"),
    (r"\b(?:confess\w*|the truth is|i lied|admit it|you lied)\b", 0.55, "confession"),
    (r"\b(?:pregnant|carrying (?:his|your|my) child)\b", 0.75, "secret"),
    (r"\b(?:treason|evidence|documents?|proof)\b", 0.45, "exposure"),
]
REVEAL_ACTION = [
    (r"\b(?:unmask\w*|recogni[sz]\w*|realiz\w*|realis\w*|revealing|reveals?|is revealed|exposes?|exposed)\b", 0.6, "reveal"),
    (r"\b(?:removes|pulls (?:off|back)|lowers) (?:his|her|the) (?:mask|hood|veil|disguise)\b", 0.8, "identity"),
    (r"\b(?:crest|seal|signet|birthmark|locket|portrait)\b", 0.35, "identity"),
    (r"\b(?:walks in on|witness\w*|catches (?:them|her|him))\b", 0.6, "secret"),
]
RESOLUTION = [
    (r"\b(?:arrest (?:him|her|them)|take (?:him|her|them) away|(?:you are|you're|you’re|is|are) (?:now )?under arrest|seize (?:him|her|them)|apprehend\w*)\b", 0.75),
    (r"\b(?:it[’']?s over|it is over|you lost|you've lost|game is over|justice (?:is|has been) (?:served|done))\b", 0.7),
    (r"\b(?:sentenced to|hereby (?:sentence|banish|strip)|stripped of (?:his|her) title)\b", 0.7),
    (r"\b(?:handcuff\w*|led away in chains|dragged away by (?:the )?guards)\b", 0.6),
]
LOGLINE_REVEAL_VERBS = re.compile(r"\b(unmask\w*|expos\w*|reveal\w*|discover\w*|uncover\w*|learn\w*|realiz\w*|realis\w*|"
                                  r"recogni\w*|confess\w*|proclaim\w*|witness\w*|finds? (?:out|proof)|truth|identity|"
                                  r"apprehend\w*|arrest\w*|reunit\w*|presumed[- ]dead|framed|poison\w*)\b", re.I)

ROLE_PHRASE = re.compile(r"\b(?:my|your|his|her|their|the)\s+(?:son|daughter|father|mother|brother|sister|wife|husband|"
                         r"heir\w*|duke|duchess|king|queen|prince\w*|ceo|boss|twin)\b")
_ROLE_NORM = {"wife": "spouse", "husband": "spouse"}


def _roles(text: str) -> set:
    """Role nouns used possessively ('my father', 'his wife'), normalised (wife/husband -> spouse)."""
    return {_ROLE_NORM.get(m.split()[-1], re.sub(r"(es|s)$", "", m.split()[-1])) for m in ROLE_PHRASE.findall(text.lower())}


_RL = [(re.compile(p, re.I), s, k) for p, s, k in REVEAL_LINE]
_RA = [(re.compile(p, re.I), s, k) for p, s, k in REVEAL_ACTION]
_RS = [(re.compile(p, re.I), s) for p, s in RESOLUTION]
STOP = set(ENGLISH_STOP_WORDS) | {"lady", "lord", "sir", "said", "will", "just", "know", "like", "yes", "come", "look"}
TOK = re.compile(r"[a-z][a-z']{2,}")


def _content(text: str) -> set:
    return {t.strip("'") for t in TOK.findall(text.lower())} - STOP


@dataclass
class RevealEvent:
    episode: int
    t: float
    end: float
    strength: float
    kind: str           # identity | culprit | secret | alive | confession | exposure | reveal | resolution
    text: str
    logline_match: float = 0.0
    premise: bool = False     # the title/premise promises this reveal: not a spoiler

    @property
    def severity(self) -> float:
        if self.premise:
            return 0.0
        return min(1.0, 0.6 * self.strength + 0.6 * self.logline_match)


class RevealIndex:
    def __init__(self, show: str, episodes, free_episodes: int = 3, use_loglines: bool = True):
        self.free = free_episodes
        eps = sorted(episodes, key=lambda e: e.number)
        self.n_max = max((e.number for e in eps), default=1)
        first = eps[0] if eps else None
        # premise vocabulary: title + first-episode logline (what the ad and episode 1 already promise)
        prem_text = show.replace(".", " ") + " " + (first.logline if first is not None and first.number == 1 else "")
        self.premise_terms = _content(prem_text)
        self.title_terms = _content(show.replace(".", " "))
        # What a promo viewer already knows: relationships/roles stated in the free episodes or in the premise.
        # A cue that only restates them ("You are my father!" in ep 5) is not a reveal.
        known_txt = prem_text + " " + " ".join(b.text for e in eps if e.number <= self.free for b in e.blocks if b.kind == "dialogue")
        self.known_roles = _roles(known_txt)
        if re.search(r"\b(marri\w*|wed\w*|bride|groom)\b", prem_text, re.I):
            self.known_roles.add("spouse")        # a title about a marriage already tells the viewer who is married
        self.events: List[RevealEvent] = []
        self.by_ep: Dict[int, List[RevealEvent]] = {}
        for e in eps:
            if e.number <= self.free:
                continue
            log_terms = _content(" ".join(m.group(0) + " " + e.logline[m.end():m.end() + 120]
                                          for m in LOGLINE_REVEAL_VERBS.finditer(e.logline))) if (use_loglines and e.logline) else set()
            late = (e.number - 1) / max(self.n_max - 1, 1) >= 0.75
            for b in e.blocks:
                if b.kind not in ("dialogue", "action"):
                    continue
                strength, kind, span = 0.0, "", ""
                for rx, s, k in (_RL if b.kind == "dialogue" else _RA):
                    m = rx.search(b.text) if s > strength else None
                    if m:
                        strength, kind, span = s, k, b.text[max(0, m.start() - 30):m.end() + 30]
                if late:
                    for rx, s in _RS:
                        m = rx.search(b.text) if s > strength else None
                        if m:
                            strength, kind, span = s, "resolution", m.group(0)
                if strength <= 0:
                    continue
                if kind == "identity":
                    roles = _roles(span)
                    if roles and roles <= self.known_roles:
                        strength *= 0.35          # restates a relationship the viewer already knows
                ct = _content(b.text)
                lm = 0.0
                if log_terms and ct:
                    lm = min(1.0, len(ct & log_terms) / 3.0)      # 3+ shared content words with the logline's reveal clause
                # premise payoff: the reveal's content is what the title promises (e.g. "billionaire" in "The Maid Who Married a Billionaire")
                # (only the words around the matched cue count, and only role words: "married" in a title must not
                # exempt every line that mentions a marriage)
                st = _content(span) - {"married", "marry", "wife", "husband", "love"}
                prem = bool(st & self.title_terms) and kind in ("identity", "reveal")
                ev = RevealEvent(e.number, b.start, b.end, strength, kind, b.text, lm, prem)
                self.events.append(ev)
                self.by_ep.setdefault(e.number, []).append(ev)

    def clip_risk(self, segments) -> Tuple[float, Optional[RevealEvent], List[RevealEvent]]:
        """Highest reveal severity inside the clip, the event behind it, and any premise payoffs shown."""
        best, ev, prem = 0.0, None, []
        for sg in segments:
            for x in self.by_ep.get(sg.episode, ()):
                if sg.start - 0.05 <= x.t < sg.end:
                    if x.premise:
                        prem.append(x)
                    elif x.severity > best:
                        best, ev = x.severity, x
        return best, ev, prem

    def summary(self, top=12) -> List[Dict]:
        ev = sorted((x for x in self.events if not x.premise), key=lambda x: -x.severity)[:top]
        return [{"episode": x.episode, "t": round(x.t, 2), "kind": x.kind, "severity": round(x.severity, 2),
                 "logline_match": round(x.logline_match, 2), "text": x.text[:140]} for x in ev]


TOLERANCE = {"strict": 0.6, "balanced": 0.35, "off": 0.0}


def spoiler_penalty(risk: float, tolerance: str) -> float:
    """Multiplicative factor on the clip score. Only clear reveals bite: risk below 0.3 is ignored."""
    w = TOLERANCE.get(tolerance, TOLERANCE["balanced"])
    return 1.0 - w * max(0.0, (risk - 0.3) / 0.7)
