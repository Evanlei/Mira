"""model.json loader: win scoring and pick probabilities, no numpy."""

from __future__ import annotations

import json
import math
from pathlib import Path


def _norm(s: str) -> str:
    return "".join(ch for ch in s.lower() if ch.isalnum())


class Model:
    def __init__(self, data: dict, tier: int | None = None):
        """``tier``: the rank tier to draft for (index into data["tiers"]); default_tier if None."""
        self.data = data
        self.tiers = data.get("tiers", [])
        self.tier = data.get("default_tier", 0) if tier is None else tier
        self.names = [b["name"] for b in data["brawlers"]]
        self.B = len(self.names)
        self._by_name = {_norm(n): i for i, n in enumerate(self.names)}
        self.maps = [(m["mode"], m["map"]) for m in data["maps"]]
        self.modes = data["modes"]
        self._mode_of_map = [self.modes.index(mode) for mode, _ in self.maps]

        w = data["win_model"]
        self.g = w["global"]
        self.s_mode = w["mode"]
        self.s_map = w["map"]
        self.syn = {(i, j): v for i, j, v in w["synergy"]}
        self.syn_mode = {(i, j, k): v for i, j, k, v in w["synergy_mode"]}
        self.mu = {(i, j): v for i, j, v in w["matchup"]}
        self.mu_mode = {(i, j, k): v for i, j, k, v in w["matchup_mode"]}
        self.s_tier = w.get("tier")            # [B][n_tiers] or None (older models)
        self.s_tier_mode = w.get("tier_mode")  # [B][n_tiers][n_modes]

        p = data.get("pick_model")
        if p:
            self.alpha, self.beta = p["alpha"], p["beta"]
            self.log_base = p["log_base"]  # [B][n_maps]
            if "log_base_tier" in p:
                self.log_base = p["log_base_tier"][self.tier]
            self.ally = {}
            for i, j, v in p["ally_lift"]:
                self.ally[i, j] = self.ally[j, i] = v
            self.enemy = {}
            for i, j, v in p["enemy_lift"]:
                self.enemy[i, j] = self.enemy[j, i] = v
        self.games = data.get("games", {})

        # How the search ranks our own candidates (see adjust()). Older model.json files have no
        # "ranking" block: kappa = gamma = 0, so they rank by the win model alone, as before.
        r = data.get("ranking") or {}
        self.kappa = r.get("kappa", 0.0)
        self.gamma = r.get("gamma", 0.0) if p else 0.0
        sd = r.get("strength_sd")  # [n_tiers][B][n_maps]
        self.sd = sd[self.tier] if sd else None
        # Pro drafts (Liquipedia): rho weighs the pro pick rate in our ranking, ban_lambda the pro
        # ban rate in ban suggestions. Without a "pro" block both are off.
        pro = data.get("pro") or {}
        self.pro_log_pick = pro.get("log_pick")  # [B][n_maps]
        self.pro_ban = pro.get("ban")            # [B][n_maps]
        self.rho = r.get("rho", 0.0) if self.pro_log_pick else 0.0
        self.ban_lambda = r.get("ban_lambda", 0.0) if self.pro_ban else 0.0

    @classmethod
    def load(cls, path: str | Path, tier: int | None = None) -> "Model":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")), tier)

    # -- lookups ------------------------------------------------------------

    def brawler(self, name: str) -> int:
        key = _norm(name)
        if key in self._by_name:
            return self._by_name[key]
        matches = [i for k, i in self._by_name.items() if k.startswith(key)]
        if len(matches) == 1:
            return matches[0]
        hint = f" (did you mean {', '.join(self.names[i] for i in matches[:5])}?)" if matches else ""
        raise KeyError(f"unknown brawler {name!r}{hint}")

    def map(self, name: str) -> int:
        key = _norm(name)
        hits = [i for i, (_, m) in enumerate(self.maps) if _norm(m) == key]
        if not hits:
            hits = [i for i, (_, m) in enumerate(self.maps) if _norm(m).startswith(key)]
        if len(hits) == 1:
            return hits[0]
        raise KeyError(f"unknown or ambiguous map {name!r}; known: {', '.join(m for _, m in self.maps)}")

    # -- win model ----------------------------------------------------------

    def strength(self, b: int, mp: int) -> float:
        k = self._mode_of_map[mp]
        s = self.g[b] + self.s_mode[b][k] + self.s_map[b][mp]
        if self.s_tier is not None:
            s += self.s_tier[b][self.tier] + self.s_tier_mode[b][self.tier][k]
        return s

    def synergy(self, a: int, b: int, mp: int) -> float:
        i, j = (a, b) if a < b else (b, a)
        k = self._mode_of_map[mp]
        return self.syn.get((i, j), 0.0) + self.syn_mode.get((i, j, k), 0.0)

    def matchup(self, a: int, b: int, mp: int) -> float:
        """Edge of a over b (antisymmetric)."""
        if a == b:
            return 0.0
        i, j = (a, b) if a < b else (b, a)
        k = self._mode_of_map[mp]
        v = self.mu.get((i, j), 0.0) + self.mu_mode.get((i, j, k), 0.0)
        return v if a < b else -v

    def team_score(self, team, mp: int) -> float:
        s = sum(self.strength(b, mp) for b in team)
        for x in range(len(team)):
            for y in range(x + 1, len(team)):
                s += self.synergy(team[x], team[y], mp)
        return s

    def logit(self, ours, theirs, mp: int) -> float:
        """Works on partial teams too (missing picks contribute 0)."""
        s = self.team_score(ours, mp) - self.team_score(theirs, mp)
        for a in ours:
            for b in theirs:
                s += self.matchup(a, b, mp)
        return s

    def win_prob(self, ours, theirs, mp: int) -> float:
        return 1.0 / (1.0 + math.exp(-self.logit(ours, theirs, mp)))

    def gain(self, b: int, ours, theirs, mp: int) -> float:
        """Change in our logit from adding b to our team."""
        return (self.strength(b, mp) + sum(self.synergy(b, a, mp) for a in ours)
                + sum(self.matchup(b, e, mp) for e in theirs))

    def sd_of(self, b: int, mp: int) -> float:
        """Standard error of strength(b, mp): wide for brawlers with few games on the map."""
        return self.sd[b][mp] if self.sd is not None else 0.0

    def adjust(self, b: int, mp: int) -> float:
        """Logit-scale bonus used only to rank and choose our picks, never in a reported win chance.

        -kappa * sd: a pessimistic (lower-bound) reading of a noisy estimate, so the brawler with
        the highest *estimate* doesn't win just because it has the fewest games (optimizer's curse).
        +gamma * log pick rate: what Masters players actually pick on the map is evidence too; a
        brawler almost nobody picks there needs a much bigger edge to be recommended.
        +rho * log pro pick rate: the same for what pros pick there (shrunk toward Masters)."""
        a = -self.kappa * self.sd_of(b, mp) if self.kappa else 0.0
        if self.gamma:
            a += self.gamma * self.log_base[b][mp]
        if self.rho:
            a += self.rho * self.pro_log_pick[b][mp]
        return a

    def pro_ban_rate(self, b: int, mp: int) -> float:
        return self.pro_ban[b][mp] if self.pro_ban else 0.0

    # -- pick model ---------------------------------------------------------

    def pick_probs(self, allies, enemies, unavailable, mp: int) -> dict[int, float]:
        """P(next pick = b) for the side owning ``allies``, as a typical Masters player."""
        scores = {}
        for b in range(self.B):
            if b in unavailable:
                continue
            s = self.log_base[b][mp]
            for a in allies:
                s += self.alpha * self.ally.get((b, a), 0.0)
            for e in enemies:
                s += self.beta * self.enemy.get((b, e), 0.0)
            scores[b] = s
        top = max(scores.values())
        exp = {b: math.exp(s - top) for b, s in scores.items()}
        z = sum(exp.values())
        return {b: v / z for b, v in exp.items()}

    def games_on_map(self, b: int, mp: int) -> int:
        bm = self.games.get("brawler_map")
        return bm[b][mp] if bm else 0
