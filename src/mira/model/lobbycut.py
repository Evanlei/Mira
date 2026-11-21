"""Choose the lowest lobby rank to train on, so lower lobbies drop out by themselves once
there are enough Masters games.

Each candidate cut (Legendary I, Legendary III, Masters I) trains a win model on the same matches
before the split and is scored on the same newest all-Masters matches (evaluate.masters_split).
Starting from Masters only, a looser cut is taken only if it beats the current choice with a 95%
paired-bootstrap interval below 0 *and* its per-brawler win-rate error is no worse than the
Masters-only model's (plus a small tolerance). Lower lobbies are a stopgap: while the Masters
data is thin they help (Nov 2026: 0.6821 vs 0.6850 log loss), and when that gain is no longer
clear the cut tightens.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .dataset import MASTERS, Matches
from .evaluate import brawler_error, log_loss, masters_split, paired_bootstrap, weights_for
from .winmodel import WinModel

CUTS = (MASTERS, 18, 16)        # strictest first: Masters I, Legendary III, Legendary I
ERROR_TOLERANCE = 0.001         # per-brawler error may exceed Masters-only by at most 0.1 point


@dataclass
class CutRow:
    cut: int
    n_train: int
    log_loss: float
    vs_choice: tuple[float, float, float]  # (mean diff, lo, hi) vs the cut chosen before it
    brawler_error: float
    taken: bool


def choose(m: Matches, l2: dict, patches=(), half_life_days: float = 28.0, pre_patch_factor: float = 0.1,
           rank_factor: float = 0.5, cuts=CUTS) -> tuple[int, list[CutRow]]:
    """(chosen minimum lobby rank, one row per cut). ``m`` must hold every lobby down to min(cuts)."""
    train_mask, test_mask, _ = masters_split(m)
    test = m.subset(test_mask)
    w = weights_for(m, list(patches), half_life_days, pre_patch_factor, rank_factor)
    ranks = m.ranks()
    rows: list[CutRow] = []
    choice, choice_loss, ref_error = None, None, None
    for cut in cuts:
        sel = train_mask & (ranks >= cut)
        if sel.sum() < 200 or not len(test) or (rows and sel.sum() == rows[-1].n_train):
            continue  # too little data, or the same matches as the stricter cut
        p = WinModel.fit(m.subset(sel), w[sel], l2).predict(test)
        loss = log_loss(test.y, p)
        err = brawler_error(test, p)[0]
        if choice is None:  # the strictest cut is the reference
            ref_error = err
            rows.append(CutRow(cut, int(sel.sum()), float(loss.mean()), (0.0, 0.0, 0.0), err, True))
            choice, choice_loss = cut, loss
            continue
        d = paired_bootstrap(loss, choice_loss)
        ok = d[2] < 0 and not (err > ref_error + ERROR_TOLERANCE)
        rows.append(CutRow(cut, int(sel.sum()), float(loss.mean()), d, err, ok))
        if ok:
            choice, choice_loss = cut, loss
    for r in rows:
        r.taken = r.cut == choice
    return (choice if choice is not None else min(cuts)), rows


def format_rows(rows: list[CutRow], names: dict[int, str]) -> str:
    out = ["Lowest lobby rank to train on (same newest all-Masters test games; a looser cut must beat the "
           "current choice with a 95% CI below 0 and keep per-brawler error within 0.1 pt of Masters-only):"]
    for r in rows:
        d, lo, hi = r.vs_choice
        out.append(f"  {names.get(r.cut, str(r.cut)):<14} train {r.n_train:>8,}  log loss {r.log_loss:.4f}  "
                   f"vs previous choice {d:+.4f} [{lo:+.4f}, {hi:+.4f}]  brawler error {r.brawler_error:.2%}"
                   + ("  <-" if r.taken else ""))
    return "\n".join(out)
