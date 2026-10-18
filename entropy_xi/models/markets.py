"""Score-matrix maths: Dixon–Coles distribution, Asian handicap / goal-line settlement,
de-vigging and market-implied expected goals.

Conventions
-----------
* Asian handicap ``line`` is always the HOME handicap (football-data ``AHh``): -0.75 means
  home gives three-quarters of a goal. The away side holds ``-line``.
* Quarter lines are split into two half-stakes (e.g. -0.75 -> -0.5 and -1.0).
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq, least_squares

MAXG = 11  # goals 0..10
_K = np.arange(MAXG)
_LOGFACT = np.array([math.lgamma(k + 1) for k in range(MAXG)])


def _pmf(lam: float) -> np.ndarray:
    return np.exp(_K * math.log(max(lam, 1e-9)) - lam - _LOGFACT)


def score_matrix(lh: float, la: float, rho: float = -0.06) -> np.ndarray:
    m = np.outer(_pmf(lh), _pmf(la))
    # Dixon–Coles low-score dependence
    m[0, 0] *= max(1 - lh * la * rho, 1e-6)
    m[0, 1] *= max(1 + lh * rho, 1e-6)
    m[1, 0] *= max(1 + la * rho, 1e-6)
    m[1, 1] *= max(1 - rho, 1e-6)
    return m / m.sum()


def outcome_probs(m: np.ndarray) -> tuple[float, float, float]:
    return float(np.tril(m, -1).sum()), float(np.trace(m)), float(np.triu(m, 1).sum())


def diff_dist(m: np.ndarray) -> dict[int, float]:
    """P(home goals - away goals = d)."""
    out: dict[int, float] = {}
    n = m.shape[0]
    for d in range(-(n - 1), n):
        out[d] = float(np.trace(m, offset=-d))
    return out


def total_dist(m: np.ndarray) -> np.ndarray:
    n = m.shape[0]
    t = np.zeros(2 * n - 1)
    for i in range(n):
        t[i:i + n] += m[i]
    return t


def split_line(line: float) -> tuple[float, float]:
    """Quarter lines -> two half stakes; others -> the same line twice."""
    q = round(line * 4)
    if q % 2 != 0:  # .25 / .75
        return (q - 1) / 4.0, (q + 1) / 4.0
    return line, line


def _settle_component(margin_plus_line: float) -> float:
    """+1 win, 0 push, -1 loss for a single half-stake."""
    if margin_plus_line > 1e-9:
        return 1.0
    if margin_plus_line < -1e-9:
        return -1.0
    return 0.0


def settle_result(score_diff: int, line: float) -> float:
    """Outcome units for a bet on the side holding `line` given that side's goal difference.
    Returns one of 1, 0.5, 0, -0.5, -1 (win, half-win, push, half-loss, loss)."""
    a, b = split_line(line)
    return (_settle_component(score_diff + a) + _settle_component(score_diff + b)) / 2.0


def handicap_probs(dd: dict[int, float], line: float, side: str = "home") -> dict[str, float]:
    """Probabilities of win / half-win / push / half-loss / loss for a handicap bet.
    dd: goal-difference distribution from the HOME perspective."""
    res = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
    sl = line if side == "home" else -line
    for d, p in dd.items():
        diff = d if side == "home" else -d
        r = settle_result(diff, sl)
        key = {1.0: "win", 0.5: "half_win", 0.0: "push", -0.5: "half_loss", -1.0: "loss"}[r]
        res[key] += p
    return res


def total_probs(td: np.ndarray, line: float, side: str = "over") -> dict[str, float]:
    res = {"win": 0.0, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 0.0}
    a, b = split_line(line)
    for g, p in enumerate(td):
        if side == "over":
            r = (_settle_component(g - a) + _settle_component(g - b)) / 2.0
        else:
            r = (_settle_component(a - g) + _settle_component(b - g)) / 2.0
        key = {1.0: "win", 0.5: "half_win", 0.0: "push", -0.5: "half_loss", -1.0: "loss"}[r]
        res[key] += p
    return res


def expected_return(pr: dict[str, float], odds: float) -> float:
    """Expected profit per unit stake."""
    w = odds - 1.0
    return pr["win"] * w + pr["half_win"] * w / 2 - pr["half_loss"] / 2 - pr["loss"]


def effective_win_prob(pr: dict[str, float]) -> float:
    """Win probability on the decided part of the stake: a half-win is half a win plus half a push,
    a half-loss is half a loss plus half a push. Break-even equals 1/odds, as for a plain bet."""
    won = pr["win"] + 0.5 * pr["half_win"]
    decided = won + pr["loss"] + 0.5 * pr["half_loss"]
    return won / decided if decided > 1e-9 else 0.5


def fair_odds(pr: dict[str, float]) -> float:
    """Decimal odds at which the bet has zero expected value."""
    # EV = pw*(o-1) + phw*(o-1)/2 - phl/2 - pl = 0  ->  o = 1 + (phl/2 + pl) / (pw + phw/2)
    num = pr["half_loss"] / 2 + pr["loss"]
    den = pr["win"] + pr["half_win"] / 2
    return 1.0 + num / den if den > 1e-9 else float("inf")


def main_handicap_line(dd: dict[int, float]) -> float:
    """Quarter line where home and away fair odds are closest (how Asian books set the main line)."""
    best, best_gap = 0.0, 1e9
    for q in range(-16, 17):
        line = q / 4.0
        fh = fair_odds(handicap_probs(dd, line, "home"))
        fa = fair_odds(handicap_probs(dd, line, "away"))
        gap = abs(math.log(fh) - math.log(fa))
        if gap < best_gap:
            best, best_gap = line, gap
    return best


def main_total_line(td: np.ndarray) -> float:
    best, best_gap = 2.5, 1e9
    for q in range(6, 21):
        line = q / 4.0
        fo = fair_odds(total_probs(td, line, "over"))
        fu = fair_odds(total_probs(td, line, "under"))
        gap = abs(math.log(fo) - math.log(fu))
        if gap < best_gap:
            best, best_gap = line, gap
    return best


# ---------------------------------------------------------------------------
# De-vigging and implied expected goals
# ---------------------------------------------------------------------------
def devig_power(odds) -> np.ndarray | None:
    """Power method: p_i = (1/o_i)^k with sum p = 1 (corrects favourite–longshot bias)."""
    o = np.asarray(odds, dtype=float)
    if np.any(~np.isfinite(o)) or np.any(o <= 1.0):
        return None
    inv = 1.0 / o
    if abs(inv.sum() - 1.0) < 1e-6:
        return inv
    try:
        k = brentq(lambda k: np.sum(inv ** k) - 1.0, 0.5, 3.0)
    except ValueError:
        return inv / inv.sum()
    return inv ** k


def devig_two_way(o1: float, o2: float) -> float | None:
    """Probability of side 1 from a two-way market (proportional)."""
    if not (np.isfinite(o1) and np.isfinite(o2)) or o1 <= 1 or o2 <= 1:
        return None
    a, b = 1 / o1, 1 / o2
    return a / (a + b)


def implied_goals(p1x2=None, p_over25=None, ah_line=None, p_ah_home=None, rho: float = -0.06,
                  init=(1.4, 1.1)) -> tuple[float, float] | None:
    """Fit (lambda_home, lambda_away) so the DC score model reproduces market probabilities."""
    targets = []
    if p1x2 is not None:
        targets.append("1x2")
    if p_over25 is not None:
        targets.append("ou")
    if ah_line is not None and p_ah_home is not None:
        targets.append("ah")
    if not targets:
        return None

    def resid(x):
        lh, la = math.exp(x[0]), math.exp(x[1])
        m = score_matrix(lh, la, rho)
        r = []
        if p1x2 is not None:
            h, d, a = outcome_probs(m)
            r += [h - p1x2[0], d - p1x2[1], a - p1x2[2]]
        if p_over25 is not None:
            td = total_dist(m)
            r.append((td[3:].sum() - p_over25) * 1.5)
        if "ah" in targets:
            pr = handicap_probs(diff_dist(m), ah_line, "home")
            fo = fair_odds(pr)
            p_home = 1.0 / fo if np.isfinite(fo) else 0.0
            pr_a = handicap_probs(diff_dist(m), ah_line, "away")
            fa = fair_odds(pr_a)
            p_away = 1.0 / fa if np.isfinite(fa) else 0.0
            s = p_home + p_away
            r.append(((p_home / s if s > 0 else 0.5) - p_ah_home) * 1.5)
        return r

    sol = least_squares(resid, x0=np.log(init), bounds=([math.log(0.05)] * 2, [math.log(6.0)] * 2), xtol=1e-6)
    return float(math.exp(sol.x[0])), float(math.exp(sol.x[1]))


def entropy_1x2(p) -> float:
    """Normalised Shannon entropy of a 1X2 distribution in [0, 1]."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1)
    return float(-(p * np.log(p)).sum() / math.log(3))
