"""End-to-end promo discovery: boundaries -> moment scorers -> candidates -> rank."""
from __future__ import annotations
import math, re, time
import numpy as np
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from .parser import Episode, Block, fmt_ts
from .features import (set_arousal_mode, hook_features, cliff_features, window_features, hook_text, cliff_text,
                       overlapping, HOOK_SPAN, CLIFF_SPAN)
from .models import (TextFeatLR, CLIFF_DENSE, HOOK_DENSE, cliff_rule_score, hook_lfs)
from .labelmodel import LabelModel
from .series import SeriesIndex
from . import lexicons as L

EPS = 1e-6
POS_ZONE, NEG_ZONE = 4.0, 20.0   # cliffhanger self-supervision: last 4s = pos, >20s before end = neg
VIOLENCE = re.compile(r"\b(blood\w*|branding|searing iron|stab\w*|wound\w*|lacerat\w*|whip\w*|torture\w*|"
                      r"burn\w* (?:her|you|flesh|skin)|gallows|execut\w*|hang\w*|explosion|fireball)\b", re.I)


# ---------------------------------------------------------------- boundaries
def _clip(x: float, lo: float, hi: float) -> float:
    """Same value as float(np.clip(x, lo, hi)) for finite floats, without numpy call overhead."""
    return float(min(max(x, lo), hi))


def valid_cut(ep: Episode, t: float) -> bool:
    """A cut is legal only if it does not split a line of dialogue."""
    return not any(b.kind == "dialogue" and b.start + 0.05 < t < b.end - 0.05
                   for b in overlapping(ep.blocks, t - 0.1, t + 0.1))


def boundaries(ep: Episode):
    starts = sorted({round(b.start, 2) for b in ep.blocks if b.kind in ("camera", "dialogue")})
    ends = sorted({round(b.end, 2) for b in ep.blocks if b.kind in ("camera", "dialogue")})
    starts = [s for s in starts if valid_cut(ep, s)]
    ends = [e for e in ends if valid_cut(ep, e) and e > 0]
    shot_starts = {round(b.start, 2) for b in ep.blocks if b.kind == "camera"}
    shot_ends = {round(b.end, 2) for b in ep.blocks if b.kind == "camera"}
    return starts, ends, shot_starts, shot_ends


@dataclass
class Moment:
    ep: int
    t: float
    feats: Dict[str, float]
    text: str
    score: float = 0.0
    pct: float = 0.0
    label: int = -1          # cliff self-supervision label (-1 = unlabeled)
    extra: Dict = field(default_factory=dict)


def pct_rank(x: np.ndarray) -> np.ndarray:
    if len(x) == 0:
        return x
    order = x.argsort().argsort()
    return (order + 0.5) / len(x)


# ---------------------------------------------------------------- moment scoring
def build_moments(episodes: List[Episode]):
    hooks, cliffs, bnd = [], [], {}
    for ep in episodes:
        st, en, ss, se = boundaries(ep)
        bnd[ep.number] = (st, en, ss, se)
        for s in st:
            if s <= ep.duration - 2.5:
                hooks.append(Moment(ep.number, s, hook_features(ep, s), hook_text(ep, s)))
        for e in en:
            if e >= 2.5:
                lab = 1 if e >= ep.duration - POS_ZONE else (0 if e <= ep.duration - NEG_ZONE else -1)
                cliffs.append(Moment(ep.number, e, cliff_features(ep, e), cliff_text(ep, e), label=lab))
    return hooks, cliffs, bnd


def future_payoff(cliffs: List[Moment], hooks: List[Moment], episodes: List[Episode], horizon=6.0):
    """For each cut point: how strong is the moment the viewer is DENIED by cutting here?
    = best hook-score of any legal start in (t, t+horizon]. At an episode end we look into
    the next episode's opening, because the story continues there."""
    by_ep: Dict[int, List[Moment]] = {}
    for h in hooks:
        by_ep.setdefault(h.ep, []).append(h)
    dur = {e.number: e.duration for e in episodes}
    nxt = {e.number: e for e in episodes}
    for m in cliffs:
        cand = [h.score for h in by_ep.get(m.ep, []) if m.t - 0.05 <= h.t <= m.t + horizon]
        if m.t >= dur[m.ep] - 1.0 and (m.ep + 1) in nxt:
            cand += [h.score for h in by_ep.get(m.ep + 1, []) if h.t <= horizon]
        m.feats["c_payoff"] = max(cand) if cand else 0.0
        # pending answer: last line is a question and the reply comes only after the cut
        ep = nxt[m.ep]
        after = [b for b in ep.blocks if b.kind == "dialogue" and b.start >= m.t - 0.05][:1]
        if not after and (m.ep + 1) in nxt:
            after = [b for b in nxt[m.ep + 1].blocks if b.kind == "dialogue"][:1]
        last = [b for b in overlapping(ep.blocks, m.t - CLIFF_SPAN, m.t, {"dialogue"})][-1:]
        m.feats["c_pending_answer"] = float(bool(last and after and last[0].text.rstrip().endswith("?")
                                                 and after[0].speaker != last[0].speaker))


def cliff_v2_score(f: Dict[str, float]) -> float:
    """A-priori weights (not fit to any labels): open content + withheld payoff - closure."""
    v = (0.40 * cliff_rule_score(f) + 0.35 * f["c_payoff"] + 0.15 * f["c_pending_answer"]
         + 0.10 * f["c_arousal_last"] - 0.25 * min(f["c_resolve_lex"], 3) / 3)
    return _clip(v, 0, 1)


def score_cliffs(cliffs: List[Moment], mode="withheld_payoff", blend=0.7, n_folds=5, seed=0, C=1.0,
                 hooks=None, episodes=None):
    if mode == "withheld_payoff":
        future_payoff(cliffs, hooks, episodes)
        for m in cliffs:
            m.score = cliff_v2_score(m.feats); m.extra["model"] = "withheld_payoff_v2"
        return
    rules = np.array([cliff_rule_score(m.feats) for m in cliffs])
    groups = np.array([m.ep for m in cliffs]); labels = np.array([m.label for m in cliffs])
    n_pos = int((labels == 1).sum()); eps_ = np.unique(groups)
    if mode != "self_supervised" or n_pos < 8 or len(eps_) < 4:
        for m, r in zip(cliffs, rules):
            m.score = float(r); m.extra["model"] = "rules"
        return
    out = np.zeros(len(cliffs))
    rng = np.random.RandomState(seed); order = eps_.copy(); rng.shuffle(order)
    for fold in np.array_split(order, min(n_folds, len(order))):
        te = np.isin(groups, fold); tr = (~te) & (labels >= 0)
        model = TextFeatLR(CLIFF_DENSE, C=C).fit([cliffs[i].text for i in np.where(tr)[0]],
                                                [cliffs[i].feats for i in np.where(tr)[0]], labels[tr])
        idx = np.where(te)[0]
        out[idx] = model.predict_proba([cliffs[i].text for i in idx], [cliffs[i].feats for i in idx])
    final = blend * out + (1 - blend) * rules
    for m, f, o in zip(cliffs, final, out):
        m.score = float(f); m.extra["model_oof"] = float(o); m.extra["model"] = "self_supervised+rules"


def score_hooks(hooks: List[Moment], mode="weak_supervision", n_folds=5, seed=0):
    Lm = np.array([hook_lfs(m.feats) for m in hooks])
    lm = LabelModel().fit(Lm)
    p_lm = lm.predict_proba(Lm)
    # the end model is cross-fitted by episode, so it needs >= 2 episodes to have any training data
    if mode != "weak_supervision" or len(hooks) < 50 or len({m.ep for m in hooks}) < 2:
        for m, p in zip(hooks, p_lm):
            m.score = float(p); m.extra["model"] = "label_model"
        return lm
    groups = np.array([m.ep for m in hooks]); eps_ = np.unique(groups)
    out = np.zeros(len(hooks))
    rng = np.random.RandomState(seed); order = eps_.copy(); rng.shuffle(order)
    for fold in np.array_split(order, min(n_folds, len(order))):
        te = np.isin(groups, fold); tr = np.where(~te)[0]
        # soft labels -> duplicated rows with probability weights
        texts = [hooks[i].text for i in tr] * 2
        feats = [hooks[i].feats for i in tr] * 2
        y = np.r_[np.ones(len(tr)), np.zeros(len(tr))]
        w = np.r_[p_lm[tr], 1 - p_lm[tr]]
        m = TextFeatLR(HOOK_DENSE).fit(texts, feats, y, sample_weight=w)
        idx = np.where(te)[0]
        out[idx] = m.predict_proba([hooks[i].text for i in idx], [hooks[i].feats for i in idx])
    for m, a, b in zip(hooks, p_lm, out):
        m.score = float(0.5 * a + 0.5 * b); m.extra.update(model="ws_label+end_model", lm=float(a), end=float(b))
    return lm


# ---------------------------------------------------------------- candidates
@dataclass
class Segment:
    episode: int
    start: float
    end: float

    @property
    def dur(self):
        return self.end - self.start


@dataclass
class Candidate:
    segments: List[Segment]
    kind: str                         # single | cross_episode | cold_open
    hook: Moment
    cliff: Moment
    comps: Dict[str, float] = field(default_factory=dict)
    wfeat: Dict[str, float] = field(default_factory=dict)
    score: float = 0.0
    flags: List[str] = field(default_factory=list)
    text: str = ""
    _dia: list = field(default_factory=list, repr=False)   # dialogue blocks in the clip (for exact fast paths)

    @property
    def dur(self):
        return sum(s.dur for s in self.segments)


def clear_caches():
    """Drop module-level speed-up caches (results are unaffected; they only hold references)."""
    from . import features
    features._OV_INDEX.clear(); _VIOL_CACHE.clear(); _JUNC_CACHE.clear()


_VIOL_CACHE: dict = {}


def _viol_piece(t: str) -> bool:
    v = _VIOL_CACHE.get(t)
    if v is None:
        if len(_VIOL_CACHE) > 200000:
            _VIOL_CACHE.clear()
        v = _VIOL_CACHE[t] = bool(VIOLENCE.search(t))
    return v


def violence_flag(c) -> bool:
    """== bool(VIOLENCE.search(c.text + ' ' + c.cliff.text + ' ' + c.hook.text)), computed per piece.
    Every VIOLENCE pattern spans at most two space-separated tokens, so a match either lies inside
    one piece or straddles one junction; junctions are checked with the two tokens on each side."""
    pieces = [b.text for b in c._dia] if c._dia else [""]
    pieces += [c.cliff.text, c.hook.text]
    if any(_viol_piece(p) for p in pieces):
        return True
    for a, b in zip(pieces, pieces[1:]):
        if _viol_junction(a, b):
            return True
    return False


_JUNC_CACHE: dict = {}


def _viol_junction(a: str, b: str) -> bool:
    k = (a, b)
    v = _JUNC_CACHE.get(k)
    if v is None:
        if len(_JUNC_CACHE) > 200000:
            _JUNC_CACHE.clear()
        v = _JUNC_CACHE[k] = _viol_piece(" ".join(a.split(" ")[-2:]) + " " + " ".join(b.split(" ")[:2]))
    return v


def opens_on_answer(sg, eps, max_gap=3.0) -> bool:
    """True if the clip's first line replies to a question the viewer never hears
    (asked by another speaker just before the cut - possibly at the end of the previous episode)."""
    ep = eps[sg.episode]
    first = overlapping(ep.blocks, sg.start, sg.end, {"dialogue"})[:1]
    if not first:
        return False
    prev = [b for b in ep.blocks if b.kind == "dialogue" and b.end <= sg.start + 0.05]
    gap = (first[0].start - prev[-1].end) if prev else None
    if not prev and sg.start < 1.0 and (sg.episode - 1) in eps:
        prev = [b for b in eps[sg.episode - 1].blocks if b.kind == "dialogue"]
        gap = first[0].start + (eps[sg.episode - 1].duration - prev[-1].end) if prev else None
    if not prev or gap is None:
        return False
    q = prev[-1]
    return q.text.rstrip().endswith("?") and q.speaker != first[0].speaker and gap < max_gap


def stability(picks, longlist, cfg, draws=200, spread=0.5, seed=0):
    """How much should an editor trust a pick's place? Fraction of random weight settings
    (each weight x U(1-spread, 1+spread)) under which the pick still ranks in the top-N of
    the diverse longlist. Not a probability of being 'good' - a robustness-to-our-guesses signal."""
    pool = list({id(c): c for c in list(longlist) + list(picks)}.values())
    if not pool:
        return
    W = cfg["weights"]; keys = list(W); n = cfg["top_n"]
    rng = np.random.RandomState(seed)
    logc = np.array([[math.log(max(c.comps[k], 0.02)) for k in keys] for c in pool])
    extra = np.array([c.comps["duration_fit"] * c.comps["funnel"] * (1 - c.comps.get("_penalty", 0.0)) for c in pool])
    base = np.array([W[k] for k in keys])
    def ranks(w):
        sc = np.exp(logc @ w / w.sum()) * extra
        r = np.empty(len(pool), int); r[np.argsort(-sc)] = np.arange(len(pool)); return r
    pick_idx = [i for i, c in enumerate(pool) if any(c is p for p in picks)]
    cutoff = max(ranks(base)[pick_idx]) if pick_idx else n - 1   # every pick is "in" at the default weights
    hits = np.zeros(len(pool))
    for _ in range(draws):
        hits += ranks(base * rng.uniform(1 - spread, 1 + spread, len(keys))) <= cutoff
    for c, h in zip(pool, hits / draws):
        c.comps["stability"] = round(float(h), 3)


def total_score(comps, W, funnel=True):
    """Weighted geometric mean of components x duration fit x funnel prior x edit penalty."""
    ws = sum(W.values()) or 1.0
    logs = sum(W[k] * math.log(max(comps[k], 0.02)) for k in W) / ws
    return float(math.exp(logs) * comps["duration_fit"] * (comps["funnel"] if funnel else 1.0) * (1 - comps.get("_penalty", 0.0)))


class PromoFinder:
    def __init__(self, cfg):
        self.cfg = cfg

    # -- component scores for one candidate
    def _components(self, c: Candidate, eps: Dict[int, Episode], series: SeriesIndex):
        cfg = self.cfg
        dia_all, wf_list = [], []
        for sg in c.segments:
            ep = eps[sg.episode]
            wf_list.append((window_features(ep, sg.start, sg.end), sg.dur))
            dia_all += overlapping(ep.blocks, sg.start, sg.end, {"dialogue"})
        # duration-weighted merge of window features
        keys = wf_list[0][0].keys(); tot = sum(d for _, d in wf_list)
        wf = {k: sum(f[k] * d for f, d in wf_list) / tot for k in keys}
        for k in ("w_n_lines", "w_relational", "w_scene_changes"):
            wf[k] = sum(f[k] for f, _ in wf_list)
        wf["w_arousal_peak"] = max(f["w_arousal_peak"] for f, _ in wf_list)
        wf["w_dangling_open"] = wf_list[0][0]["w_dangling_open"]
        wf["w_answer_open"] = float(opens_on_answer(c.segments[0], eps))
        wf["w_n_speakers"] = float(len({b.speaker for b in dia_all if not b.voiceover}))
        refs = series.unintroduced_refs(c.segments[0].episode, dia_all)
        wf["w_unintroduced"] = float(len(refs))
        c.wfeat = wf
        # standalone: can a stranger follow it?
        sa = (0.55 + 0.07 * min(wf["w_relational"], 4) - 0.22 * max(wf["w_dangling_open"], wf["w_answer_open"])
              - 0.12 * min(wf["w_scene_changes"], 3) - 0.08 * min(wf["w_unintroduced"], 3)
              + 0.25 * (min(wf["w_dialogue_cov"], 0.8) - 0.4)
              + (0.05 if 2 <= wf["w_n_speakers"] <= 4 else -0.05)
              - (0.15 if wf["w_n_lines"] < 3 else 0.0))
        arc = (0.45 * wf["w_arousal_peak"] + 0.25 * wf["w_arousal_mean"]
               + 0.2 * _clip(0.5 + wf["w_escalation"], 0, 1) + 0.1 * wf["w_conflict"])
        c.comps = {"hook": c.hook.pct, "cliff": c.cliff.pct,
                   "standalone": _clip(sa, 0.02, 1), "arc": _clip(arc, 0.02, 1)}
        c.text = " ".join(b.text for b in dia_all)
        c._dia = dia_all
        if refs:
            c.flags.append("needs context: mentions " + ", ".join(sorted(refs)))
        if wf["w_answer_open"]:
            c.flags.append("opens on a reply to an unheard question")
        elif wf["w_dangling_open"]:
            c.flags.append("opens mid-exchange")
        if wf["w_scene_changes"] >= 1 and c.kind == "single":
            c.flags.append("crosses a scene/location change")

    def _finalise(self, cands: List[Candidate], series: SeriesIndex, n_eps_max: int):
        cfg = self.cfg; W = cfg["weights"]
        prem = pct_rank(series.premise_sim_windows([c._dia for c in cands])) if cands else []
        lo, hi = cfg["ideal_dur"]
        for c, p in zip(cands, prem):
            c.comps["premise"] = float(p)
            d = c.dur
            dur_fit = 1.0 if lo <= d <= hi else 1 - 0.15 * (min(abs(d - lo), abs(d - hi)) / max(lo - cfg["min_dur"], cfg["max_dur"] - hi))
            pen = 0.0
            if c.kind == "cold_open":
                pen += cfg["cold_open_penalty"]
            if c.kind == "cross_episode":
                pen += cfg["cross_episode_penalty"]
            funnel = 1.0
            if cfg["funnel"]["enabled"] and n_eps_max > 1:
                pos = (c.segments[0].episode - 1) / (n_eps_max - 1)
                funnel = 1 - cfg["funnel"]["late_episode_penalty"] * pos ** 2
            c.comps["duration_fit"] = round(dur_fit, 3); c.comps["funnel"] = round(funnel, 3)
            c.comps["_penalty"] = pen
            c.score = total_score(c.comps, W)
            if c.cliff.feats["c_resolve_lex"] >= 2 and c.cliff.feats["c_last_q"] == 0:
                c.flags.append("ending may feel resolved")
            if violence_flag(c):
                c.flags.append("ad-policy review: violence/injury")
            if (c.segments[0].episode - 1) / max(n_eps_max - 1, 1) > 0.66:
                c.flags.append("late-series: may spoil major reveals")

    def run(self, show: str, episodes: List[Episode], progress=None):
        """progress(stage_label, fraction_done) is called between stages (e.g. by the web app)."""
        cfg = self.cfg
        timings, clock = {}, [time.perf_counter()]

        def stage(done_label, frac, next_label):
            now = time.perf_counter(); timings[done_label] = round(now - clock[0], 3); clock[0] = now
            if progress:
                progress(next_label, frac)

        if progress:
            progress("Indexing the series", 0.02)
        eps = {e.number: e for e in episodes}
        # delivery-tag coverage decides how line intensity is measured (v1.1, see exp5_tagfree)
        n_dia = sum(1 for e in episodes for b in e.blocks if b.kind == "dialogue")
        tag_cov = sum(1 for e in episodes for b in e.blocks if b.kind == "dialogue" and b.tags) / max(n_dia, 1)
        mode = cfg.get("arousal_mode", "auto")
        if mode == "auto":
            mode = "tags" if tag_cov >= 0.5 else "fallback"
        set_arousal_mode(mode)
        series = SeriesIndex(show, episodes)
        stage("series_index", 0.05, "Finding every legal cut point")
        hooks, cliffs, bnd = build_moments(episodes)
        stage("cut_points_and_moment_features", 0.12, "Scoring hooks (weak supervision)")
        lm = score_hooks(hooks, cfg["hook_model"])
        stage("hook_model", 0.24, "Scoring cliffhangers")
        score_cliffs(cliffs, cfg["cliff_model"], blend=cfg.get("cliff_blend", 0.7), hooks=hooks, episodes=episodes)
        for arr in (hooks, cliffs):
            p = pct_rank(np.array([m.score for m in arr]))
            for m, v in zip(arr, p):
                m.pct = float(v)
        stage("cliff_model", 0.28, "Generating candidate clips")
        H = {(m.ep, m.t): m for m in hooks}; Cm = {(m.ep, m.t): m for m in cliffs}
        cands: List[Candidate] = []
        # 1) single continuous windows
        for ep in episodes:
            st, en, ss, se = bnd[ep.number]
            for s in st:
                if (ep.number, s) not in H:
                    continue
                for e in en:
                    d = e - s
                    if d < cfg["min_dur"] or d > cfg["max_dur"]:
                        continue
                    if e > s and (ep.number, e) in Cm:
                        cands.append(Candidate([Segment(ep.number, s, e)], "single", H[(ep.number, s)], Cm[(ep.number, e)]))
        # 2) cross-episode bridges (story is continuous across episode cuts)
        if cfg["allow_cross_episode"]:
            nums = sorted(eps)
            for a, b in zip(nums, nums[1:]):
                if b != a + 1:
                    continue
                ea, eb = eps[a], eps[b]
                st_a = [s for s in bnd[a][0] if ea.duration - s >= 6 and (a, s) in H]
                en_b = [e for e in bnd[b][1] if e >= 8 and (b, e) in Cm]
                for s in st_a:
                    for e in en_b:
                        d = (ea.duration - s) + e
                        if cfg["min_dur"] <= d <= cfg["max_dur"]:
                            cands.append(Candidate([Segment(a, s, ea.duration), Segment(b, 0.0, e)],
                                                   "cross_episode", H[(a, s)], Cm[(b, e)]))
        stage("candidate_generation", 0.30, f"Scoring {len(cands):,} candidate clips")
        for i, c in enumerate(cands):
            self._components(c, eps, series)
            if progress and i % 5000 == 4999:
                progress(f"Scoring {len(cands):,} candidate clips", 0.30 + 0.45 * (i + 1) / len(cands))
        stage("clip_components", 0.75, "Premise fit and final scores")
        self._finalise(cands, series, max(eps))
        stage("premise_and_total_score", 0.82, "Cold-open edits")
        # 3) cold opens: best short hook snippet + strong body from same/adjacent episode
        if cfg["allow_cold_open"] and cands:
            cands += self._cold_opens(cands, hooks, bnd, eps, series)
        stage("cold_opens", 0.86, "Choosing a diverse top list")
        cands.sort(key=lambda c: -c.score)
        picks = self._select(cands, series, cfg["top_n"])
        longlist = self._select(cands, series, cfg["longlist_n"])
        stage("diverse_selection", 0.95, "Checking pick stability")
        stability(picks, longlist, cfg)
        stage("stability", 0.97, "Writing outputs")
        clear_caches()   # long-running servers: don't keep this show's blocks alive via speed-up caches
        return {"timings": timings, "arousal_mode": mode, "tag_coverage": round(tag_cov, 3), "show": show, "episodes": episodes, "series": series, "hooks": hooks, "cliffs": cliffs,
                "candidates": cands, "top": picks, "longlist": longlist, "label_model": lm}

    def _cold_opens(self, cands, hooks, bnd, eps, series):
        cfg = self.cfg
        top_h = sorted(hooks, key=lambda m: -m.score)[:60]
        # bodies with a strong cliffhanger/standalone story but a weaker opening benefit most
        bodies = sorted((c for c in cands if c.kind == "single"),
                        key=lambda c: -(c.comps["cliff"] * c.comps["standalone"] * c.comps["arc"]))[:600]
        out = []
        for h in top_h:
            ep = eps[h.ep]
            ends = [e for e in bnd[h.ep][1] if 2.5 <= e - h.t <= 7.0]
            if not ends:
                continue
            he = ends[-1]
            hd = overlapping(ep.blocks, h.t, he, {"dialogue"})
            hspk = {b.speaker.split()[-1] for b in hd}
            for body in bodies:
                sg = body.segments[0]
                if abs(sg.episode - h.ep) > 1 or body.comps["hook"] >= h.pct:
                    continue
                if sg.episode == h.ep and not (he <= sg.start or h.t >= sg.end):
                    continue  # snippet must not overlap the body
                if sg.dur + (he - h.t) > cfg["max_dur"]:
                    continue
                bd = overlapping(eps[sg.episode].blocks, sg.start, sg.end, {"dialogue"})
                if not hspk & {b.speaker.split()[-1] for b in bd}:
                    continue  # same characters -> coherent story
                c = Candidate([Segment(h.ep, h.t, he), Segment(sg.episode, sg.start, sg.end)], "cold_open", h, body.cliff)
                out.append(c)
                break
        for c in out:
            self._components(c, eps, series)
        self._finalise(out, series, max(eps))
        return out

    def _select(self, cands: List[Candidate], series: SeriesIndex, n: int):
        """Greedy MMR: high score, no time overlap, <=k per episode, content diversity."""
        cfg = self.cfg
        # pool = global top + top-k of every episode, so the longlist is not starved by a few episodes
        per = {}
        for c in cands:
            per.setdefault(c.segments[0].episode, []).append(c)
        keep = {id(c) for c in cands[: max(2000, n * 40)]}
        for lst in per.values():
            keep |= {id(c) for c in lst[:40]}
        pool = [c for c in cands if id(c) in keep]
        if not pool:
            return []
        E = series.embed_windows([c._dia for c in pool])
        return [pool[i] for i in mmr_select(pool, E, n, cfg["mmr_lambda"], cfg["max_per_episode"])]


def mmr_select(pool, E, n, lam, max_per_ep):
    """Vectorised greedy MMR, same rule as the original loop: among candidates whose episodes
    still have room and that do not overlap a chosen clip (0.5 s tolerance), take the first one
    maximising (1-lam)*score - lam*maxsim*score, where maxsim is the highest cosine to any chosen clip."""
    N = len(pool)
    K = max(len(c.segments) for c in pool)
    seg_ep = np.full((N, K), -1, dtype=np.int64); seg_s = np.zeros((N, K)); seg_e = np.zeros((N, K))
    for i, c in enumerate(pool):
        for k, sg in enumerate(c.segments):
            seg_ep[i, k], seg_s[i, k], seg_e[i, k] = sg.episode, sg.start, sg.end
    valid = seg_ep >= 0
    score = np.array([c.score for c in pool], dtype=float)
    blocked = np.zeros(N, dtype=bool)          # chosen or overlapping a chosen clip
    maxsim = np.full(N, -np.inf)
    ep_count = {}
    chosen = []
    while len(chosen) < n:
        full = np.zeros(N, dtype=bool)
        for ep, cnt in ep_count.items():
            if cnt >= max_per_ep:
                full |= ((seg_ep == ep) & valid).any(axis=1)
        ok = ~blocked & ~full
        if not ok.any():
            break
        sim = maxsim if chosen else np.zeros(N)
        v = np.where(ok, (1 - lam) * score - lam * sim * score, -np.inf)
        best = int(np.argmax(v))
        if not np.isfinite(v[best]) or v[best] <= -1e9:
            break
        chosen.append(best); blocked[best] = True
        for sg in pool[best].segments:
            ep_count[sg.episode] = ep_count.get(sg.episode, 0) + 1
            hit = (seg_ep == sg.episode) & valid & (seg_s < sg.end - 0.5) & (sg.start < seg_e - 0.5)
            blocked |= hit.any(axis=1)
        maxsim = np.maximum(maxsim, E @ E[best])
    return chosen


def _overlap(a: Candidate, b: Candidate) -> bool:
    for x in a.segments:
        for y in b.segments:
            if x.episode == y.episode and x.start < y.end - 0.5 and y.start < x.end - 0.5:
                return True
    return False
