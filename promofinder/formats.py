"""Screenplay format adapters.

Every adapter turns one file into the same `Episode` / `Block` table the scorer uses, so ranking logic
never sees format differences. `parse_any` sniffs the content (not just the extension) and picks the
adapter that recovers the most well-formed timed blocks.

Supported:
  kuku     - production format: **NAME (Tag):** header, then `Start: (mm:ss.ss) | End: (mm:ss.ss)`, then text.
             Also tolerated: headers without ** bold, timing on the header line, [a - b] / a --> b timings.
  inline   - one block per line: `[00:11.3 - 00:13.1] MARA (Cold): text`, `00:11.3 --> 00:13.1 MARA: text`,
             or start-only `[00:11.3] MARA: text` (end = next start). CAMERA/ACTION/SFX work as speakers.
  srt/vtt  - subtitle files. `NAME: text` / `[NAME] text` give speakers; `(door slams)` / `[SFX ...]` become sound cues.
  json     - {"episode": 1, "title": .., "logline": .., "blocks": [{"start", "end", "kind", "speaker", "text", "tags"}]}
             or a bare list of such blocks. The lossless interchange format (also what AI script generators emit).
"""
from __future__ import annotations
import json, re
from typing import List, Optional, Tuple
from .parser import Block, Episode, parse_screenplay, _split_header, _episode_number, NON_DIALOGUE

# h:mm:ss.sss | mm:ss.ss | ss.ss ; comma or dot decimals (SRT uses a comma)
TSG = r"(\d{1,2}:)?(\d{1,3}):(\d{2}(?:[.,]\d+)?)"
RX_TS = re.compile(TSG)


def to_sec(h: Optional[str], m: str, s: str) -> float:
    return (int(h[:-1]) * 3600 if h else 0) + int(m) * 60 + float(s.replace(",", "."))


def _ts(text: str) -> Optional[float]:
    m = RX_TS.search(text)
    return to_sec(*m.groups()) if m else None


SEP = r"\s*(?:-->|->|–|—|-|to)\s*"
RX_RANGE = re.compile(r"[\[(]?\s*" + TSG + r"\s*[\])]?" + SEP + r"[\[(]?\s*" + TSG + r"\s*[\])]?")
RX_KUKU_TIMING = re.compile(r"start\s*:\s*\(?\s*" + TSG + r"\s*\)?\s*[|,;]?\s*end\s*:\s*\(?\s*" + TSG, re.I)
NAME = r"([A-Z][A-Z0-9 .'’&\-]{0,60}?(?:\s*\([^)]*\))*)"
RX_INLINE = re.compile(r"^\s*(?:" + RX_RANGE.pattern + r"|[\[(]\s*" + TSG + r"\s*[\])]|" + TSG + r")\s*[|:\-–]?\s*"
                       + NAME + r"\s*[:|]\s*(.+)$")
RX_SCENE_SLUG = re.compile(r"^\s*(?:SCENE\s+\d+|INT\.|EXT\.|INT/EXT\.?)", re.I)


def _mk(blocks: List[Block], ep: int, kind_or_name: str, start: float, end: float, text: str, src: str, line: int,
        scene: int, heading: str, raw: str = ""):
    name, tags, os_, vo = _split_header(kind_or_name)
    kind = NON_DIALOGUE.get(name.upper())
    text = text.strip()
    if kind is None:
        kind = "dialogue"
        text = text.strip().strip('"').strip("“”").strip()
    if end < start:
        start, end = end, start
    blocks.append(Block(episode=ep, idx=len(blocks), kind=kind, start=start, end=end, text=text,
                        speaker=name if kind == "dialogue" else "", tags=tags if kind == "dialogue" else [],
                        offscreen=os_, voiceover=vo, scene=scene, scene_heading=heading, src_file=src, src_line=line,
                        raw_header=raw or kind_or_name))


def _finish(blocks: List[Block], ep_no: int, meta: dict, src: str, warnings: List[str], fmt: str) -> Episode:
    blocks.sort(key=lambda b: (b.start, b.idx))
    for k, b in enumerate(blocks):
        b.idx = k; b.episode = ep_no
    if not blocks:
        warnings.append("no timestamped blocks found")
    e = Episode(number=ep_no, title=meta.get("title") or f"Episode {ep_no}", logline=meta.get("logline", ""),
                continuity=meta.get("continuity", ""), blocks=blocks, src_file=src,
                duration=max((b.end for b in blocks), default=0.0), warnings=warnings)
    e.format = fmt
    return e


_META = {"title": re.compile(r"^\s*EPISODE(?: NUMBER| TITLE)?\s*:\s*(.*)$", re.I),
         "logline": re.compile(r"^\s*(?:EPISODE )?LOGLINE\s*:\s*(.*)$", re.I),
         "continuity": re.compile(r"^\s*CONTINUITY NOTES\s*:\s*(.*)$", re.I)}


def _meta(lines) -> dict:
    meta = {}
    for ln in lines[:40]:
        for k, rx in _META.items():
            m = rx.match(ln)
            if m and k not in meta:
                meta[k] = m.group(1).strip()
    return meta


# ------------------------------------------------------------------ kuku (header / timing / body)
RX_LOOSE_HEADER = re.compile(r"^\s*(?:\*\*)?\s*" + NAME + r"\s*(?::\s*\*\*\s*:?|\*\*\s*:?|:)\s*(.*)$")


def parse_kuku_loose(text: str, src: str) -> Episode:
    """The production format with tolerance for missing bold, same-line timings and other timing styles."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta = _meta(lines)
    ep_no = _episode_number(meta.get("title", ""), src)
    blocks: List[Block] = []; warnings: List[str] = []
    scene, heading, i, n = 0, "", 0, len(lines)

    def timing(s):
        m = RX_KUKU_TIMING.search(s) or RX_RANGE.search(s)
        return (to_sec(*m.groups()[0:3]), to_sec(*m.groups()[3:6])) if m else None

    while i < n:
        ln = lines[i]
        if RX_SCENE_SLUG.match(ln):
            mm = re.match(r"^\s*SCENE\s+(\d+)", ln, re.I)
            scene = int(mm.group(1)) if mm else scene + 1
            if not mm:
                heading = ln.strip()
            i += 1; continue
        hm = re.match(r"^\s*scene heading\s*:\s*(.*)$", ln, re.I)
        if hm:
            heading = hm.group(1).strip(); i += 1; continue
        m = RX_LOOSE_HEADER.match(ln)
        if m and ln.strip() and not any(rx.match(ln) for rx in _META.values()) and not re.match(r"^\s*(start|end|scene)\b", ln, re.I):
            rest = m.group(2)
            tm = timing(rest) if rest else None
            j = i
            if tm is None and not rest.strip():
                j = i + 1
                while j < n and not lines[j].strip() and j < i + 3:
                    j += 1
                tm = timing(lines[j]) if j < n and re.match(r"^\s*(start|\[|\(|\d)", lines[j], re.I) else None
            if tm is not None:
                k = j + 1; body = []
                inline_body = RX_KUKU_TIMING.sub("", RX_RANGE.sub("", rest)).strip(" |:") if j == i else ""
                if inline_body:
                    body.append(inline_body)
                while k < n and lines[k].strip() and not lines[k].startswith("---") and not RX_SCENE_SLUG.match(lines[k]):
                    nxt = RX_LOOSE_HEADER.match(lines[k])
                    if nxt and lines[k].strip().startswith("**"):
                        break
                    if nxt and not nxt.group(2).strip() and k + 1 < n and timing(lines[k + 1]):
                        break
                    body.append(lines[k].strip()); k += 1
                _mk(blocks, ep_no, m.group(1).strip(), tm[0], tm[1], " ".join(body), src, i + 1, scene, heading)
                i = k; continue
        i += 1
    return _finish(blocks, ep_no, meta, src, warnings, "kuku-loose")


# ------------------------------------------------------------------ inline (one line per block)
def parse_inline(text: str, src: str) -> Episode:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta = _meta(lines)
    ep_no = _episode_number(meta.get("title", ""), src)
    rows = []; scene, heading = 0, ""
    for i, ln in enumerate(lines):
        if RX_SCENE_SLUG.match(ln):
            mm = re.match(r"^\s*SCENE\s+(\d+)", ln, re.I)
            if mm:
                scene = int(mm.group(1))
            else:
                scene += 1; heading = ln.strip()
            continue
        m = RX_INLINE.match(ln)
        if not m:
            if rows and ln.strip() and not RX_TS.match(ln.strip()):
                rows[-1][3] += " " + ln.strip()          # wrapped continuation line
            continue
        g = m.groups()
        if g[0] is not None or g[1] is not None:           # range
            st, en = to_sec(*g[0:3]), to_sec(*g[3:6])
        elif g[7] is not None:                             # [start]
            st, en = to_sec(*g[6:9]), None
        else:                                              # bare start
            st, en = to_sec(*g[9:12]), None
        rows.append([st, en, g[12].strip(), g[13].strip(), i + 1, scene, heading])
    blocks: List[Block] = []
    starts = sorted({r[0] for r in rows})
    for r in rows:
        st, en = r[0], r[1]
        if en is None:   # start-only: run to the next block start (or +2.5 s at the end)
            later = [s for s in starts if s > st + 1e-6]
            en = later[0] if later else st + 2.5
        _mk(blocks, ep_no, r[2], st, en, r[3], src, r[4], r[5], r[6])
    return _finish(blocks, ep_no, meta, src, [], "inline")


# ------------------------------------------------------------------ subtitles
RX_CUE = re.compile(r"^\s*" + TSG + r"\s*-->\s*" + TSG)
RX_SPK = re.compile(r"^\s*(?:\[([^\]]{1,40})\]|([A-Z][A-Z0-9 .'’\-]{1,40}(?:\s*\([^)]*\))?)\s*:)\s*(.*)$")


def _unwrap(t: str) -> str:
    t = t.strip()
    return t[1:-1].strip() if len(t) > 1 and t[0] + t[-1] in ("[]", "()") else t


def parse_subtitles(text: str, src: str) -> Episode:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ep_no = _episode_number("", src)
    blocks: List[Block] = []; i, n = 0, len(lines)
    last_spk = ""
    while i < n:
        m = RX_CUE.match(lines[i])
        if not m:
            i += 1; continue
        st, en = to_sec(*m.groups()[0:3]), to_sec(*m.groups()[3:6])
        j = i + 1; body = []
        while j < n and lines[j].strip() and not RX_CUE.match(lines[j]):
            body.append(re.sub(r"<[^>]+>", "", lines[j]).strip()); j += 1
        txt = " ".join(body).strip()
        if txt:
            if re.fullmatch(r"[\(\[][^\)\]]*[\)\]]", txt) or re.match(r"^\[(?:SFX|SOUND|MUSIC)\b", txt, re.I):
                _mk(blocks, ep_no, "SOUND FX", st, en, re.sub(r"^(?:SFX|SOUND(?: FX)?|MUSIC)\s*:?\s*", "", _unwrap(txt), flags=re.I),
                    src, i + 1, 0, "")
            elif re.match(r"^\[(?:ACTION|CAMERA)\s*:?", txt, re.I):
                kind = "CAMERA" if txt[1:].upper().startswith("CAMERA") else "ACTION"
                _mk(blocks, ep_no, kind, st, en, re.sub(r"^\[(?:ACTION|CAMERA)\s*:?\s*|\]$", "", txt, flags=re.I), src, i + 1, 0, "")
            else:
                sm = RX_SPK.match(txt)
                if sm:
                    last_spk = (sm.group(1) or sm.group(2)).strip().upper()
                    txt = sm.group(3)
                elif txt.startswith("-"):
                    txt = txt.lstrip("- ")
                _mk(blocks, ep_no, last_spk or "SPEAKER", st, en, txt, src, i + 1, 0, "")
        i = j
    return _finish(blocks, ep_no, {}, src, [], "subtitles")


# ------------------------------------------------------------------ JSON
def parse_json_script(text: str, src: str) -> Episode:
    data = json.loads(text)
    meta = data if isinstance(data, dict) else {}
    rows = meta.get("blocks", data if isinstance(data, list) else [])
    ep_no = int(meta["episode"]) if str(meta.get("episode", "")).isdigit() else _episode_number(str(meta.get("title", "")), src)
    blocks: List[Block] = []
    for k, r in enumerate(rows):
        if not isinstance(r, dict) or "start" not in r:
            continue
        st = r["start"] if isinstance(r["start"], (int, float)) else _ts(str(r["start"]))
        en = r.get("end", st)
        en = en if isinstance(en, (int, float)) else _ts(str(en))
        if st is None or en is None:
            continue
        kind = (r.get("kind") or r.get("type") or "dialogue").lower()
        header = {"camera": "CAMERA", "action": "ACTION", "sfx": "SOUND FX", "sound": "SOUND FX", "text": "TEXT"}.get(kind)
        if header is None:
            tags = r.get("tags") or []
            header = (r.get("speaker") or "SPEAKER") + (f" ({', '.join(tags)})" if tags else "")
        _mk(blocks, ep_no, header, float(st), float(en), str(r.get("text", "")), src, int(r.get("line", k + 1)), int(r.get("scene", 0) or 0),
            str(r.get("scene_heading", "")))
    return _finish(blocks, ep_no, {"title": str(meta.get("title", "")), "logline": str(meta.get("logline", "")),
                                   "continuity": str(meta.get("continuity", ""))}, src, [], "json")


def episode_to_json(ep: Episode) -> dict:
    """Lossless export of a parsed episode (the inverse of parse_json_script)."""
    return {"episode": ep.number, "title": ep.title, "logline": ep.logline, "continuity": ep.continuity,
            "blocks": [{"start": b.start, "end": b.end, "kind": b.kind, "speaker": b.speaker, "tags": b.tags,
                        "text": b.text, "scene": b.scene, "scene_heading": b.scene_heading, "line": b.src_line}
                       for b in ep.blocks]}


# ------------------------------------------------------------------ dispatcher
def _quality(e: Episode) -> Tuple[int, int]:
    """More timed blocks wins; ties broken by the number with dialogue text."""
    return (len(e.blocks), sum(1 for b in e.blocks if b.kind == "dialogue" and b.text))


def parse_any(text: str, src_file: str = "") -> Episode:
    name = src_file.lower()
    if name.endswith(".json") or text.lstrip()[:1] in ("{", "["):
        try:
            return parse_json_script(text, src_file)
        except (ValueError, TypeError, KeyError, AttributeError):
            pass
    if name.endswith((".srt", ".vtt")) or text.lstrip().startswith("WEBVTT") or re.search(r"^\s*\d+\s*\n\s*" + TSG + r"\s*-->", text[:2000], re.M):
        e = parse_subtitles(text, src_file)
        if e.blocks:
            return e
    if RX_KUKU_TIMING.search(text) and re.search(r"^\s*\*\*.+\*\*\s*:?\s*$", text, re.M):
        e = parse_screenplay(text, src_file)     # the strict production parser: byte-identical to v1.3 results
        e.format = "kuku"
        loose = parse_kuku_loose(text, src_file)
        return e if _quality(e) >= _quality(loose) else loose
    best = None
    for fn in (parse_kuku_loose, parse_inline):
        try:
            e = fn(text, src_file)
        except Exception:      # a malformed file must never break the whole upload
            continue
        if best is None or _quality(e) > _quality(best):
            best = e
    if best is None or not best.blocks:
        e = parse_screenplay(text, src_file); e.format = "unknown"
        return e
    return best


SUPPORTED_EXT = (".txt", ".srt", ".vtt", ".json", ".md", ".fountain")
