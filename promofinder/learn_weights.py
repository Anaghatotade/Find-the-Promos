"""Re-fit component weights from editor ✓/✗ feedback (human-in-the-loop).

Feedback lines (jsonl) look like: {"id":..., "vote":"up"|"down", "components":{"hook":..,...}}
We fit a logistic regression on log(component) features - which is exactly the
weighted-geometric-mean scoring rule - and print weights normalised to the defaults'
scale. Needs at least ~30 votes with both classes before suggesting changes.
"""
import argparse, json, math, sys
import numpy as np
from sklearn.linear_model import LogisticRegression

KEYS = ["hook", "cliff", "standalone", "arc", "premise"]


def fit(rows, min_votes=30):
    X = np.array([[math.log(max(r["components"][k], 0.02)) for k in KEYS] for r in rows])
    y = np.array([1 if r["vote"] == "up" else 0 for r in rows])
    if len(rows) < min_votes or len(set(y)) < 2:
        return None, f"need >= {min_votes} votes with both ✓ and ✗ (have {len(rows)})"
    lr = LogisticRegression(C=1.0, max_iter=1000).fit(X, y)
    w = np.clip(lr.coef_.ravel(), 0, None)
    if w.sum() == 0:
        return None, "no component predicts editor approval"
    w = w / w.sum() * 3.9  # same total as defaults (1+1+0.8+0.6+0.5)
    return dict(zip(KEYS, np.round(w, 2).tolist())), "ok"


def main(argv=None):
    ap = argparse.ArgumentParser(); ap.add_argument("feedback", nargs="?", default="feedback/feedback.jsonl")
    a = ap.parse_args(argv)
    rows = [json.loads(l) for l in open(a.feedback, encoding="utf-8") if l.strip()]
    last = {}
    for r in rows:
        last[r["id"]] = r  # latest vote per promo wins
    W, msg = fit(list(last.values()))
    print(msg if W is None else "suggested weights (paste into config.yaml):\n" + json.dumps({"weights": W}, indent=2))


if __name__ == "__main__":
    main()
