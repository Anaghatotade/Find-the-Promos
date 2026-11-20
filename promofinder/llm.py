"""Optional, provider-agnostic LLM layer (the core ranker never needs it).

Jobs given to a language model, always on a small shortlist so cost is ~constant per show:
  1. rerank_with_llm   - rubric-score the top-K (hook, cliffhanger, standalone, spoiler, overall) and
                         rank-average with the system score;
  2. pairwise refine   - a bubble pass over the final top-N with *position-swapped* A/B judgments: each pair
                         is asked twice (A,B) and (B,A); only a verdict that survives the swap moves a clip.
                         LLM judges are known to favour whichever answer is shown first (Zheng et al., 2023,
                         "Judging LLM-as-a-Judge"); the swap cancels that bias at 2 calls per pair;
  3. judge_pair        - the same debiased A/B judgment, for evaluation or for feeding the preference learner.

Providers (swap by config or env; no SDK needed - plain HTTPS via the standard library):
  anthropic | openai | gemini | groq | openrouter | ollama | openai_compatible (any base_url) | mock
Keys come ONLY from environment variables or a local .env file (never from config.yaml, never written
to outputs). Every response is cached on disk by (provider, model, prompt), so re-runs cost nothing.
A malformed or failed answer falls back to the system score: the LLM can never break a run.
"""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, threading, time, urllib.request, urllib.error
from typing import Dict, List, Optional

RUBRIC = """You are a senior promo editor for vertical microdramas (ReelShort/DramaBox style).
Rate this candidate clip as a 20-60 s social ad that pulls NEW viewers into the show{audience}.
Judge only from the transcript. Score 1-5 each:
- hook: do the first 3 seconds stop a scrolling viewer (slap, reveal, shocking line)?
- cliffhanger: does it cut at an unresolved moment so the viewer needs to know what happens next?
- standalone: would someone who has never seen the show understand who/what is at stake?
- spoiler_safe: 5 = gives away no twist or ending; 1 = reveals a major twist or how the story ends.
- overall: would you post it?
Return ONLY JSON: {{"hook":n,"cliffhanger":n,"standalone":n,"spoiler_safe":n,"overall":n,"why":"<=20 words","risk":"<=12 words or empty"}}"""

PAIR = """You are a senior promo editor for vertical microdramas. Two candidate 20-60 s promo clips from the
same show are shown as transcripts. Which one would pull more NEW viewers on TikTok/Reels{audience}?
Consider the first 3 seconds (hook), the final moment (cliffhanger), whether a stranger can follow it, and
whether it spoils a twist. Return ONLY JSON: {{"winner":"A" or "B","confidence":1-5,"reason":"<=20 words"}}"""

PRESETS = {
    # provider: (base_url, env var with the key, default model, API style)
    "anthropic": ("https://api.anthropic.com/v1", "ANTHROPIC_API_KEY", "claude-sonnet-4-5", "anthropic"),
    "openai": ("https://api.openai.com/v1", "OPENAI_API_KEY", "gpt-4o-mini", "openai"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY", "gemini-2.5-flash", "openai"),
    "groq": ("https://api.groq.com/openai/v1", "GROQ_API_KEY", "llama-3.3-70b-versatile", "openai"),
    "openrouter": ("https://openrouter.ai/api/v1", "OPENROUTER_API_KEY", "meta-llama/llama-3.3-70b-instruct:free", "openai"),
    "ollama": ("http://localhost:11434/v1", "", "llama3.1", "openai"),
    "openai_compatible": ("", "OPENAI_API_KEY", "", "openai"),
}
KEY_ALIASES = {"ANTHROPIC_API_KEY": ["PROMOFINDER_ANTHROPIC_KEY"], "GEMINI_API_KEY": ["GOOGLE_API_KEY"]}


# ------------------------------------------------------------------ .env (keys stay on this machine)
def load_dotenv(path: Optional[str] = None) -> List[str]:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win. Returns keys loaded."""
    path = path or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    loaded = []
    if not os.path.exists(path):
        return loaded
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            k = k[7:].strip() if k.startswith("export ") else k
            v = v.strip()
            if v[:1] in ('"', "'") and v[1:].find(v[0]) >= 0:
                v = v[1:1 + v[1:].find(v[0])]              # quoted value: keep everything inside the quotes
            else:
                v = v.split(" #", 1)[0].strip()           # unquoted: drop an inline comment
            if k and v and k not in os.environ:
                os.environ[k] = v; loaded.append(k)
    return loaded


def _key(env: str) -> str:
    if not env:
        return ""
    for name in [env] + KEY_ALIASES.get(env, []):
        if os.environ.get(name):
            return os.environ[name]
    return ""


def llm_status(cfg: Dict) -> Dict:
    """What the UI shows: which provider is configured and whether its key is present (never the key)."""
    lc = cfg.get("llm", {}) if "llm" in cfg else cfg
    p = (os.environ.get("PROMOFINDER_LLM_PROVIDER") or lc.get("provider") or "none").lower()
    if p in ("none", ""):
        return {"provider": "none", "ready": False, "model": "", "message": "No LLM configured (optional)."}
    if p == "mock":
        return {"provider": "mock", "ready": True, "model": "mock", "message": "Mock LLM (testing only)."}
    base, env, model, _ = PRESETS.get(p, PRESETS["openai_compatible"])
    model = os.environ.get("PROMOFINDER_LLM_MODEL") or lc.get("model") or model
    ok = p == "ollama" or bool(_key(env))
    return {"provider": p, "model": model, "ready": ok,
            "message": f"{p} · {model}" + ("" if ok else f" - set {env} in .env to enable")}


# ------------------------------------------------------------------ cache
class _Cache:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS r (k TEXT PRIMARY KEY, v TEXT, ts REAL)")
        self.lock = threading.Lock()

    def get(self, k):
        with self.lock:
            row = self.db.execute("SELECT v FROM r WHERE k=?", (k,)).fetchone()
        return row[0] if row else None

    def put(self, k, v):
        with self.lock:
            self.db.execute("INSERT OR REPLACE INTO r VALUES (?,?,?)", (k, v, time.time())); self.db.commit()


# ------------------------------------------------------------------ clients
class LLMClient:
    name = "base"
    model = ""

    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class HTTPClient(LLMClient):
    """Anthropic Messages API or any OpenAI-compatible /chat/completions endpoint, via urllib."""
    def __init__(self, provider: str, model: str = "", base_url: str = "", timeout: float = 60.0, cache_dir: Optional[str] = None):
        base, env, default_model, style = PRESETS.get(provider, PRESETS["openai_compatible"])
        self.name, self.style = provider, style
        self.base = (base_url or os.environ.get("PROMOFINDER_LLM_BASE_URL") or base).rstrip("/")
        self.model = model or os.environ.get("PROMOFINDER_LLM_MODEL") or default_model
        self.key = _key(env)
        if not self.base:
            raise ValueError("openai_compatible provider needs llm.base_url (or PROMOFINDER_LLM_BASE_URL)")
        if env and not self.key and provider != "ollama":
            raise ValueError(f"{provider}: no API key - set {env} in the .env file next to run.sh")
        self.timeout = timeout
        cd = cache_dir or os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".llm_cache")
        self.cache = _Cache(os.path.join(cd, "responses.sqlite"))
        self.calls = 0; self.cache_hits = 0

    def _post(self, url, body, headers):
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json", **headers})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503, 529) and attempt < 2:
                    time.sleep(2 ** attempt * 2); continue
                raise RuntimeError(f"{self.name} HTTP {e.code}: {e.read()[:200]!r}")
        raise RuntimeError(f"{self.name}: no response")

    def complete(self, system, user):
        k = hashlib.sha256(json.dumps([self.name, self.model, system, user]).encode()).hexdigest()
        hit = self.cache.get(k)
        if hit is not None:
            self.cache_hits += 1
            return hit
        self.calls += 1
        if self.style == "anthropic":
            j = self._post(self.base + "/messages", {"model": self.model, "max_tokens": 300, "system": system,
                                                     "messages": [{"role": "user", "content": user}]},
                           {"x-api-key": self.key, "anthropic-version": "2023-06-01"})
            out = "".join(b.get("text", "") for b in j.get("content", []) if b.get("type") == "text")
        else:
            hdr = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            j = self._post(self.base + "/chat/completions", {"model": self.model, "temperature": 0, "max_tokens": 300,
                                                             "messages": [{"role": "system", "content": system},
                                                                          {"role": "user", "content": user}]}, hdr)
            out = (j.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        self.cache.put(k, out)
        return out


class MockClient(LLMClient):
    """Deterministic stand-in used by tests (and to dry-run the plumbing). Has a deliberate position bias
    (prefers A on near-ties) so the swap-debiasing logic is exercised."""
    name = "mock"; model = "mock"

    def __init__(self):
        self.calls = 0; self.cache_hits = 0

    def complete(self, system, user):
        self.calls += 1
        if "winner" in system:
            a, b = user.split("CLIP B:")[0], user.split("CLIP B:")[-1]
            sa, sb = a.count("?") + a.count("!"), b.count("?") + b.count("!")
            return json.dumps({"winner": "A" if sa >= sb - 1 else "B", "confidence": 2, "reason": "mock"})
        n = min(5, 1 + user.count("?") + user.count("!"))
        return json.dumps({"hook": n, "cliffhanger": n, "standalone": 3, "spoiler_safe": 4, "overall": n, "why": "mock", "risk": ""})


def make_client(cfg) -> LLMClient:
    lc = cfg.get("llm", cfg)
    p = (os.environ.get("PROMOFINDER_LLM_PROVIDER") or lc.get("provider") or "none").lower()
    if p == "mock":
        return MockClient()
    if p in PRESETS:
        return HTTPClient(p, lc.get("model", ""), lc.get("base_url", ""))
    raise ValueError(f"unknown LLM provider {p!r} (use one of: {', '.join(PRESETS)}, mock)")


def parse_json(text: str) -> Dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def transcript_text(c, eps, max_lines=40) -> str:
    from .features import overlapping
    from .parser import fmt_ts
    lines = []
    for i, sg in enumerate(c.segments):
        if len(c.segments) > 1:
            lines.append(f"--- segment {i+1}: episode {sg.episode} ---")
        for b in overlapping(eps[sg.episode].blocks, sg.start, sg.end):
            if b.kind == "dialogue":
                lines.append(f"[{fmt_ts(b.start)}] {b.speaker} ({', '.join(b.tags)}): \"{b.text}\"")
            elif b.kind == "action":
                lines.append(f"[{fmt_ts(b.start)}] (action) {b.text}")
    return "\n".join(lines[:max_lines])


def _aud(result) -> str:
    p = result.get("profile")
    return f" in the audience '{p.label}'" if p is not None else ""


def judge_pair(client: LLMClient, text_a: str, text_b: str, audience: str = "") -> Dict:
    """Position-swapped A/B: returns {'winner': 'A'|'B'|'tie', 'consistent': bool, 'reasons': [...]}."""
    sysm = PAIR.format(audience=audience)
    j1 = parse_json(client.complete(sysm, f"CLIP A:\n{text_a}\n\nCLIP B:\n{text_b}"))
    j2 = parse_json(client.complete(sysm, f"CLIP A:\n{text_b}\n\nCLIP B:\n{text_a}"))
    w1 = j1.get("winner"); w2 = {"A": "B", "B": "A"}.get(j2.get("winner"))
    if w1 in ("A", "B") and w1 == w2:
        return {"winner": w1, "consistent": True, "reasons": [j1.get("reason", ""), j2.get("reason", "")]}
    return {"winner": "tie", "consistent": False, "reasons": [j1.get("reason", ""), j2.get("reason", "")]}


def rerank_with_llm(result, cfg, client: LLMClient | None = None):
    """Blend system score with LLM rubric score on the top-K longlist (rank-average), then one debiased
    pairwise bubble pass over the final top-N."""
    lc = cfg["llm"]; client = client or make_client(cfg)
    eps = {e.number: e for e in result["episodes"]}
    k = lc.get("rerank_top_k", 30); alpha = lc.get("system_weight", 0.5)
    aud = _aud(result)
    pool = sorted(result["longlist"], key=lambda c: -c.score)[:k]
    errors = 0
    for c in pool:
        try:
            j = parse_json(client.complete(RUBRIC.format(audience=aud), f"Show: {result['show']}\n\nTRANSCRIPT:\n{transcript_text(c, eps)}"))
        except Exception as e:      # network/auth/quota: keep the system score for this clip
            errors += 1; j = {"_error": str(e)[:120]}
        keys = ("hook", "cliffhanger", "standalone", "overall")
        if all(isinstance(j.get(x), (int, float)) for x in keys):
            ss = j.get("spoiler_safe", 5) if isinstance(j.get("spoiler_safe"), (int, float)) else 5
            c.comps["llm"] = round((j["hook"] + j["cliffhanger"] + j["standalone"] + 2 * j["overall"] + 0.5 * ss) / 27.5, 3)
            if j.get("risk"):
                c.flags.append("LLM: " + str(j["risk"])[:80])
            if j.get("why"):
                c.llm_why = str(j["why"])[:160]
        else:
            c.comps["llm"] = None
    sys_rank = {id(c): r for r, c in enumerate(pool)}
    scored = [c for c in pool if c.comps.get("llm") is not None]
    llm_rank = {id(c): r for r, c in enumerate(sorted(scored, key=lambda c: -c.comps["llm"]))}
    for c in pool:
        lr = llm_rank.get(id(c), sys_rank[id(c)])
        c.comps["blend_rank"] = alpha * sys_rank[id(c)] + (1 - alpha) * lr
    pool.sort(key=lambda c: c.comps["blend_rank"])
    n = cfg["top_n"]
    swaps = 0; inconsistent = 0
    if lc.get("pairwise_refine", True) and len(pool) > 1 and scored:
        top = pool[:n]
        for i in range(len(top) - 1):
            try:
                v = judge_pair(client, transcript_text(top[i], eps), transcript_text(top[i + 1], eps), aud)
            except Exception:
                errors += 1; continue
            if not v["consistent"]:
                inconsistent += 1
            elif v["winner"] == "B":
                top[i], top[i + 1] = top[i + 1], top[i]; swaps += 1
        pool[:n] = top
    if len(pool) >= n:
        result["top"] = pool[:n]
    result["llm_used"] = {"provider": getattr(client, "name", "?"), "model": getattr(client, "model", ""), "k": k,
                          "scored": len(scored), "errors": errors, "pairwise_swaps": swaps,
                          "pairwise_inconsistent": inconsistent, "api_calls": getattr(client, "calls", None),
                          "cache_hits": getattr(client, "cache_hits", None)}
    return result
