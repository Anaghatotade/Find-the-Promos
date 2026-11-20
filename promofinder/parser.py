"""Parse Kuku-style timestamped screenplays into a flat, typed block table.

Every block keeps its exact source (file, line number, raw header) so any promo
can be traced back to the screenplay text it came from.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field, asdict
from typing import List, Optional

TS = r"\(?\s*(\d+):(\d+(?:\.\d+)?)\s*\)?"
RE_TIMING = re.compile(r"^\s*start\s*:\s*" + TS + r"\s*\|\s*end\s*:\s*" + TS, re.I)
RE_HEADER = re.compile(r"^\s*\*\*(.+?):?\*\*\s*:?\s*$")
RE_SCENE = re.compile(r"^\s*SCENE\s+(\d+)\s*$", re.I)
RE_SCENE_HEADING = re.compile(r"^\s*scene heading\s*:\s*(.*)$", re.I)
RE_META = {
    "episode": re.compile(r"^\s*EPISODE NUMBER\s*:\s*(.*)$", re.I),
    "logline": re.compile(r"^\s*EPISODE LOGLINE\s*:\s*(.*)$", re.I),
    "continuity": re.compile(r"^\s*CONTINUITY NOTES\s*:\s*(.*)$", re.I),
}
NON_DIALOGUE = {"CAMERA": "camera", "ACTION": "action", "SOUND FX": "sfx", "SFX": "sfx",
                "SOUND": "sfx", "MUSIC": "sfx", "TEXT": "text", "TEXT ON SCREEN": "text",
                "INSERT": "camera", "TITLE": "text", "SUPER": "text"}


HONORIFICS = re.compile(r"^(?:(?:THE|LADY|LORD|SIR|DAME|MR|MRS|MS|MISS|DR|DOCTOR|KING|QUEEN|PRINCE|PRINCESS|DUKE|DUCHESS|"
                        r"CAPTAIN|DETECTIVE|SHERIFF|OFFICER|MASTER|MISTRESS|MADAM|YOUNG|OLD)\.?\s+)+", re.I)


def canon_speaker(name: str) -> str:
    """'LADY MARA' and 'MARA' are the same person: drop leading honorifics for identity checks."""
    n = (name or "").strip().upper()
    c = HONORIFICS.sub("", n).strip()
    return c or n


def ts(m: str, s: str) -> float:
    return int(m) * 60 + float(s)


def fmt_ts(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


@dataclass
class Block:
    episode: int
    idx: int                 # order within episode
    kind: str                # dialogue | camera | action | sfx | text
    start: float
    end: float
    text: str
    speaker: str = ""
    tags: List[str] = field(default_factory=list)   # delivery/emotion tags
    offscreen: bool = False
    voiceover: bool = False
    scene: int = 0
    scene_heading: str = ""
    src_file: str = ""
    src_line: int = 0
    raw_header: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass
class Episode:
    number: int
    title: str
    logline: str
    continuity: str
    blocks: List[Block]
    src_file: str
    duration: float
    warnings: List[str] = field(default_factory=list)


def _split_header(h: str):
    """'MATRIARCH (O.S.) (Cold, Commanding)' -> ('MATRIARCH', [tags], os, vo)."""
    groups = re.findall(r"\(([^)]*)\)", h)
    name = re.sub(r"\([^)]*\)", "", h).strip().rstrip(":").strip()
    tags, os_, vo = [], False, False
    for g in groups:
        for t in re.split(r"[,;/]", g):
            t = t.strip().lower()
            if not t:
                continue
            if t in ("o.s.", "os", "o.c.", "off-screen", "offscreen"):
                os_ = True
            elif t in ("v.o.", "vo", "voice-over", "voiceover"):
                vo = True
            else:
                tags.append(t)
    return name, tags, os_, vo


def _episode_number(label: str, fname: str) -> int:
    for s in (label, fname):
        m = re.search(r"episode[\s_-]*0*(\d+)", s or "", re.I)
        if m:
            return int(m.group(1))
    m = re.search(r"(\d+)", fname or "")
    return int(m.group(1)) if m else 0


def parse_screenplay(text: str, src_file: str = "") -> Episode:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta = {k: "" for k in RE_META}
    blocks: List[Block] = []
    warnings: List[str] = []
    scene, heading = 0, ""
    i, n = 0, len(lines)
    ep_no = None
    while i < n:
        line = lines[i]
        for k, rx in RE_META.items():
            m = rx.match(line)
            if m and not meta[k]:
                meta[k] = m.group(1).strip()
        m = RE_SCENE.match(line)
        if m:
            scene = int(m.group(1)); i += 1; continue
        m = RE_SCENE_HEADING.match(line)
        if m:
            heading = m.group(1).strip(); i += 1; continue
        m = RE_HEADER.match(line)
        if m and i + 1 < n:
            # timing line is normally next; tolerate one blank line
            j = i + 1
            while j < n and not lines[j].strip() and j < i + 3:
                j += 1
            tm = RE_TIMING.match(lines[j]) if j < n else None
            if not tm:
                warnings.append(f"line {i+1}: header without timing: {line.strip()[:60]}")
                i += 1; continue
            if ep_no is None:
                ep_no = _episode_number(meta["episode"], src_file)
            start, end = ts(tm.group(1), tm.group(2)), ts(tm.group(3), tm.group(4))
            k = j + 1; body = []
            while k < n and lines[k].strip() and not RE_HEADER.match(lines[k]) \
                    and not RE_SCENE.match(lines[k]) and not lines[k].startswith("---"):
                body.append(lines[k].strip()); k += 1
            raw = m.group(1).strip()
            name, tags, os_, vo = _split_header(raw)
            kind = NON_DIALOGUE.get(name.upper())
            txt = " ".join(body).strip()
            if kind is None:
                kind = "dialogue"
                txt = txt.strip().strip('"').strip("“”").strip()
            if end < start:
                warnings.append(f"line {i+1}: end<start, swapped"); start, end = end, start
            blocks.append(Block(episode=ep_no, idx=len(blocks), kind=kind, start=start, end=end,
                                text=txt, speaker=name if kind == "dialogue" else "",
                                tags=tags if kind == "dialogue" else [], offscreen=os_,
                                voiceover=vo, scene=scene, scene_heading=heading,
                                src_file=src_file, src_line=i + 1, raw_header=raw))
            i = k; continue
        i += 1
    if ep_no is None:
        ep_no = _episode_number(meta["episode"], src_file)
    blocks.sort(key=lambda b: (b.start, b.idx))
    for k, b in enumerate(blocks):
        b.idx = k
    dur = max((b.end for b in blocks), default=0.0)
    if not blocks:
        warnings.append("no timestamped blocks found")
    return Episode(number=ep_no, title=meta["episode"] or f"Episode {ep_no}",
                   logline=meta["logline"], continuity=meta["continuity"],
                   blocks=blocks, src_file=src_file, duration=dur, warnings=warnings)
