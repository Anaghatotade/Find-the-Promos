"""SIMULATION (not real editors): hidden 'editor' weight vectors judge clips from the real 50-clip longlist with
Bradley-Terry noise. Does the learner recover the editor's ranking, and does active pair selection beat random?"""
import json, math, sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from scipy.stats import kendalltau
from promofinder.preferences import rescore, next_pair, learned_weights_for, append_feedback, KEYS, DEFAULT, feat
from promofinder.config import load_config
L = json.load(open(sys.argv[1] + "/promos_longlist.json"))["promos"]
EDITORS = {"clarity-first": {"hook": 0.6, "cliff": 0.9, "standalone": 2.0, "arc": 0.3, "premise": 0.1},
           "cliff-obsessed": {"hook": 0.7, "cliff": 2.2, "standalone": 0.4, "arc": 0.4, "premise": 0.2},
           "intensity-lover": {"hook": 1.2, "cliff": 0.5, "standalone": 0.3, "arc": 1.8, "premise": 0.1}}
TAU = 4.0
PS = float(os.environ.get("PS", "4.0"))
def util(r, w):
    ws = sum(w.values()); c = r["components"]
    return sum(w[k] * math.log(max(c[k], .02)) for k in KEYS) / ws + math.log(c.get("extra_factor", 1))
def evaluate(w_true, w_hat):
    t = [util(r, w_true) for r in L]; h = [util(r, w_hat) for r in L]
    tau = kendalltau(t, h).statistic
    top_t = set(np.argsort(t)[-12:]); top_h = set(np.argsort(h)[-12:])
    return tau, len(top_t & top_h)
def run(editor, strategy, budget, seed):
    rng = np.random.RandomState(seed); w_true = EDITORS[editor]
    cfg = load_config(overrides={"learning": {"min_judgments": 0, "auto_apply": True, "prior_strength": PS}})
    fd = tempfile.mkdtemp(); path = os.path.join(fd, "fb.jsonl")
    ranked = rescore(L, DEFAULT)
    for i in range(budget):
        if strategy == "votes":                 # Use/Reject on the shown list, top-down
            r = ranked[i % 20]
            p = 1 / (1 + math.exp(-TAU * (util(r, w_true) - np.median([util(x, w_true) for x in L]))))
            append_feedback(path, {"type": "vote", "run": "sim", "show": "s", "id": r["id"], "vote": "up" if rng.rand() < p else "down", "components": r["components"]})
            continue
        if strategy == "active":
            a, b, _ = next_pair(ranked, path, cfg, run="sim", top_k=int(os.environ.get("TOPK", "25")))
        else:
            idx = rng.choice(int(os.environ.get("TOPK", "25")), 2, replace=False); a, b = ranked[idx[0]], ranked[idx[1]]
        p = 1 / (1 + math.exp(-TAU * (util(a, w_true) - util(b, w_true))))
        append_feedback(path, {"type": "pair", "run": "sim", "show": "s", "a": {"id": a["id"], "components": a["components"]},
                               "b": {"id": b["id"], "components": b["components"]}, "winner": "a" if rng.rand() < p else "b"})
    w = learned_weights_for(path, cfg)["fitted"] if budget else DEFAULT
    return evaluate(w_true, w)
res = {}
for budget in (0, 10, 20, 40):
    for strat in os.environ.get("STRATS", "votes,random,active").split(","):
        if budget == 0 and strat != "active":
            continue
        taus, tops = [], []
        for ed in EDITORS:
            for seed in range(12):
                t, o = run(ed, strat, budget, seed); taus.append(t); tops.append(o)
        res[f"{budget:>2} {strat if budget else 'defaults'}"] = (round(float(np.mean(taus)), 3), round(float(np.mean(tops)), 2))
        print(f"budget {budget:>2} clicks  {strat if budget else 'default weights':>15}: Kendall tau {np.mean(taus):.3f}  top-12 overlap {np.mean(tops):.2f}/12")
print(json.dumps(res))
