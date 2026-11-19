"""Default configuration. Override any key with a YAML file (see config.yaml)."""
import copy, yaml

DEFAULTS = {
    "min_dur": 20.0, "max_dur": 60.0,
    "ideal_dur": [25.0, 45.0],          # sweet spot for Reels/TikTok promos
    "top_n": 12, "longlist_n": 50,
    "fps": 30,                          # timecode rate for EDL / cut-list export
    "max_per_episode": 2,
    "mmr_lambda": 0.35,                 # diversity strength
    # weighted geometric mean of component scores (all in 0..1)
    "weights": {"hook": 1.0, "cliff": 1.0, "standalone": 0.8, "arc": 0.6, "premise": 0.5},
    "funnel": {"enabled": True, "late_episode_penalty": 0.12},  # mild spoiler/funnel prior
    "allow_cross_episode": True,
    "allow_cold_open": True,
    "cold_open_penalty": 0.06, "cross_episode_penalty": 0.03,
    "cliff_model": "withheld_payoff",   # withheld_payoff | self_supervised | rules
    "hook_model": "weak_supervision",
    "arousal_mode": "auto",             # auto | tags | fallback | max  (auto: tags if >=50% of lines are tagged)
    "llm": {"enabled": False, "provider": "none", "model": "", "rerank_top_k": 30},
}


def load_config(path=None, overrides=None):
    cfg = copy.deepcopy(DEFAULTS)
    if path:
        with open(path, encoding="utf-8") as fh:
            _merge(cfg, yaml.safe_load(fh) or {})
    if overrides:
        _merge(cfg, overrides)
    return cfg


def _merge(a, b):
    for k, v in b.items():
        if isinstance(v, dict) and isinstance(a.get(k), dict):
            _merge(a[k], v)
        else:
            a[k] = v
