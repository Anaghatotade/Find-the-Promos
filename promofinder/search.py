"""Natural-language scene search over a finished run, returning promo-ready clips.

"find betrayal scenes", "she is locked up underground", "strong emotional confrontation" ->
ranked moments, each with a legal 20-60 s clip around it built from the run's scored cut points.

Retrieval is hybrid, and works fully offline with no model download:
  1. BM25 over beats (a line plus its neighbouring lines), with light stemming;
  2. concept expansion: editor vocabulary ("betrayal", "confrontation", "humiliation", ...) and
     genre-level synonyms ("jail" ~ "cell" ~ "dungeon") expand the query;
  3. LSA (TF-IDF + SVD fitted on this show) for paraphrases the synonym list doesn't cover;
  4. delivery tags: "emotional", "angry", "tender" queries match how a line is performed;
  5. optional dense embeddings (model2vec or sentence-transformers, if installed) blended in.
Every hit says which signals matched, so an editor can see why it was returned.
"""
from __future__ import annotations
import json, math, os, re
from collections import Counter, defaultdict
from typing import Dict, List, Optional
import numpy as np

# ---------------------------------------------------------------- vocabulary
CONCEPTS = {
    # editor vocabulary -> cue words (stems) and delivery-tag stems
    "betrayal": (["betray", "traitor", "cheat", "lie", "lied", "liar", "behind my back", "abandon", "chose her", "chose him",
                  "sold", "framed", "deceiv", "trust"], ["betray", "bitter", "accus", "devastat"]),
    "confrontation": (["how dare", "liar", "accus", "you", "dare", "stop", "enough", "answer me", "get out"],
                      ["furious", "accus", "defiant", "venom", "shout", "rage", "seeth", "demand", "harsh", "fierce"]),
    "emotional": (["tear", "cry", "sob", "weep", "please", "heart", "forgive"],
                  ["tearful", "sob", "weep", "heartbroken", "anguish", "devastat", "trembl", "desperate", "plead", "broken", "crying"]),
    "humiliation": (["humiliat", "kneel", "beg", "laugh", "mock", "beggar", "worthless", "disgrace", "shame", "mud", "trash", "plain"],
                    ["mocking", "cruel", "smug", "scorn", "condescend", "gloat", "taunt"]),
    "revenge": (["revenge", "pay for", "regret", "vengeance", "make them pay", "destroy", "ruin"], ["vengeful", "cold", "icy", "steely", "vindictive"]),
    "romance": (["love", "kiss", "heart", "darling", "hold", "embrace", "together", "marry", "wife", "husband", "protect"],
                ["tender", "loving", "soft", "gentle", "intimate", "warm", "longing"]),
    "violence": (["slap", "strike", "struck", "hit", "punch", "shove", "grab", "whip", "crop", "lash", "beat", "kick", "stab", "blood", "attack", "fight"],
                 ["violent", "furious", "rage"]),
    "threat": (["kill", "die", "dead", "gallows", "hang", "execut", "burn", "or else", "warn", "threat", "regret", "guard"],
               ["menac", "threaten", "deadly", "lethal", "sinister", "chilling", "cold"]),
    "reveal": (["truth", "secret", "real", "identity", "know who", "who you are", "reveal", "it was you", "confess", "alive"],
               ["shocked", "stunned", "aghast", "incredulous", "horrified"]),
    "rescue": (["save", "rescue", "let her go", "take your hands", "step away", "protect", "free"], ["commanding", "low", "thunder"]),
    "power": (["kneel", "bow", "duke", "duchess", "ceo", "heir", "rightful", "title", "crown", "lord", "your grace", "command"],
              ["commanding", "authoritative", "regal", "booming"]),
    "grief": (["dead", "died", "grave", "mother", "miss", "gone", "funeral", "loss"], ["grief", "sob", "mourn", "heartbroken"]),
    "jealousy": (["jealous", "her instead", "mine", "stay away", "choose"], ["jealous", "bitter", "possessive", "spite"]),
}
SYNONYMS = [
    {"marry", "marriage", "wed", "wedding", "bride", "groom", "altar", "vow", "propos", "fiance", "husband", "wife"},
    {"jilt", "abandon", "leave", "left", "reject", "cast", "dump", "desert", "walk out"},
    {"kill", "murder", "poison", "die", "death", "dead", "slay", "dying"},
    {"hit", "strike", "struck", "slap", "whip", "crop", "lash", "beat", "punch", "smack"},
    {"burn", "fire", "flame", "blaze", "ablaze", "smoke", "ash", "inferno", "arson"},
    {"prison", "cell", "dungeon", "jail", "gaol", "lock", "chain", "shackl", "cage", "imprison", "underground", "captive"},
    {"trial", "court", "judge", "accus", "testimon", "witness", "verdict", "sentenc", "charg", "dock"},
    {"witch", "witchcraft", "sorcer", "devil", "curse", "spell"},
    {"heal", "cure", "remedy", "herb", "medicin", "sick", "ill", "fever", "doctor", "potion", "tonic"},
    {"blood", "wound", "injur", "bleed", "bandag", "hurt", "cut", "lacerat", "scar"},
    {"alive", "surviv", "living", "breath", "return"},
    {"pay", "paid", "hire", "bribe", "money", "coin", "gold"},
    {"attack", "thug", "assault", "ambush", "raid", "men"},
    {"soldier", "guard", "salute", "arrest", "constabl", "officer", "royal"},
    {"gate", "door", "explos", "blast", "blown", "shatter", "burst", "smash"},
    {"church", "priest", "clergy", "council", "licens", "invalid", "void", "annul", "cathedral", "sanctuar"},
    {"mother", "mom", "mum", "mama"}, {"father", "dad", "papa"}, {"son", "boy", "child", "kid"},
    {"book", "journal", "diary", "ledger", "notebook", "letter", "page"},
    {"ring", "signet", "jewel", "necklac", "pendant"},
    {"thorn", "briar", "bramble", "rose", "garden", "plant"},
    {"mud", "dirt", "filth", "dust", "ground"},
    {"old", "elderly", "aged", "dowager"}, {"home", "house", "cottage", "cabin", "hut"},
    {"admit", "confess", "reveal", "tell", "say", "own up"},
    {"secret", "hidden", "hide", "conceal", "disguis"},
    {"cry", "tear", "sob", "weep"}, {"angry", "furious", "rage", "anger", "fury"},
]
INTENSE = re.compile(r"\b(strong|intense|big|explosive|heated|huge|powerful|dramatic|shocking|brutal|violent|emotional)\b", re.I)
SOFT = re.compile(r"\b(quiet|soft|tender|gentle|calm|sweet|subtle|intimate)\b", re.I)
STOPWORDS = set("a an the of in on at to for with and or but is are was were be been she he her his him they them their it its "
                "this that these those by from as into out up down over after before who what when where why how scene scenes "
                "find show me clip clips moment moments some any where there someone something my your our i you we us "
                "between lead leads main character characters very really get got just".split())
TOK = re.compile(r"[a-z][a-z']+")


def stem(w: str) -> str:
    w = w.lower().strip("'")
    for suf in ("ingly", "edly", "ation", "ings", "ing", "ies", "ied", "ed", "es", "ly", "s"):
        if len(w) - len(suf) >= 3 and w.endswith(suf):
            w = w[: -len(suf)]
            if suf in ("ies", "ied"):
                w += "y"
            break
    if len(w) > 4 and w[-1] == w[-2] and w[-1] not in "ls":   # stopp -> stop, burnn -> burn
        w = w[:-1]
    return w


def toks(text: str) -> List[str]:
    return [stem(t) for t in TOK.findall(text.lower()) if t not in STOPWORDS]


def query_toks(text: str) -> List[str]:
    """Query words minus intensity modifiers ('strong', 'tender'...), which steer delivery, not content."""
    return [t for t in toks(INTENSE.sub(" ", SOFT.sub(" ", text))) if t]


_SYN = [{stem(x) for x in grp} for grp in SYNONYMS]


def expand(query: str):
    """Returns ({term: weight}, matched concept names, intensity -1/0/+1)."""
    q = query.lower()
    terms: Dict[str, float] = {}
    for t in query_toks(q):
        terms[t] = max(terms.get(t, 0), 1.0)
        for grp in _SYN:
            if t in grp or any(len(g) >= 4 and (t.startswith(g) or g.startswith(t)) for g in grp):
                for g in grp:
                    terms.setdefault(g, 0.55)
    concepts, tag_stems = [], []
    for name, (cues, tags) in CONCEPTS.items():
        if re.search(r"\b" + name[:5], q) or any(re.search(r"\b" + re.escape(c), q) for c in [name] + ([] if name != "violence" else ["fight", "slap"])):
            concepts.append(name)
            for c in cues:
                for t in toks(c):
                    terms.setdefault(t, 0.5)
            tag_stems += tags
    inten = 1 if INTENSE.search(q) else (-1 if SOFT.search(q) else 0)
    return terms, concepts, tag_stems, inten


# ---------------------------------------------------------------- index
class ShowSearch:
    def __init__(self, index: Dict, embedder=None):
        self.show = index["show"]
        self.units = []
        for e in index["episodes"]:
            bl = [b for b in e["blocks"] if b["kind"] in ("dialogue", "action")]
            for i, b in enumerate(bl):
                ctx = [x for x in bl[max(0, i - 2): i + 3] if abs(x["start"] - b["start"]) <= 8.0]
                self.units.append({"episode": e["episode"], "start": b["start"], "end": b["end"], "kind": b["kind"],
                                   "speaker": b.get("speaker", ""), "tags": b.get("tags", []), "text": b["text"],
                                   "doc": b["text"] + " " + b["text"] + " " + " ".join(x["text"] for x in ctx if x is not b),
                                   "ctx_tags": [t for x in ctx for t in x.get("tags", [])]})
        self.eps = {e["episode"]: e for e in index["episodes"]}
        self.hooks = defaultdict(list); self.cliffs = defaultdict(list)
        for ep, t, p in index.get("hooks", []):
            self.hooks[ep].append((t, p))
        for ep, t, p in index.get("cliffs", []):
            self.cliffs[ep].append((t, p))
        docs = [toks(u["doc"]) for u in self.units]
        self.df = Counter(t for d in docs for t in set(d))
        self.tf = [Counter(d) for d in docs]
        self.len = np.array([len(d) for d in docs], dtype=float)
        self.avg = float(self.len.mean()) if len(self.len) else 1.0
        self.N = len(docs)
        # LSA on this show's own beats: learns that words co-occur (cell ~ chains ~ dungeon) without any download
        from sklearn.feature_extraction.text import TfidfVectorizer
        from sklearn.decomposition import TruncatedSVD
        from sklearn.preprocessing import normalize
        self._tfv = TfidfVectorizer(analyzer=lambda s: toks(s), sublinear_tf=True, min_df=2)
        X = self._tfv.fit_transform([u["doc"] for u in self.units])
        k = max(2, min(100, X.shape[1] - 1, X.shape[0] - 1))
        self._svd = TruncatedSVD(n_components=k, random_state=0).fit(X)
        self._Z = normalize(self._svd.transform(X))
        self._norm = normalize
        self.embedder = embedder
        self._E = None
        if embedder is not None:
            try:
                self._E = embedder.encode([u["doc"] for u in self.units])
            except Exception:
                self._E = None
        from .lexicons import tag_arousal
        self._arousal = np.array([(tag_arousal(u["tags"]) or 0.0) for u in self.units])

    def _bm25(self, terms: Dict[str, float], k1=1.2, b=0.75) -> np.ndarray:
        s = np.zeros(self.N)
        for t, w in terms.items():
            n = self.df.get(t, 0)
            if not n:
                continue
            idf = math.log(1 + (self.N - n + 0.5) / (n + 0.5))
            for i, tf in enumerate(self.tf):
                f = tf.get(t)
                if f:
                    s[i] += w * idf * f * (k1 + 1) / (f + k1 * (1 - b + b * self.len[i] / self.avg))
        return s

    def search(self, query: str, k: int = 8, episodes: Optional[List[int]] = None, merge_window: float = 20.0) -> List[Dict]:
        terms, concepts, tag_stems, inten = expand(query)
        phrase = re.sub(r"\s+", " ", query.strip().strip('"“”\'').lower())
        # exact line search ("who are you") works even when every word is a stop word
        phr = np.array([1.0 if len(phrase) >= 4 and phrase in u["text"].lower() else 0.0 for u in self.units])
        if not terms and not concepts and not phr.any():
            return []
        bm = self._bm25(terms) if terms else np.zeros(self.N)
        bm = bm / (bm.max() or 1.0)
        if terms:
            qv = self._norm(self._svd.transform(self._tfv.transform([" ".join(t for t, w in terms.items() if w >= 0.5)])))
            lsa = np.clip((self._Z @ qv.T).ravel(), 0, 1)
        else:
            lsa = np.zeros(self.N)
        tagm = np.array([min(1.0, sum(1 for t in u["tags"] + u["ctx_tags"] for s in tag_stems if s in t) / 2) for u in self.units]) if tag_stems else np.zeros(self.N)
        score = 0.55 * bm + 0.30 * lsa + 0.15 * tagm + 0.6 * phr
        if self._E is not None:
            try:
                qe = self.embedder.encode([query])[0]
                dense = np.clip(self._E @ qe / (np.linalg.norm(self._E, axis=1) * np.linalg.norm(qe) + 1e-9), 0, 1)
                score = 0.6 * score + 0.4 * dense
            except Exception:
                pass
        if inten:
            score *= (0.75 + 0.5 * (self._arousal if inten > 0 else 1 - self._arousal))
        if episodes:
            score = np.where(np.isin([u["episode"] for u in self.units], episodes), score, 0)
        order = np.argsort(-score)
        hits = []
        for i in order:
            if score[i] <= 0.05 or len(hits) >= k:
                break
            u = self.units[i]
            if any(h["episode"] == u["episode"] and abs(h["t"] - u["start"]) < merge_window for h in hits):
                continue
            matched = sorted({t for t in terms if self.tf[i].get(t)}, key=lambda t: -terms[t])[:6]
            why = (["exact line"] if phr[i] else []) + ([f"concept: {', '.join(concepts)}"] if concepts else []) + ([f"words: {', '.join(matched)}"] if matched else [])
            if tagm[i] > 0:
                why.append("delivery: " + ", ".join(u["tags"][:2] or u["ctx_tags"][:2]))
            if lsa[i] > 0.4 and not matched:
                why.append("related wording (LSA)")
            from .parser import fmt_ts
            hits.append({"score": round(float(score[i]), 3), "episode": u["episode"], "t": u["start"], "at": fmt_ts(u["start"]),
                         "kind": u["kind"], "speaker": u["speaker"].title(), "tags": u["tags"], "text": u["text"],
                         "matched": why, "clip": self.clip_around(u["episode"], u["start"], u["end"])})
        return hits

    def clip_around(self, ep: int, t0: float, t1: float, min_d=20.0, max_d=60.0, ideal=(25.0, 45.0)) -> Optional[Dict]:
        """Best legal 20-60 s window containing [t0, t1]: maximises the run's own hook x cliffhanger scores."""
        from .parser import fmt_ts
        H = [(t, p) for t, p in self.hooks.get(ep, []) if t <= t0 + 0.05 and t >= t1 - max_d]
        C = [(t, p) for t, p in self.cliffs.get(ep, []) if t >= t1 - 0.05 and t <= t0 + max_d]
        best = None
        for s, hp in H:
            for e, cp in C:
                d = e - s
                if d < min_d or d > max_d:
                    continue
                fit = 1.0 if ideal[0] <= d <= ideal[1] else 0.9
                v = math.sqrt(hp * cp) * fit
                if best is None or v > best[0]:
                    best = (v, s, e, hp, cp)
        if best is None:
            return None
        v, s, e, hp, cp = best
        return {"episode": ep, "start": fmt_ts(s), "end": fmt_ts(e), "start_s": round(s, 2), "end_s": round(e, 2),
                "duration_s": round(e - s, 1), "hook_pct": round(hp, 3), "cliff_pct": round(cp, 3), "quality": round(v, 3)}


# ---------------------------------------------------------------- optional dense embeddings
class Embedder:
    """Wraps model2vec / sentence-transformers if installed. Set PROMOFINDER_EMBED_MODEL to a model name or a
    local folder (e.g. minishlab/potion-base-8M, or sentence-transformers/all-MiniLM-L6-v2)."""
    def __init__(self, name: str):
        self.name = name
        try:
            from model2vec import StaticModel
            self.m = StaticModel.from_pretrained(name); self.kind = "model2vec"
        except Exception:
            from sentence_transformers import SentenceTransformer
            self.m = SentenceTransformer(name); self.kind = "sentence-transformers"

    def encode(self, texts):
        return np.asarray(self.m.encode(list(texts)), dtype=float)


def default_embedder():
    name = os.environ.get("PROMOFINDER_EMBED_MODEL", "").strip()
    if not name:
        return None
    try:
        return Embedder(name)
    except Exception:
        return None


_CACHE: Dict[str, ShowSearch] = {}


def load_search(run_dir: str) -> ShowSearch:
    p = os.path.join(run_dir, "show_index.json")
    key = p + str(os.path.getmtime(p))
    if key not in _CACHE:
        if len(_CACHE) > 4:
            _CACHE.clear()
        with open(p, encoding="utf-8") as fh:
            _CACHE[key] = ShowSearch(json.load(fh), default_embedder())
    return _CACHE[key]


def search_run(run_dir: str, query: str, k: int = 8) -> List[Dict]:
    return load_search(run_dir).search(query, k=k)
