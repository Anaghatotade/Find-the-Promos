"""Moment- and window-level features computed directly from timestamped blocks."""
from __future__ import annotations
import functools
import re
from bisect import bisect_left
import numpy as np
from typing import List, Dict
from .parser import Block, Episode, canon_speaker
from . import lexicons as L

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _VADER = SentimentIntensityAnalyzer()
except Exception:  # optional dependency
    _VADER = None

# arousal source: "tags" (delivery tags only) | "fallback" (tags, else inferred) | "max" (max of both)
AROUSAL_MODE = "tags"


def set_arousal_mode(mode: str):
    global AROUSAL_MODE
    assert mode in ("tags", "fallback", "max"), mode
    AROUSAL_MODE = mode


def inferred_arousal(ep: Episode, b: Block) -> float:
    ctx = " ".join(x.text for x in overlapping(ep.blocks, b.start - 0.5, b.end + 0.3, {"camera", "action"}))
    return max(L.visual_arousal(ctx), L.text_arousal(b.text))


def line_arousal(ep: Episode, b: Block):
    """Per-line value, cached on the block (it is requested once per window containing the line)."""
    cache = b.__dict__.setdefault("_arousal_cache", {})
    if AROUSAL_MODE not in cache:
        cache[AROUSAL_MODE] = _line_arousal(ep, b)
    return cache[AROUSAL_MODE]


def _line_arousal(ep: Episode, b: Block):
    tag = L.tag_arousal(b.tags)
    if AROUSAL_MODE == "tags":
        return tag
    inf = inferred_arousal(ep, b)
    if AROUSAL_MODE == "fallback":
        return tag if tag is not None else inf
    return max(tag or 0.0, inf)


HOOK_SPAN = 3.5     # brief: "something in the first 3 seconds"
CLIFF_SPAN = 6.0    # last beat(s) before the cut


def vader(text: str) -> float:
    if not _VADER or not text:
        return 0.0
    return _vader_cached(text)


@functools.lru_cache(maxsize=65536)
def _vader_cached(text: str) -> float:
    """VADER is a pure function of the text; overlapping moments repeat the same text ~3x."""
    return _VADER.polarity_scores(text)["compound"]


_OV_INDEX: dict = {}


def _ov_index(blocks: List[Block]):
    """(starts, max_duration, sorted?) for a block list; lists are cached by identity."""
    ent = _OV_INDEX.get(id(blocks))
    if ent is not None and ent[0] is blocks and ent[1] == len(blocks):
        return ent[2]
    starts = [b.start for b in blocks]
    ok = all(a <= c for a, c in zip(starts, starts[1:]))
    idx = (starts, max((b.end - b.start for b in blocks), default=0.0), ok)
    if len(_OV_INDEX) > 4096:
        _OV_INDEX.clear()
    _OV_INDEX[id(blocks)] = (blocks, len(blocks), idx)
    return idx


def overlapping(blocks: List[Block], t0: float, t1: float, kinds=None) -> List[Block]:
    """Blocks intersecting (t0, t1), in original order. Uses binary search on start times
    (blocks are sorted by start); exactly the same result as a full linear scan."""
    starts, maxdur, ok = _ov_index(blocks)
    if not ok:
        return [b for b in blocks if b.end > t0 + 1e-6 and b.start < t1 - 1e-6 and (kinds is None or b.kind in kinds)]
    lo = bisect_left(starts, t0 - maxdur - 1.0)        # safe lower bound: nothing earlier can reach t0
    hi = bisect_left(starts, t1 - 1e-6)
    return [b for b in blocks[lo:hi] if b.end > t0 + 1e-6 and (kinds is None or b.kind in kinds)]


def masked(text: str) -> str:
    return L.META_LEAK.sub(" ", text)


def moment_text(bs: List[Block], mask=True) -> str:
    parts = []
    for b in bs:
        if b.kind == "dialogue":
            tag = masked(" ".join(b.tags[:2])) if mask else " ".join(b.tags[:2])
            parts.append(f"{b.text} __tag_{'_'.join(tag.split())}")
        elif b.kind in ("action",):
            parts.append(masked(b.text) if mask else b.text)
    return " ".join(parts)


def hook_features(ep: Episode, s: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, s, s + HOOK_SPAN)
    dia = [b for b in bs if b.kind == "dialogue"]
    act = [b for b in bs if b.kind == "action"]
    cam = [b for b in bs if b.kind == "camera"]
    dtext = " ".join(b.text for b in dia)
    atext = " ".join(b.text for b in act + cam)
    ar = [line_arousal(ep, b) for b in dia]
    ar = [a for a in ar if a is not None]
    first_line = dia[0].text if dia else ""
    prev = [b for b in ep.blocks if b.kind == "dialogue" and b.end <= s + 0.05]
    prev_gap = min(s - prev[-1].end, 5.0) if prev else 5.0
    same_spk = bool(prev and dia and canon_speaker(prev[-1].speaker) == canon_speaker(dia[0].speaker) and prev_gap < 1.5)
    est = any(re.search(r"\b(wide|establishing|exterior|aerial|panning shot across)\b", b.text, re.I) for b in cam)
    return {
        "h_has_dialogue": float(bool(dia)),
        "h_first_line_at": (dia[0].start - s) if dia else HOOK_SPAN,
        "h_action_lex": float(len(L.HOOK_ACTION.findall(atext))),
        "h_line_lex": float(len(L.HOOK_LINE.findall(dtext))),
        "h_arousal_max": max(ar) if ar else 0.0,
        "h_excl": float(dtext.count("!")),
        "h_question": float("?" in dtext),
        "h_you": float(bool(re.search(r"\byou\b", dtext, re.I))),
        "h_vader_abs": abs(vader(dtext)),
        "h_establishing": float(est and not dia),
        "h_dangling": float(bool(first_line) and bool(L.DANGLING_START.match(first_line))),
        "h_closeup": float(any(re.search(r"close-up|extreme close", b.text, re.I) for b in cam)),
        "h_empty": float(not dia and not act),
        "h_prev_gap": prev_gap,
        "h_mid_speech": float(same_spk),
        "h_relief": float(vader(dtext) >= 0.5),
    }


def cliff_features(ep: Episode, e: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, e - CLIFF_SPAN, e)
    dia = [b for b in bs if b.kind == "dialogue"]
    act = [b for b in bs if b.kind == "action"]
    last = dia[-1].text if dia else ""
    dtext = " ".join(b.text for b in dia)
    atext = masked(" ".join(b.text for b in act))
    ar = [line_arousal(ep, b) for b in dia]
    ar = [a for a in ar if a is not None]
    after = [b for b in ep.blocks if b.start >= e - 1e-6 and b.kind == "dialogue"][:1]
    gap = (after[0].start - e) if after else 99.0
    return {
        "c_has_dialogue": float(bool(dia)),
        "c_last_q": float(last.rstrip().endswith("?")),
        "c_last_ellipsis": float(last.rstrip().endswith(("...", "…", "—", "-"))),
        "c_last_excl": float(last.rstrip().endswith("!")),
        "c_line_lex": float(len(L.CLIFF_LINE.findall(dtext))),
        "c_action_lex": float(len(L.CLIFF_ACTION.findall(atext))),
        "c_resolve_lex": float(len(L.RESOLVE.findall(atext + " " + dtext))),
        "c_arousal_max": max(ar) if ar else 0.0,
        "c_arousal_last": ar[-1] if ar else 0.0,
        "c_vader": vader(dtext),
        "c_line_len": float(len(last.split())),
        "c_secs_since_line": (e - dia[-1].end) if dia else CLIFF_SPAN,
        "c_answer_gap": min(gap, 10.0),     # an answer arriving right after the cut = less suspense lost
    }


def cliff_text(ep: Episode, e: float) -> str:
    return moment_text(overlapping(ep.blocks, e - CLIFF_SPAN, e), mask=True)


def hook_text(ep: Episode, s: float) -> str:
    bs = overlapping(ep.blocks, s, s + HOOK_SPAN)
    return moment_text(bs, mask=True) + " " + " ".join(b.text for b in bs if b.kind == "camera")


_ADD = np.add.reduce


def _mean(xs) -> float:
    """Bit-identical to float(np.mean(xs)) (same SIMD reduction, then divide by n) without
    np.mean's Python-level wrapper. Note: a plain sum()/len() is NOT identical (verified)."""
    return float(_ADD(np.array(xs, dtype=float)) / len(xs))


def _relational_count(b: Block) -> int:
    """RELATIONAL only has single-token patterns, so counts over ' '.join(lines) == sum of per-line counts."""
    v = b.__dict__.get("_rel_count")
    if v is None:
        v = b.__dict__["_rel_count"] = len(L.RELATIONAL.findall(b.text))
    return v


def window_features(ep: Episode, s: float, e: float) -> Dict[str, float]:
    bs = overlapping(ep.blocks, s, e)
    dia = [b for b in bs if b.kind == "dialogue"]
    dur = e - s
    ar = [(b.start, line_arousal(ep, b)) for b in dia]
    ar = [(t, a) for t, a in ar if a is not None]
    mid = s + dur / 2
    a1 = [a for t, a in ar if t < mid]; a2 = [a for t, a in ar if t >= mid]
    speakers = {canon_speaker(b.speaker) for b in dia if not b.voiceover}
    scenes = {b.scene for b in bs}
    first = dia[0].text if dia else ""
    dia_secs = sum(min(b.end, e) - max(b.start, s) for b in dia)
    return {
        "w_dur": dur,
        "w_n_lines": float(len(dia)),
        "w_dialogue_cov": dia_secs / max(dur, 1e-6),
        "w_n_speakers": float(len(speakers)),
        "w_scene_changes": float(len(scenes) - 1),
        "w_arousal_mean": _mean([a for _, a in ar]) if ar else 0.0,
        "w_arousal_peak": float(max(a for _, a in ar)) if ar else 0.0,
        "w_escalation": (_mean(a2) - _mean(a1)) if a1 and a2 else 0.0,
        "w_relational": float(sum(_relational_count(b) for b in dia)),   # == findall over the joined text
        "w_dangling_open": float(bool(first) and bool(L.DANGLING_START.match(first))),
        "w_conflict": float(any((line_arousal(ep, b) or 0) >= 0.6 for b in dia) and len(speakers) >= 2),
    }
