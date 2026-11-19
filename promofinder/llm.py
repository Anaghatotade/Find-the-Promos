"""Optional, provider-agnostic LLM layer.

The core ranker needs no LLM. When a stronger model is available (Kuku can plug in
its own API), it is used for exactly two jobs where language understanding beats
features, on a SMALL shortlist (cost stays ~constant per show):
  1. rerank_with_llm  - rubric-score the top-K candidates and blend with the system score
  2. judge_pair       - blind A/B judging for evaluation (eval/pairwise.py)
Swap models by config: provider = anthropic | openai | openai_compatible (Ollama,
Groq, vLLM, Gemini's OpenAI endpoint ...) | mock. Prompts ask for JSON only; any
malformed answer falls back to the system score (the LLM can never break a run).
"""
from __future__ import annotations
import json, os, re
from typing import Dict, List

RUBRIC = """You are a senior promo editor for vertical microdramas (ReelShort/DramaBox style).
Rate this candidate clip for use as a 20-60s social ad that pulls NEW viewers into the show.
Judge only from the transcript. Score 1-5 each:
- hook: does the first 3 seconds stop a scrolling viewer (slap, reveal, shocking line)?
- cliffhanger: does it cut at an unresolved moment so the viewer needs to know what happens next?
- standalone: would someone who has never seen the show understand who/what is at stake?
- overall: would you post it?
Return ONLY JSON: {"hook":n,"cliffhanger":n,"standalone":n,"overall":n,"why":"<=20 words","risk":"<=12 words or empty"}"""

PAIR = """You are a senior promo editor for vertical microdramas. Two candidate 20-60s promo clips
from the same show are shown as transcripts. Which one would pull more new viewers on TikTok/Reels?
Consider the first 3 seconds (hook), the final moment (cliffhanger) and whether a stranger can follow it.
Return ONLY JSON: {"winner":"A" or "B","confidence":1-5,"reason":"<=20 words"}"""


class LLMClient:
    def complete(self, system: str, user: str) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    def __init__(self, model="claude-sonnet-4-5", api_key=None):
        import anthropic  # pip install anthropic
        self.c = anthropic.Anthropic(api_key=api_key or os.environ.get("PROMOFINDER_ANTHROPIC_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        self.model = model

    def complete(self, system, user):
        r = self.c.messages.create(model=self.model, max_tokens=300, system=system,
                                   messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in r.content if getattr(b, "type", "") == "text")


class OpenAIClient(LLMClient):
    """Also covers any OpenAI-compatible endpoint via base_url (Ollama, Groq, vLLM, Gemini)."""
    def __init__(self, model="gpt-4o-mini", api_key=None, base_url=None):
        from openai import OpenAI  # pip install openai
        self.c = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY", "none"),
                        base_url=base_url or os.environ.get("OPENAI_BASE_URL"))
        self.model = model

    def complete(self, system, user):
        r = self.c.chat.completions.create(model=self.model, temperature=0, max_tokens=300,
                                           messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        return r.choices[0].message.content or ""


class MockClient(LLMClient):
    """Deterministic stand-in used by tests (and to dry-run the plumbing)."""
    def complete(self, system, user):
        if "winner" in system:
            return json.dumps({"winner": "A" if len(user.split("CLIP B")[0]) >= len(user.split("CLIP B")[-1]) else "B",
                               "confidence": 2, "reason": "mock"})
        n = min(5, 1 + user.count("?") + user.count("!"))
        return json.dumps({"hook": n, "cliffhanger": n, "standalone": 3, "overall": n, "why": "mock", "risk": ""})


def make_client(cfg) -> LLMClient:
    p = (cfg.get("provider") or "none").lower()
    if p == "anthropic":
        return AnthropicClient(cfg.get("model") or "claude-sonnet-4-5")
    if p in ("openai", "openai_compatible"):
        return OpenAIClient(cfg.get("model") or "gpt-4o-mini", base_url=cfg.get("base_url"))
    if p == "mock":
        return MockClient()
    raise ValueError(f"unknown LLM provider {p}")


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


def rerank_with_llm(result, cfg, client: LLMClient | None = None):
    """Blend system score with LLM rubric score on the top-K longlist (rank-average)."""
    lc = cfg["llm"]; client = client or make_client(lc)
    eps = {e.number: e for e in result["episodes"]}
    k = lc.get("rerank_top_k", 30); alpha = lc.get("system_weight", 0.5)
    pool = sorted(result["longlist"], key=lambda c: -c.score)[:k]
    for c in pool:
        j = parse_json(client.complete(RUBRIC, f"Show: {result['show']}\n\nTRANSCRIPT:\n{transcript_text(c, eps)}"))
        if all(isinstance(j.get(x), (int, float)) for x in ("hook", "cliffhanger", "standalone", "overall")):
            c.comps["llm"] = round((j["hook"] + j["cliffhanger"] + j["standalone"] + 2 * j["overall"]) / 25.0, 3)
            if j.get("risk"):
                c.flags.append("LLM: " + str(j["risk"])[:80])
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
    if len(pool) >= n:
        result["top"] = pool[:n]
    result["llm_used"] = {"provider": lc.get("provider"), "model": lc.get("model"), "k": k, "scored": len(scored)}
    return result


def judge_pair(client: LLMClient, text_a: str, text_b: str) -> Dict:
    return parse_json(client.complete(PAIR, f"CLIP A:\n{text_a}\n\nCLIP B:\n{text_b}"))
