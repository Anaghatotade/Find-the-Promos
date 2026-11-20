import json, os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
from promofinder.search import ShowSearch
idx = json.load(open(sys.argv[1] + "/show_index.json"))
Q = json.load(open(sys.argv[2]))["queries"]
t = time.time(); S = ShowSearch(idx); print("index built in %.1fs, %d beats" % (time.time() - t, S.N))
def run(mode):
    hit1 = hit5 = mrr = 0
    for q in Q:
        if mode == "bm25_plain":   # baseline: keyword BM25 only, no expansion, no LSA, no tags
            from promofinder.search import toks
            terms = {w: 1.0 for w in toks(q["q"])}
            sc = S._bm25(terms); order = np.argsort(-sc); eps = []
            for i in order:
                if sc[i] <= 0 or len(eps) >= 5: break
                eps.append(S.units[i]["episode"])
        else:
            eps = [h["episode"] for h in S.search(q["q"], k=5)]
        rel = {r + d for r in q["relevant"] for d in (-1, 0, 1)}
        ranks = [i for i, e in enumerate(eps) if e in rel]
        hit1 += bool(ranks and ranks[0] == 0); hit5 += bool(ranks); mrr += (1 / (ranks[0] + 1)) if ranks else 0
    n = len(Q); return {"mode": mode, "hit@1": f"{hit1}/{n}", "hit@5": f"{hit5}/{n}", "MRR@5": round(mrr / n, 3)}
for m in ("bm25_plain", "hybrid"):
    print(run(m))
for q in ["find betrayal scenes", "strong emotional confrontations", "tender romantic moment between the leads"]:
    print("\nQ:", q)
    for h in S.search(q, k=4):
        c = h["clip"]
        print(f"  {h['score']:.2f} E{h['episode']} {h['at']} {h['speaker']}: {h['text'][:70]} | {'; '.join(h['matched'])} | clip {c and (c['start'], c['end'], c['duration_s'])}")
