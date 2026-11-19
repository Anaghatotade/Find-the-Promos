"""Learned moment scorers.

* CliffhangerModel - SELF-SUPERVISED per show: the writers end (almost) every
  episode on a cliffhanger, so the final beat of each episode is a positive and
  beats far from any episode end are negatives. Writer meta-annotations
  ("cliffhanger", "cut to black", "fades out", ...) are masked out of inputs and
  positional features are excluded, so the model must learn from the *content*
  of the moment. At inference every episode is scored out-of-fold (cross-fitting)
  so a moment is never scored by a model that saw it as a training label.

* HookModel - WEAK SUPERVISION: transparent labeling functions -> generative label
  model (labelmodel.py) -> discriminative end model on text + features, also
  cross-fitted by episode.
"""
from __future__ import annotations
import numpy as np
from typing import List, Dict
from sklearn.feature_extraction import DictVectorizer
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from scipy.sparse import hstack, csr_matrix
from .labelmodel import LabelModel
from . import lexicons as L

CLIFF_DENSE = ["c_has_dialogue", "c_last_q", "c_last_ellipsis", "c_last_excl", "c_line_lex",
               "c_action_lex", "c_resolve_lex", "c_arousal_max", "c_arousal_last", "c_vader", "c_line_len"]
HOOK_DENSE = ["h_has_dialogue", "h_first_line_at", "h_action_lex", "h_line_lex", "h_arousal_max",
              "h_excl", "h_question", "h_you", "h_vader_abs", "h_establishing", "h_dangling", "h_closeup", "h_empty",
              "h_prev_gap", "h_mid_speech", "h_relief"]


class TextFeatLR:
    """TF-IDF(text) ⊕ standardized dense features -> logistic regression."""
    def __init__(self, dense_keys, use_text=True, use_dense=True, C=1.0):
        self.dense_keys, self.use_text, self.use_dense, self.C = dense_keys, use_text, use_dense, C

    def _X(self, texts, feats, fit=False):
        mats = []
        if self.use_text:
            if fit:
                self.tf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=20000)
                mats.append(self.tf.fit_transform(texts))
            else:
                mats.append(self.tf.transform(texts))
        if self.use_dense:
            D = np.array([[f[k] for k in self.dense_keys] for f in feats], dtype=float)
            if fit:
                self.sc = StandardScaler().fit(D)
            mats.append(csr_matrix(self.sc.transform(D)))
        return hstack(mats).tocsr()

    def fit(self, texts, feats, y, sample_weight=None):
        X = self._X(texts, feats, fit=True)
        self.lr = LogisticRegression(C=self.C, max_iter=2000, class_weight="balanced")
        self.lr.fit(X, y, sample_weight=sample_weight)
        return self

    def predict_proba(self, texts, feats):
        return self.lr.predict_proba(self._X(texts, feats))[:, 1]


def cliff_rule_score(f: Dict[str, float]) -> float:
    """Transparent baseline / fallback when a show is too small to self-train."""
    s = (1.2 * f["c_last_q"] + 0.8 * f["c_last_ellipsis"] + 0.4 * f["c_last_excl"]
         + 0.35 * min(f["c_line_lex"], 3) + 0.35 * min(f["c_action_lex"], 3)
         - 0.5 * min(f["c_resolve_lex"], 3) + 1.0 * f["c_arousal_last"])
    return float(1 / (1 + np.exp(-(s - 1.0))))


# ---------------- hook labeling functions ----------------
def hook_lfs(f: Dict[str, float]) -> List[int]:
    return [
        1 if f["h_action_lex"] >= 1 else 0,                       # physical shock in action/camera
        1 if f["h_line_lex"] >= 1 else 0,                         # shocking line vocabulary
        1 if f["h_arousal_max"] >= 0.8 else (-1 if f["h_has_dialogue"] and f["h_arousal_max"] <= 0.25 else 0),
        1 if f["h_excl"] >= 1 else 0,                             # exclamation
        1 if (f["h_you"] and (f["h_excl"] or f["h_question"])) else 0,  # direct confrontation
        -1 if (f["h_establishing"] and f["h_action_lex"] == 0) else 0,  # scenic opener
        -1 if f["h_empty"] else 0,                                # nothing happens
        -1 if (not f["h_has_dialogue"] and f["h_action_lex"] == 0) else 0,
        -1 if (f["h_relief"] and f["h_action_lex"] == 0 and f["h_line_lex"] == 0) else 0,  # relief/warmth
    ]

HOOK_LF_NAMES = ["action_shock", "shock_line", "arousal", "exclamation", "confrontation",
                 "establishing(-)", "empty(-)", "no_line_no_action(-)", "relief(-)"]
# NOTE (E2b error analysis): "dangling start" and "mid-speech" were removed from the hook LFs -
# they vetoed real hooks ("They arrested her!"). They now only affect the standalone score.


def cross_fit_predict(model_factory, groups, texts, feats, y, n_folds=5, sample_weight=None, seed=0):
    """Out-of-fold predictions grouped by episode. Returns np.array of probabilities."""
    groups = np.asarray(groups)
    uniq = np.unique(groups)
    rng = np.random.RandomState(seed); rng.shuffle(uniq)
    folds = np.array_split(uniq, min(n_folds, len(uniq)))
    out = np.zeros(len(groups))
    idx_all = np.arange(len(groups))
    for fg in folds:
        te = np.isin(groups, fg); tr = ~te
        ytr = np.asarray(y)[tr]
        if len(np.unique(ytr)) < 2:
            out[te] = 0.5; continue
        m = model_factory()
        sw = None if sample_weight is None else np.asarray(sample_weight)[tr]
        m.fit([texts[i] for i in idx_all[tr]], [feats[i] for i in idx_all[tr]], ytr, sample_weight=sw)
        out[te] = m.predict_proba([texts[i] for i in idx_all[te]], [feats[i] for i in idx_all[te]])
    return out
