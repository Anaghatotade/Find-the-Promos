"""Learning the ranking from editors: Use/Reject votes AND A/B comparisons, closed into the loop.

Why pairwise: "which of these two would you post?" is faster and more consistent than an absolute
yes/no (the reason RLHF reward models and Elo-style ratings are trained on comparisons). Use/Reject votes
are still used: within one run, every Used clip is treated as preferred over every Rejected one.

Model: the ranker's own scoring rule. A clip's utility is u = sum_k w_k * log(component_k) - exactly the
weighted geometric mean PromoFinder already uses - so learned weights drop straight into config with no
new model to trust. P(A preferred to B) = sigmoid(u_A - u_B) (Bradley-Terry). Weights are fitted by MAP
with a Gaussian prior centred on the hand-set defaults: with few judgments the ranking barely moves, with
many it follows the editors. Weights stay >= 0 (no component can become a reason to rank lower).

Active learning: the next A/B pair shown is the one whose outcome the current model is least sure about,
weighted by how much it would move the weights (Laplace-approximate posterior variance), so each click
teaches the most.

Measured outcomes (impressions/clicks from real ad runs, see `import_performance`) are a separate record
type: they are evidence of audience response, never mixed up with model estimates in the UI.
"""
from __future__ import annotations
import json, math, os, time
from itertools import combinations
from typing import Dict, List, Optional, Tuple
import numpy as np
from scipy.optimize import minimize

KEYS = ["hook", "cliff", "standalone", "arc", "premise"]
DEFAULT = {"hook": 1.0, "cliff": 1.0, "standalone": 0.8, "arc": 0.6, "premise": 0.5}
TOTAL = sum(DEFAULT.values())


def feat(comps: Dict) -> np.ndarray:
    return np.array([math.log(max(float(comps.get(k, 0.02) or 0.02), 0.02)) for k in KEYS])


def read_feedback(path: str) -> List[Dict]:
    if not path or not os.path.exists(path):
        return []
    out = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def append_feedback(path: str, rec: Dict, max_bytes=5_000_000) -> bool:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > max_bytes:
        return False
    rec = dict(rec, ts=rec.get("ts", time.time()))
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return True


def to_pairs(rows: List[Dict], llm_weight=0.3, profile: Optional[str] = None) -> List[Tuple[np.ndarray, np.ndarray, float, float]]:
    """-> list of (x_winner, x_loser, weight, y) with y=1 (winner preferred) or 0.5 (tie)."""
    pairs = []
    latest_vote = {}
    for r in rows:
        if profile and r.get("profile", "general") != profile:
            continue
        t = r.get("type", "vote")
        if t == "pair" and r.get("winner") in ("a", "b", "tie") and "a" in r and "b" in r:
            w = llm_weight if r.get("source") == "llm" else 1.0
            a, b = feat(r["a"]["components"]), feat(r["b"]["components"])
            if r["winner"] == "tie":
                pairs.append((a, b, w * 0.5, 0.5))
            elif r["winner"] == "a":
                pairs.append((a, b, w, 1.0))
            else:
                pairs.append((b, a, w, 1.0))
        elif t == "vote" and r.get("vote") in ("up", "down") and "components" in r:
            latest_vote[(r.get("show", ""), r.get("run", ""), r.get("id"))] = r      # last vote per clip wins
    by_run: Dict[tuple, Dict[str, list]] = {}
    for (show, run, _), r in latest_vote.items():
        by_run.setdefault((show, run), {"up": [], "down": []})[r["vote"]].append(feat(r["components"]))
    for g in by_run.values():
        n = len(g["up"]) * len(g["down"])
        for u in g["up"]:
            for d in g["down"]:
                pairs.append((u, d, 1.0 / math.sqrt(max(n, 1)), 1.0))   # many implied pairs from few clicks: down-weight
    return pairs


def fit_weights(pairs, prior: Dict[str, float] = None, prior_strength: float = 1.0):
    """MAP Bradley-Terry with a Gaussian prior at the default weights. Returns (weights dict, info)."""
    mu = np.array([(prior or DEFAULT)[k] for k in KEYS], dtype=float)
    if not pairs:
        return dict(zip(KEYS, mu.round(3).tolist())), {"n_effective": 0.0, "cov": np.eye(len(KEYS)) / prior_strength}
    D = np.array([a - b for a, b, _, _ in pairs]); W = np.array([w for _, _, w, _ in pairs]); Y = np.array([y for *_, y in pairs])

    def nll(w):
        z = D @ w
        p = 1 / (1 + np.exp(-z))
        ll = W * (Y * np.log(p + 1e-12) + (1 - Y) * np.log(1 - p + 1e-12))
        r = w - mu
        return -ll.sum() + 0.5 * prior_strength * r @ r

    def grad(w):
        p = 1 / (1 + np.exp(-(D @ w)))
        return -(D.T @ (W * (Y - p))) + prior_strength * (w - mu)

    res = minimize(nll, mu.copy(), jac=grad, method="L-BFGS-B", bounds=[(0.0, None)] * len(KEYS))
    w = res.x
    p = 1 / (1 + np.exp(-(D @ w)))
    H = (D * (W * p * (1 - p))[:, None]).T @ D + prior_strength * np.eye(len(KEYS))
    return dict(zip(KEYS, np.round(w, 3).tolist())), {"n_effective": float(W.sum()), "cov": np.linalg.inv(H), "converged": bool(res.success)}


def normalise(w: Dict[str, float]) -> Dict[str, float]:
    s = sum(w.values()) or 1.0
    return {k: round(v / s * TOTAL, 3) for k, v in w.items()}


def learned_weights_for(path: str, cfg: Dict, profile: Optional[str] = None) -> Dict:
    """What the run should use. 'applied' is False until there is enough evidence (cfg.learning.min_judgments)."""
    lc = cfg.get("learning", {})
    rows = read_feedback(path)
    pairs = to_pairs(rows, profile=profile) + performance_pairs(rows)
    base = cfg.get("weights", DEFAULT)
    w, info = fit_weights(pairs, prior=base, prior_strength=lc.get("prior_strength", 1.0))
    n = info["n_effective"]
    need = lc.get("min_judgments", 10)
    applied = bool(lc.get("auto_apply", True)) and n >= need
    n_votes = sum(1 for r in rows if r.get("type", "vote") == "vote")
    n_pairs = sum(1 for r in rows if r.get("type") == "pair")
    return {"weights": normalise(w) if applied else base, "fitted": normalise(w), "default": base, "applied": applied,
            "n_effective": round(n, 2), "n_votes": n_votes, "n_pairs": n_pairs, "needed": need,
            "message": (f"Ranking uses weights learned from {n_pairs} A/B comparisons and {n_votes} Use/Reject votes."
                        if applied else f"Learning: {n:.1f} of {need} judgments collected; default weights in use.")}


def learn_from_file(path: str) -> Dict:
    from .config import load_config
    r = learned_weights_for(path, load_config())
    return {k: v for k, v in r.items() if k != "cov"}


# ---------------------------------------------------------------- scoring + active learning on exported records
def rescore(records: List[Dict], weights: Dict[str, float]) -> List[Dict]:
    """Re-rank exported promos under new weights without re-running the pipeline."""
    ws = sum(weights.values()) or 1.0
    out = []
    for r in records:
        c = r["components"]
        gm = math.exp(sum(weights[k] * math.log(max(c.get(k, 0.02), 0.02)) for k in KEYS) / ws)
        out.append(dict(r, score=round(gm * c.get("extra_factor", 1.0), 4), prior_rank=r.get("rank")))
    out.sort(key=lambda r: -r["score"])
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def _overlap(a, b, tol=0.5):
    return any(x["episode"] == y["episode"] and x["start_s"] < y["end_s"] - tol and y["start_s"] < x["end_s"] - tol
               for x in a["segments"] for y in b["segments"])


def next_pair(records: List[Dict], path: str, cfg: Dict, run: str = "", top_k: int = 50, rng_seed: int = 0) -> Optional[Tuple[Dict, Dict, float]]:
    """Most informative not-yet-judged pair among the top_k: max p(1-p) * posterior variance of the margin."""
    rows = read_feedback(path)
    seen = {frozenset((r["a"]["id"], r["b"]["id"])) for r in rows if r.get("type") == "pair" and r.get("run", run) == run
            and "a" in r and "b" in r}
    w, info = fit_weights(to_pairs(rows) + performance_pairs(rows), prior=cfg.get("weights", DEFAULT), prior_strength=cfg.get("learning", {}).get("prior_strength", 1.0))
    wv = np.array([w[k] for k in KEYS]); cov = info["cov"]
    pool = records[:top_k]
    best, bv = None, -1.0
    for a, b in combinations(pool, 2):
        if frozenset((a["id"], b["id"])) in seen or _overlap(a, b):
            continue
        d = feat(a["components"]) - feat(b["components"])
        p = 1 / (1 + math.exp(-float(wv @ d)))
        v = p * (1 - p) * float(d @ cov @ d)
        if v > bv:
            best, bv = (a, b, p), v
    return best


def import_performance(csv_path: str, feedback_path: str, records: List[Dict]) -> Dict:
    """Measured ad results: CSV with columns id, impressions, clicks (or ctr), optional installs.
    Stored as type=performance next to editor judgments, and converted into pairs only between clips of the
    same show with enough impressions (default 1000) - real response data outranks every model estimate."""
    import csv
    by_id = {r["id"]: r for r in records}
    n = 0
    with open(csv_path, encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            rid = row.get("id") or row.get("promo_id")
            if rid not in by_id:
                continue
            imp = float(row.get("impressions") or 0)
            clicks = float(row.get("clicks") or 0)
            ctr = float(row["ctr"]) if row.get("ctr") else (clicks / imp if imp else 0.0)
            append_feedback(feedback_path, {"type": "performance", "id": rid, "show": row.get("show", ""), "impressions": imp,
                                            "clicks": clicks, "ctr": ctr, "installs": float(row.get("installs") or 0),
                                            "components": by_id[rid]["components"]})
            n += 1
    return {"imported": n}


def performance_pairs(rows: List[Dict], min_impressions=1000.0):
    perf = [r for r in rows if r.get("type") == "performance" and r.get("impressions", 0) >= min_impressions]
    out = []
    for a, b in combinations(perf, 2):
        if a.get("show") != b.get("show") or a["ctr"] == b["ctr"]:
            continue
        hi, lo = (a, b) if a["ctr"] > b["ctr"] else (b, a)
        # confidence grows with the CTR gap relative to its sampling error
        se = math.sqrt(hi["ctr"] * (1 - hi["ctr"]) / hi["impressions"] + lo["ctr"] * (1 - lo["ctr"]) / lo["impressions"]) or 1e-9
        out.append((feat(hi["components"]), feat(lo["components"]), min(3.0, (hi["ctr"] - lo["ctr"]) / se / 2), 1.0))
    return out
