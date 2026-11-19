"""Minimal Dawid-Skene style generative label model for binary weak supervision.

Labeling functions (LFs) vote +1 / -1 / 0 (abstain). We estimate each LF's
accuracy without ground truth by EM, assuming conditional independence given the
latent label (the standard Snorkel assumption), and output P(y=1 | votes).
"""
import numpy as np


class LabelModel:
    def __init__(self, n_iter=100, prior=None, clip=(0.55, 0.97)):
        self.n_iter, self.prior, self.clip = n_iter, prior, clip

    def fit(self, Lm: np.ndarray):
        n, m = Lm.shape
        acc = np.full(m, 0.7)
        pi = self.prior if self.prior is not None else 0.3
        for _ in range(self.n_iter):
            p = self._posterior(Lm, acc, pi)
            new = np.empty(m)
            for j in range(m):
                nz = Lm[:, j] != 0
                if nz.sum() == 0:
                    new[j] = 0.5; continue
                agree = np.where(Lm[nz, j] == 1, p[nz], 1 - p[nz])
                new[j] = agree.mean()
            acc = np.clip(new, *self.clip)
            if self.prior is None:
                pi = float(np.clip(p.mean(), 0.05, 0.6))
        self.acc_, self.pi_ = acc, pi
        return self

    @staticmethod
    def _posterior(Lm, acc, pi):
        la, lb = np.log(acc), np.log(1 - acc)
        pos = np.where(Lm == 1, la, np.where(Lm == -1, lb, 0)).sum(1) + np.log(pi)
        neg = np.where(Lm == -1, la, np.where(Lm == 1, lb, 0)).sum(1) + np.log(1 - pi)
        return 1 / (1 + np.exp(neg - pos))

    def predict_proba(self, Lm):
        return self._posterior(Lm, self.acc_, self.pi_)
