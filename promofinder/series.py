"""Show-level context: premise vector, entity introductions, semantic space."""
from __future__ import annotations
import re
import numpy as np
from collections import defaultdict
from sklearn.feature_extraction.text import TfidfVectorizer, ENGLISH_STOP_WORDS
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize
from . import lexicons as L

NAME_RX = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-Z][a-z]{2,})\b")
NOT_NAMES = {"Lady", "Lord", "Sir", "Your", "Grace", "Father", "Mother", "Duke", "Duchess", "God",
             "The", "This", "That", "What", "Why", "How", "Who", "Where", "When", "Then", "Now", "Yes", "No",
             "Please", "Madam", "Majesty", "Highness", "Tomorrow", "Tonight", "Crown", "Constable", "Ten",
             "Manor", "Hall", "House", "Abbey", "Castle", "County", "Estate", "Church", "Chapel", "Court",
             "Council", "King", "Queen", "Prince", "Princess", "Sir", "Mister", "Miss", "Mrs", "Heaven",
             "England", "London", "Monday", "Sunday", "Christmas", "Saint", "Captain", "Master", "Mistress"}


ROLE_WORDS = {"Former", "Groom", "Bride", "Bearded", "Stranger", "Mysterious", "Blond", "Nobleman", "Noblewoman",
              "Maid", "Guard", "Guards", "Royal", "Judge", "High", "Priest", "Elder", "Villager", "Peasant", "Thug",
              "Cap", "Tall", "Third", "Informant", "Official", "Police", "Housekeeper", "Matriarch", "Noble", "Woman",
              "Man", "Boy", "Girl", "Old", "Young", "Aristocratic", "Scarred", "Gown", "Gold", "Dowager", "Loyalist",
              "Scout", "Fighter", "Sentry", "Driver", "Cart", "Butler", "Servant", "Soldier", "Captain", "Doctor",
              "With", "And", "The", "Lady", "Lord", "Father"}


class SeriesIndex:
    def __init__(self, show_name, episodes):
        self.show_name = show_name
        self.episodes = {e.number: e for e in episodes}
        docs = [" ".join(b.text for b in e.blocks if b.kind in ("dialogue", "action")) for e in episodes]
        self.tfidf = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=1, ngram_range=(1, 1))
        X = self.tfidf.fit_transform(docs)
        k = max(2, min(64, X.shape[0] - 1, X.shape[1] - 1))
        self.svd = TruncatedSVD(n_components=k, random_state=0).fit(X)
        # premise: the title is what the promo is ultimately selling
        e1 = episodes[0] if episodes else None
        prem = show_name.replace(".", " ") + " " + (e1.logline if e1 and e1.number == 1 else "")
        self.premise_text = prem
        self.premise_vec = self.tfidf.transform([prem])
        # known character names: speaker-header tokens that are also used capitalised in dialogue
        # (catches sentence-initial mentions such as "Reyes paid them!")
        spk_tokens = {w.title() for e in episodes for b in e.blocks if b.kind == "dialogue"
                      for w in re.findall(r"[A-Za-z]{3,}", b.speaker)}
        dia_caps = {t for e in episodes for b in e.blocks if b.kind == "dialogue" for t in re.findall(r"\b[A-Z][a-z]{2,}\b", b.text)}
        self.known_names = {t for t in spk_tokens & dia_caps if t not in NOT_NAMES and t not in ROLE_WORDS}
        # first appearance of proper names (speakers + capitalised mentions)
        self.first_seen = {}
        for e in episodes:
            for b in e.blocks:
                if b.kind != "dialogue":
                    continue
                for nm in self._names(b.text):
                    self.first_seen.setdefault(nm, e.number)

    def _names(self, text):
        cache = self.__dict__.setdefault("_names_cache", {})
        if text not in cache:
            cache[text] = frozenset(self._names_uncached(text))
        return cache[text]

    def _names_uncached(self, text):
        out = {t for t in re.findall(r"\b[A-Z][a-z]{2,}\b", text) if t in getattr(self, "known_names", ())}
        for sent in re.split(r"(?<=[.!?…])\s+", text):
            toks = re.findall(r"\b[A-Z][a-z]{2,}\b", sent)
            # skip the sentence-initial token (capitalised anyway)
            first = re.match(r"\W*([A-Z][a-z]{2,})", sent)
            for t in toks:
                if first and t == first.group(1) and sent.strip().startswith(t):
                    continue
                if t not in NOT_NAMES:
                    out.add(t)
        return out

    # ---- exact fast path: window TF-IDF from per-line term counts --------------------
    def _block_counts(self, blocks):
        """Term counts per dialogue line (cached). Token streams of ' '.join(lines) are the
        concatenation of each line's tokens, so a window's counts are the sum of its lines'."""
        from sklearn.feature_extraction.text import CountVectorizer
        if not hasattr(self, "_cv"):
            t = self.tfidf
            self._cv = CountVectorizer(vocabulary=t.vocabulary_, stop_words=t.stop_words, lowercase=t.lowercase,
                                       token_pattern=t.token_pattern, ngram_range=t.ngram_range)
            self._row = {}; self._rows = []
        new = list({id(b): b for b in blocks if id(b) not in self._row}.values())
        if new:
            X = self._cv.transform([b.text for b in new])
            for b, i in zip(new, range(len(self._rows), len(self._rows) + len(new))):
                self._row[id(b)] = i
            self._rows.append(X)
            from scipy.sparse import vstack
            self._C = vstack(self._rows).tocsr() if len(self._rows) > 1 else self._rows[0].tocsr()
            self._rows = [self._C]
        return self._C

    def window_tfidf(self, block_lists):
        """Exactly tfidf.transform([' '.join(b.text for b in L) for L in block_lists])."""
        from scipy.sparse import csr_matrix
        flat = [b for L in block_lists for b in L]
        C = self._block_counts(flat) if flat else None
        if C is None:
            return csr_matrix((len(block_lists), len(self.tfidf.vocabulary_)))
        rows, cols = [], []
        for i, L in enumerate(block_lists):
            for b in L:
                rows.append(i); cols.append(self._row[id(b)])
        M = csr_matrix((np.ones(len(rows), dtype=C.dtype), (rows, cols)), shape=(len(block_lists), C.shape[0]))
        counts = (M @ C).tocsr(); counts.sum_duplicates(); counts.sort_indices()
        return self.tfidf._tfidf.transform(counts)

    def embed_windows(self, block_lists):
        return normalize(self.svd.transform(self.window_tfidf(block_lists)))

    def premise_sim_windows(self, block_lists):
        V = self.window_tfidf(block_lists)
        return np.asarray((normalize(V) @ normalize(self.premise_vec).T).todense()).ravel()

    def embed(self, texts):
        return normalize(self.svd.transform(self.tfidf.transform(texts)))

    def premise_sim(self, texts):
        V = self.tfidf.transform(texts)
        return np.asarray((normalize(V) @ normalize(self.premise_vec).T).todense()).ravel()

    def unintroduced_refs(self, ep_no, dia_blocks):
        """Names mentioned in-window that were introduced in an EARLIER episode and who do
        not themselves speak in the window: a stranger will not know who they are."""
        speakers = " ".join(b.speaker.title() for b in dia_blocks)
        refs = set()
        for b in dia_blocks:
            for nm in self._names(b.text):
                if self.first_seen.get(nm, ep_no) < ep_no and nm not in speakers:
                    refs.add(nm)
        return refs
