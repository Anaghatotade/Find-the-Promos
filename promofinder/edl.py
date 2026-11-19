"""Cut lists editors can import: one CMX3600 EDL per promo + a flat NLE cut-list CSV.

Assumption (stated in every file): each episode's video starts at 00:00:00:00 and the
screenplay timestamps are the video timestamps (true for this time-coded production
format). Reel = episode (E001...); relink reels to the episode video files in the NLE.
CMX3600 imports into Premiere Pro, DaVinci Resolve and Final Cut (via converters);
CapCut has no EDL import, so the CSV gives frame-accurate in/out points to type in.
"""
from __future__ import annotations
import csv, os, re
from typing import List, Dict


import unicodedata

ASCII_MAP = {"“": '"', "”": '"', "‘": "'", "’": "'", "→": "->", "…": "...", "–": "-", "—": "-"}


def ascii_safe(t: str) -> str:
    """CMX3600 importers expect plain ASCII; keep comments readable but safe."""
    for a, b in ASCII_MAP.items():
        t = t.replace(a, b)
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()


def tc(seconds: float, fps: int) -> str:
    f = int(round(seconds * fps))
    h, r = divmod(f, 3600 * fps); m, r = divmod(r, 60 * fps); s, fr = divmod(r, fps)
    return f"{h:02d}:{m:02d}:{s:02d}:{fr:02d}"


def promo_edl(p: Dict, show: str, fps: int = 30, record_start: float = 3600.0) -> str:
    L = [f"TITLE: {show[:60]} - promo {p['rank']:02d}", "FCM: NON-DROP FRAME", ""]
    rec = record_start
    for i, s in enumerate(p["segments"], 1):
        reel = f"E{s['episode']:03d}"
        src_in, src_out = s["start_s"], s["end_s"]
        dur = round((src_out - src_in) * fps) / fps
        L.append(f"{i:03d}  {reel:<8} V     C        {tc(src_in, fps)} {tc(src_in + dur, fps)} {tc(rec, fps)} {tc(rec + dur, fps)}")
        L.append(f"* FROM CLIP NAME: {reel}  (script: {s['src_file']}, lines {s['src_lines'][0]}-{s['src_lines'][1]})")
        if i == 1:
            L.append(f"* HOOK: {p['hook']['text'][:120]}")
        if i == len(p["segments"]):
            L.append(f"* CLIFFHANGER: {p['cliffhanger']['text'][:120]}")
        L.append("")
        rec += dur
    L.append("* ASSUMES EPISODE VIDEO STARTS AT 00:00:00:00 AND MATCHES SCRIPT TIMESTAMPS")
    return ascii_safe("\n".join(L)) + "\n"


def write_cutlists(promos: List[Dict], show: str, out_dir: str, fps: int = 30):
    d = os.path.join(out_dir, "edl"); os.makedirs(d, exist_ok=True)
    for p in promos:
        with open(os.path.join(d, f"promo_{p['rank']:02d}.edl"), "w", encoding="utf-8") as fh:
            fh.write(promo_edl(p, show, fps))
    with open(os.path.join(out_dir, "cutlist_nle.csv"), "w", newline="", encoding="utf-8-sig") as fh:
        w = csv.writer(fh)
        w.writerow(["promo_rank", "segment", "reel", "episode", f"src_in_tc@{fps}fps", f"src_out_tc@{fps}fps",
                    "src_in_s", "src_out_s", "duration_frames", "script_file", "script_lines"])
        for p in promos:
            for i, s in enumerate(p["segments"], 1):
                w.writerow([p["rank"], i, f"E{s['episode']:03d}", s["episode"], tc(s["start_s"], fps), tc(s["end_s"], fps),
                            s["start_s"], s["end_s"], round((s["end_s"] - s["start_s"]) * fps), s["src_file"],
                            f"{s['src_lines'][0]}-{s['src_lines'][1]}"])


EVENT = re.compile(r"^(\d{3})\s+(\S+)\s+V\s+C\s+(\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d) (\d\d:\d\d:\d\d:\d\d)$")


def parse_edl(text: str, fps: int = 30):
    """Minimal CMX3600 reader used to verify our own output round-trips."""
    def sec(t):
        h, m, s, f = map(int, t.split(":")); return h * 3600 + m * 60 + s + f / fps
    ev = []
    for line in text.splitlines():
        m = EVENT.match(line)
        if m:
            ev.append({"event": int(m.group(1)), "reel": m.group(2), "src_in": sec(m.group(3)), "src_out": sec(m.group(4)),
                       "rec_in": sec(m.group(5)), "rec_out": sec(m.group(6))})
    return ev
