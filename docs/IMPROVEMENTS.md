# PromoFinder v2: engineering notes

These notes cover what was found in the v1.3 audit, what was built and why, what was rejected, and how it was measured.
The development show is confidential, so this file reports aggregate numbers only.

## 1. Audit of v1.3 (what was there)

**Already strong, so kept as is**

- Legal cut points: a clip never splits a line of dialogue.
- Weak-supervision hook scorer (labeling functions → Dawid–Skene → text classifier, cross-fitted by episode).
- Withheld-payoff cliffhanger scorer.
- Weighted-geometric-mean ranking.
- MMR diversity.
- Stability under weight perturbation.
- CMX3600 EDLs.
- Careful ZIP error handling.
- Deterministic results.
- The existing 47 tests.

**Gaps found**

| Area | Finding |
|---|---|
| Spoilers | Only a position prior (late episodes ×0.88) and a blanket "late-series" flag. Episode 16 can unmask the villain and still rank first. On the development show, 2 of the top 12 and 5 of the longlist showed pre-labelled twists. |
| Feedback | Use/Reject votes were stored but never changed anything unless someone ran a CLI and pasted weights into YAML. Votes on similar, all-good clips also carry little information (confirmed in simulation). |
| Formats | Only the bold-header production format was read. Every other file in an upload was ignored. |
| Audience | One ranking for everyone, while paid social is bought per audience and creatives are A/B-tested. |
| Discovery | Editors could not ask for a specific kind of moment. |
| LLM | Two SDKs as optional installs, no cache, and pointwise scoring only. Pointwise LLM scores are the least reliable form of LLM judgment. |
| Evaluation | No harness to check a run against its source scripts, compare versions, or test formats. |
| Ops | Manual setup. Python 3.10 crashed on a ZIP edge case (`metadata_encoding` is 3.11+). |

## 2. The suggested features: decisions

| Suggestion | Decision | Why |
|---|---|---|
| Audience-specific ranking | **Reframed, then built** | A show's genre is fixed, so "rank for romance vs thriller" only makes sense as *angles on the same show*. Built as per-clip angle vectors, audience profiles that re-order close calls (bounded at 0.85–1.15×, so a profile cannot rescue a clip with no hook), and a **portfolio** with one clip per angle, i.e. the creatives an ad team actually A/B-tests. |
| Semantic scene search | **Built** | Search uses hybrid retrieval, and every hit becomes a *legal, scored 20–60 s clip*. That turns search into promo creation rather than a script grep. |
| Spoiler-aware scoring | **Built, with a premise exemption** | The common assumption that "reveals are bad" is wrong for this genre: the title often *is* the reveal (e.g. "…Married a Billionaire"), and ads routinely show it. Reveals the title promises are treated as a premise payoff. Only twists and endings are penalised, with a tolerance setting. |
| Pairwise preference learning | **Built, active selection is the key** | Simulation showed random pairs help slowly and Use/Reject votes barely help. Uncertainty-driven pair selection gives the gains (§4). |
| Narrative-context scoring | **Mostly already present; not rebuilt** | v1.3 already uses the withheld next beat, opens-on-an-unheard-question, names introduced in earlier episodes, and cross-episode bridges. A larger rewrite had no evaluation data to justify it. Added: honorific-aware speaker identity ("LADY MARA" = "MARA"), and spoiler context across the series. |
| Audience response prediction | **Rejected as a model; built the data path** | With zero real engagement data, any CTR prediction would be invented. Built instead: import measured ad results, show them as *Measured* (visibly separate from model scores), and let them train the same learner with confidence weighted by sampling error. The UI says plainly that scores are not CTR predictions. |

## 3. Independent additions

1. **Format adapters** (inline, SRT/VTT, JSON, production variants) with content sniffing. The original strict parser runs first, so production-format results are byte-identical.
2. **Evaluation harness** (`evaluate.py`): hard constraints against the source scripts, EDL↔JSON agreement, spoiler exposure, and run agreement. It made every number in the README reproducible.
3. **Pre-registered silver labels**: reveal labels and search queries were written from loglines *before* the code they test existed.
4. **Position-swap debiasing** for LLM pairwise judgments (LLM judges favour the first option shown). A verdict counts only if it survives the swap.
5. **Stdlib HTTP LLM client** with free-tier presets (Gemini, Groq, OpenRouter, Ollama), a SQLite response cache, and `.env`-only keys that are never written to outputs.
6. **Re-rank without re-running**: exported components include the non-learned factors, so learned weights re-order a finished run instantly (to within ±0.0002, the rounding of stored components).
7. **One-command launchers** with a dependency hash, `.venv` self-repair and free-port fallback; a portable cp437 fix for Python 3.10.

## 4. Key ML decisions

- **The learner reuses the ranker's own formula.** Utility = Σ wₖ·log(componentₖ) is exactly the weighted geometric mean, and Bradley–Terry on it is a logistic regression on log-component differences. Learned weights drop into config, so there is no second model to trust. The prior sits at the hand-set defaults with bounds w ≥ 0.
- **Prior strength was chosen by simulation, not by guessing.** At 4.0, 40 judgments changed nothing. At 0.05, the learner overfit and Kendall τ fell from 0.731 to 0.64. At 1.0, with active selection over the 50-clip longlist, τ rose 0.731 → 0.759 → 0.786 → 0.815 at 10/20/40 judgments. Learned weights apply only after 10 judgments.
- **Active pair selection**: the next pair maximises p(1−p) · Δxᵀ Σ Δx, using a Laplace-approximate posterior covariance. In other words, it picks the pair where the model is least sure of the outcome *and* the outcome would move the weights most.
- **Spoiler severity** = 0.6·cue strength + 0.6·logline overlap. A cue counts only if it is new relative to the free episodes and the premise ("You are my father!" in episode 5 is not a reveal). Risk below 0.3 never penalises. The penalty is 1 − w·(risk − 0.3)/0.7, with w = 0.6 / 0.35 / 0 for strict / balanced / off.
- **Search** = 0.55·BM25 (with synonym and concept expansion) + 0.30·LSA fitted on the show's own beats + 0.15·delivery-tag match + exact-phrase bonus. A dense embedding model is optional and blended at 0.4 when present. All of this works offline.
- **Why not embeddings or an LLM everywhere?** The model download was blocked in the build environment, and any download is a reliability risk for a one-click local app. The lexical, LSA and tag stack reached 16/16 on the paraphrase set (optimistic, see limitations), stays explainable ("matched: concept betrayal; delivery: accusing"), and costs nothing per query.

## 5. Evaluation summary

Real runs on the 50-episode development show; full numbers are in the README.

- Hard constraints: 0 violations for v1.3 and v2, on the top 12 and the longlist.
- Labelled twist or ending shown: top 12 went from 2 to 1, longlist from 5 to 2. *Strict* did not reduce it further (top 12: 1, longlist: 3). The remaining miss is a twist phrased without any cue word.
- Spoiler detector recall at episode level: 1/9 from cues alone, 8/9 with loglines (optimistic, because the labels also came from loglines).
- v2 keeps 9 of 12 v1.3 picks exactly (10 of 12 by moment), with the same #1.
- Format robustness: identical top 12 for JSON, inline and unbolded-production copies. With tags removed, 8 of 12 moments; as SRT, 4 of 12.
- Runtime: 5.9 s → 8.0 s for 51,598 candidates.

## 6. What I would build next with Kuku's data

1. **Calibrate on real outcomes.** Once a few hundred promos have impressions and clicks, fit the learner on measured CTR and report rank correlation between score and CTR on held-out shows. That would be the first true quality number.
2. **Editor A/B sessions across 5–10 shows** to learn house taste, then compare learned and default weights on new shows.
3. **Annulment- and inheritance-style twist cues**, and a small classifier for reveals trained on logline-labelled lines across many shows.
4. **Multimodal check** with the episode video, where available: confirm the first 3 s actually show the action (shot type, motion, faces) and that the cut lands on a frame worth freezing.
5. **Shared feedback store** (SQLite or Postgres) and a job queue, if more than one editor uses one instance.
