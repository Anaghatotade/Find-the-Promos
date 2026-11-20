"""Convert a parsed show into other formats, for format-robustness testing."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from promofinder.ingest import load_inputs
from promofinder.formats import episode_to_json

def hms(t, comma=False):
    h, r = divmod(t, 3600); m, s = divmod(r, 60)
    x = f"{int(h):02d}:{int(m):02d}:{s:06.3f}"
    return x.replace(".", ",") if comma else x

def mmss(t):
    m, s = divmod(t, 60); return f"{int(m):02d}:{s:05.2f}"

src, out = sys.argv[1], sys.argv[2]
show, eps = load_inputs([src])
for fmt in ("json", "inline", "inline_notags", "srt", "loose"):
    d = os.path.join(out, fmt, show); os.makedirs(d, exist_ok=True)
    for e in eps:
        n = f"episode-{e.number:03d}"
        if fmt == "json":
            open(os.path.join(d, n + ".json"), "w").write(json.dumps(episode_to_json(e)))
        elif fmt.startswith("inline"):
            L = [f"EPISODE NUMBER: Episode {e.number}", f"EPISODE LOGLINE: {e.logline}", ""]; sc = None
            for b in e.blocks:
                if b.scene != sc:
                    sc = b.scene; L.append(f"SCENE {sc:02d}")
                who = {"camera": "CAMERA", "action": "ACTION", "sfx": "SOUND FX", "text": "TEXT"}.get(b.kind, b.speaker)
                if b.kind == "dialogue" and b.tags and fmt == "inline":
                    who += f" ({', '.join(b.tags)})"
                L.append(f"[{mmss(b.start)} - {mmss(b.end)}] {who}: {b.text}")
            open(os.path.join(d, n + ".txt"), "w").write("\n".join(L))
        elif fmt == "srt":   # dialogue + sound only, no tags, no camera/action: the lossy case
            L, k = [], 1
            for b in e.blocks:
                if b.kind == "dialogue":
                    txt = f"{b.speaker}: {b.text}"
                elif b.kind == "sfx":
                    txt = f"[SFX {b.text}]"
                else:
                    continue
                L += [str(k), f"{hms(b.start, True)} --> {hms(b.end, True)}", txt, ""]; k += 1
            open(os.path.join(d, n + ".srt"), "w").write("\n".join(L))
        elif fmt == "loose":  # production layout without ** bold, timing on the header line
            L = [f"EPISODE NUMBER: Episode {e.number}", f"EPISODE LOGLINE: {e.logline}", ""]; sc = None
            for b in e.blocks:
                if b.scene != sc:
                    sc = b.scene; L += [f"SCENE {sc:02d}", ""]
                who = {"camera": "CAMERA", "action": "ACTION", "sfx": "SOUND FX", "text": "TEXT"}.get(b.kind, b.speaker)
                if b.kind == "dialogue" and b.tags:
                    who += f" ({', '.join(b.tags)})"
                L += [f"{who}: [{mmss(b.start)} --> {mmss(b.end)}]", b.text, ""]
            open(os.path.join(d, n + ".txt"), "w").write("\n".join(L))
print(show, len(eps))
