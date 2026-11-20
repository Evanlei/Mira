"""Time-split evaluation of the win model against the baselines (spec §8)."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import numpy as np

from . import patches as patchlog
from .baselines import Coin, DeepDraftStyle, MapWinRate
from .dataset import DEFAULT_RANK_FACTOR, Matches
from .winmodel import DEFAULT_L2, WinModel

# Candidate L2 values per group, in pseudo-games. "pair" sets synergy and matchup (all-mode terms);
# their per-mode adjustments get 3x that.
L2_GRID = {
    "global": [3.0, 30.0, 100.0, 300.0],
    "mode": [30.0, 100.0, 300.0],
    "map": [10.0, 30.0, 100.0, 300.0],
    "pair": [100.0, 300.0, 1000.0, 3000.0],
}


# -- metrics ------------------------------------------------------------------

def log_loss(y: np.ndarray, p: np.ndarray) -> np.ndarray:
    p = np.clip(p, 1e-12, 1 - 1e-12)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def calibration_error(y: np.ndarray, p: np.ndarray, bins: int = 10) -> float:
    """Expected calibration error over equal-count bins of predicted probability."""
    order = np.argsort(p)
    err = 0.0
    for chunk in np.array_split(order, bins):
        if len(chunk):
            err += len(chunk) * abs(p[chunk].mean() - y[chunk].mean())
    return err / len(p)


@dataclass
class Score:
    name: str
    log_loss: float
    brier: float
    accuracy: float
    ece: float
    per_match_loss: np.ndarray = field(repr=False)


def score(name: str, y: np.ndarray, p: np.ndarray) -> Score:
    ll = log_loss(y, p)
    return Score(name, ll.mean(), ((p - y) ** 2).mean(), ((p > 0.5) == (y == 1)).mean(),
                 calibration_error(y, p), ll)


def paired_bootstrap(a: np.ndarray, b: np.ndarray, n: int = 2000, seed: int = 0) -> tuple[float, float, float]:
    """Mean of (a - b) per-match loss and its 95% bootstrap interval. Negative = a is better."""
    rng = np.random.default_rng(seed)
    d = a - b
    means = np.concatenate([
        d[rng.integers(0, len(d), size=(min(100, n - i), len(d)))].mean(axis=1) for i in range(0, n, 100)
    ])
    return d.mean(), np.percentile(means, 2.5), np.percentile(means, 97.5)


# -- splitting ----------------------------------------------------------------

def _parse(t: str) -> datetime:
    return datetime.strptime(t, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def time_split(m: Matches, test_days: float = 7.0, max_test_frac: float = 0.3,
               fallback_frac: float = 0.2) -> tuple[np.ndarray, str]:
    """Boolean test mask: matches in the last ``test_days``. If that would be more than
    ``max_test_frac`` of the data (short history), use the newest ``fallback_frac`` instead."""
    newest = _parse(m.times[-1])
    cutoff = (newest - timedelta(days=test_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    mask = np.array([t > cutoff for t in m.times])
    if mask.mean() <= max_test_frac:
        return mask, f"last {test_days:g} days (after {cutoff})"
    k = int(round(len(m) * (1 - fallback_frac)))
    mask = np.zeros(len(m), dtype=bool)
    mask[k:] = True
    return mask, (f"newest {fallback_frac:.0%} of matches by time (from {m.times[k]}); "
                  f"the history is too short for a {test_days:g}-day test window")


# -- training -----------------------------------------------------------------

def weights_for(m: Matches, patches, half_life_days: float, pre_patch_factor: float,
                rank_factor: float = DEFAULT_RANK_FACTOR) -> np.ndarray:
    """Recency x patch x lobby-rank weight per match."""
    return np.array(patchlog.match_weights(
        m.times, m.names_per_match(), patches, reference=m.times[-1],
        half_life_days=half_life_days, pre_patch_factor=pre_patch_factor)) * m.rank_weights(rank_factor)


def _l2_from(choice: dict) -> dict:
    pair = choice["pair"]
    return {**DEFAULT_L2, "global": choice["global"], "mode": choice["mode"], "map": choice["map"],
            "synergy": pair, "matchup": pair, "synergy_mode": 3 * pair, "matchup_mode": 3 * pair}


def tune_l2(train: Matches, weights: np.ndarray, val_frac: float = 0.2, passes: int = 2) -> tuple[dict, list]:
    """Coordinate descent over L2_GRID: tune one group at a time (others fixed), ``passes`` times.
    Scored by log loss on the newest ``val_frac`` of the training data."""
    k = int(round(len(train) * (1 - val_frac)))
    fit_part, val_part = train.subset(slice(0, k)), train.subset(slice(k, None))
    cache: dict[tuple, float] = {}

    def val_loss(choice: dict) -> float:
        key = tuple(choice[g] for g in L2_GRID)
        if key not in cache:
            model = WinModel.fit(fit_part, weights[:k], _l2_from(choice))
            cache[key] = log_loss(val_part.y, model.predict(val_part)).mean()
        return cache[key]

    choice = {"global": 30.0, "mode": 100.0, "map": 100.0, "pair": 1000.0}
    for _ in range(passes):
        for group, values in L2_GRID.items():
            choice[group] = min(values, key=lambda v: val_loss({**choice, group: v}))
    history = sorted((loss, dict(zip(L2_GRID, key))) for key, loss in cache.items())
    return _l2_from(choice), history


@dataclass
class Report:
    split: str
    n_train: int
    n_test: int
    l2: dict
    scores: list[Score]
    comparisons: list[tuple[str, float, float, float]]  # (baseline, mean diff, lo, hi)
    passes: bool
    reasons: list[str]
    n_train_masters: int = 0


MASTERS_ONLY = "Mira, all-Masters lobbies only"


def run(m: Matches, patches=(), test_days: float = 7.0, half_life_days: float = 28.0,
        pre_patch_factor: float = 0.1, tune: bool = True, seed: int = 0,
        rank_factor: float = DEFAULT_RANK_FACTOR) -> Report:
    """Train on everything before the split (lower lobbies weighted down); test only on
    all-Masters matches after it. Baselines see all-Masters training matches only, as
    before; "Mira, all-Masters only" shows whether the lower lobbies help."""
    test_mask, split_desc = time_split(m, test_days)
    train, test = m.subset(~test_mask), m.subset(test_mask & m.masters_mask())
    masters_train = train.subset(train.masters_mask())
    w_train = weights_for(train, list(patches), half_life_days, pre_patch_factor, rank_factor)
    l2 = tune_l2(train, w_train)[0] if tune else dict(DEFAULT_L2)
    model = WinModel.fit(train, w_train, l2)

    scores = [score(b.name, test.y, b.fit(masters_train).predict(test))
              for b in (Coin(), MapWinRate(), DeepDraftStyle())]
    has_lower = len(masters_train) < len(train)
    if has_lower:
        w_m = weights_for(masters_train, list(patches), half_life_days, pre_patch_factor)
        l2_m = tune_l2(masters_train, w_m)[0] if tune else dict(DEFAULT_L2)
        scores.append(score(MASTERS_ONLY, test.y, WinModel.fit(masters_train, w_m, l2_m).predict(test)))
    mira = score("Mira win model", test.y, model.predict(test))
    scores.append(mira)
    comparisons = [(s.name, *paired_bootstrap(mira.per_match_loss, s.per_match_loss, seed=seed)) for s in scores[:-1]]

    dd = next(c for c in comparisons if c[0] == DeepDraftStyle.name)
    reasons = []
    if dd[3] >= 0:
        reasons.append("log loss is not clearly better than the DeepDraft-style baseline (95% interval includes 0)")
    if mira.ece > 0.03:
        reasons.append(f"calibration error {mira.ece:.3f} > 0.03")
    return Report(split_desc, len(train), len(test), l2, scores, comparisons, not reasons, reasons,
                  len(masters_train))
