"""Market layer: combine the model with bookmaker lines, choose directions, grade confidence,
raise early warnings, and settle results.

Prices
------
* "offered" — the price a user would actually take: Bet365 (football-data) when available,
  otherwise the market average, otherwise DraftKings (ESPN) for 1X2/goal line, otherwise an
  estimated Asian main line at DEFAULT_ASIAN_ODDS (flagged ``est``).
* "reference" — consensus price used as the market prior (average of many books / exchange).
"""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import config
from . import markets as mk

DEFAULT_STAR_RULES = {  # minimum score (EV after penalties) per star level; replaced by validation-chosen rules
    "AH": [0.00, 0.015, 0.03, 0.05, 0.055],
    "OU": [0.00, 0.02, 9.9, 9.9, 9.9],
    "1X2": [0.00, 0.03, 0.065, 0.07, 9.9],
}
STAR_RULES_PATH = config.MODEL_DIR / "star_rules.json"
SCORE_CAP = 0.15        # larger apparent edges are almost always stale / mismatched prices -> no stars
MIN_RECOMMEND_STARS = 3


def _load_rules() -> dict:
    try:
        import json
        return json.loads(STAR_RULES_PATH.read_text(encoding="utf-8"))["rules"]
    except Exception:
        return dict(DEFAULT_STAR_RULES)


STAR_RULES = _load_rules()


def _f(x):
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) and x > 1.0 else None


def _pick(*vals):
    for v in vals:
        if v is not None:
            return v
    return None


TOL_2WAY = 0.08   # max |p(Bet365) - p(consensus)| before a price is treated as a data glitch / different line
TOL_1X2 = 0.08


def _two_way_ok(o1, o2, r1, r2) -> bool:
    if not (1.25 <= o1 <= 4.0 and 1.25 <= o2 <= 4.0):
        return False
    if r1 and r2:
        p, q = mk.devig_two_way(o1, o2), mk.devig_two_way(r1, r2)
        if p is None or q is None or abs(p - q) > TOL_2WAY:
            return False
    return True


def market_inputs(r) -> dict:
    """Collect offered and reference prices for one match row (football-data or ESPN columns).
    Bet365 prices that disagree sharply with the market average are rejected (stale or
    different line) and the average price is used instead."""
    g = lambda c: _f(getattr(r, c, None))  # noqa: E731
    out = {"src": None}
    # 1X2
    b365 = (g("b365_h"), g("b365_d"), g("b365_a"))
    avg = (g("avg_h"), g("avg_d"), g("avg_a"))
    dk = (g("ml_home_close"), g("ml_draw_close"), g("ml_away_close"))
    cls = (g("avgc_h"), g("avgc_d"), g("avgc_a"))
    psc = (g("psc_h"), g("psc_d"), g("psc_a"))
    if all(b365) and all(avg):
        pb, pa = mk.devig_power(b365), mk.devig_power(avg)
        if pb is None or pa is None or np.max(np.abs(pb - pa)) > TOL_1X2:
            b365 = (None, None, None)
    if all(b365):
        out["x_offer"], out["x_src"] = b365, "Bet365"
    elif all(avg):
        out["x_offer"], out["x_src"] = avg, "Avg"
    elif all(dk):
        out["x_offer"], out["x_src"] = dk, "DraftKings"
    elif all(psc):
        out["x_offer"], out["x_src"] = psc, "Pinnacle(close)"
    elif all(cls):
        out["x_offer"], out["x_src"] = cls, "Avg(close)"
    ref = next((t for t in (avg, b365, dk, psc, cls) if all(t)), None)
    out["x_ref"] = ref
    # Goal line
    b_ok = bool(g("b365_o25") and g("b365_u25")) and _two_way_ok(g("b365_o25"), g("b365_u25"), g("avg_o25"), g("avg_u25"))
    a_ok = bool(g("avg_o25") and g("avg_u25")) and _two_way_ok(g("avg_o25"), g("avg_u25"), None, None)
    o_off = _pick((2.5, g("b365_o25"), g("b365_u25"), "Bet365") if b_ok else None,
                  (2.5, g("avg_o25"), g("avg_u25"), "Avg") if a_ok else None)
    dk_line = getattr(r, "ou_line_close", None)
    if o_off is None and dk_line is not None and not pd.isna(dk_line) and g("ou_over_close") and g("ou_under_close"):
        o_off = (float(dk_line), g("ou_over_close"), g("ou_under_close"), "DraftKings")
    out["ou_offer"] = o_off
    o_ref = _pick((2.5, g("avg_o25"), g("avg_u25")) if g("avg_o25") and g("avg_u25") else None,
                  (2.5, g("b365_o25"), g("b365_u25")) if g("b365_o25") and g("b365_u25") else None,
                  (o_off[0], o_off[1], o_off[2]) if o_off else None)
    out["ou_ref"] = o_ref
    # Asian handicap (football-data line is the home handicap)
    line = getattr(r, "ah_line", None)
    line = None if line is None or pd.isna(line) else float(line)
    a_off = None
    avg_ok = line is not None and bool(g("avg_ahh") and g("avg_aha")) and _two_way_ok(g("avg_ahh"), g("avg_aha"), None, None)
    if line is not None:
        if g("b365_ahh") and g("b365_aha") and _two_way_ok(g("b365_ahh"), g("b365_aha"),
                                                           g("avg_ahh") if avg_ok else None, g("avg_aha") if avg_ok else None):
            a_off = (line, g("b365_ahh"), g("b365_aha"), "Bet365")
        elif avg_ok:
            a_off = (line, g("avg_ahh"), g("avg_aha"), "Avg")
    out["ah_offer"] = a_off
    a_ref = None
    if line is not None:
        if avg_ok:
            a_ref = (line, g("avg_ahh"), g("avg_aha"))
        elif a_off:
            a_ref = a_off[:3]
    out["ah_ref"] = a_ref
    out["has_market"] = bool(ref or o_ref or a_ref)
    return out


def market_goals(mi: dict, rho: float) -> tuple[float, float] | None:
    p1x2 = mk.devig_power(mi["x_ref"]) if mi.get("x_ref") else None
    p_o = None
    if mi.get("ou_ref") and abs(mi["ou_ref"][0] - 2.5) < 1e-6:
        p_o = mk.devig_two_way(mi["ou_ref"][1], mi["ou_ref"][2])
    ah_line = p_ah = None
    if mi.get("ah_ref"):
        ah_line = mi["ah_ref"][0]
        p_ah = mk.devig_two_way(mi["ah_ref"][1], mi["ah_ref"][2])
    if p1x2 is None and p_o is None and p_ah is None:
        return None
    if p1x2 is None and (p_o is None or p_ah is None):
        return None  # one two-way market cannot pin both rates
    return mk.implied_goals(p1x2=p1x2, p_over25=p_o, ah_line=ah_line, p_ah_home=p_ah, rho=rho)


def final_goals(model, mkt=None, mac=None) -> tuple[float, float, str]:
    """Probability basis actually published: market-anchored correction where available,
    otherwise the market-implied view, otherwise the multi-algorithm model.
    (Out of sample the pure model is less accurate than the consensus price, so it is never
    blended against an available market — see the backtest report.)"""
    if mac is not None and all(x is not None and np.isfinite(x) for x in mac):
        return float(mac[0]), float(mac[1]), "mac"
    if mkt is not None:
        return float(mkt[0]), float(mkt[1]), "market"
    return float(model[0]), float(model[1]), "model"


def stars_for(market: str, score: float, rules: dict | None = None) -> int:
    if score >= SCORE_CAP:
        return 0
    s = 0
    for i, th in enumerate((rules or STAR_RULES)[market]):
        if score >= th:
            s = i + 1
    return s


def evaluate_match(lh: float, la: float, rho: float, mi: dict, *, model_p=None, disagree=0.0,
                   n_min=60, min_1x2_odds=config.MIN_1X2_ODDS) -> dict:
    """Probabilities, direction, EV and stars for AH / goal line / 1X2 on one match."""
    m = mk.score_matrix(lh, la, rho)
    ph, pd_, pa = mk.outcome_probs(m)
    dd, td = mk.diff_dist(m), mk.total_dist(m)
    fair_ah = mk.main_handicap_line(dd)
    fair_ou = mk.main_total_line(td)
    res = {"lh": lh, "la": la, "p": [ph, pd_, pa], "fair_ah": fair_ah, "fair_ou": fair_ou,
           "entropy": mk.entropy_1x2([ph, pd_, pa]), "picks": {}}
    penalty = 0.0
    if disagree > 0.06:
        penalty += (disagree - 0.06) * 0.5
    if n_min < 10:
        penalty += 0.03

    # --- Asian handicap
    if mi.get("ah_offer"):
        line, oh, oa, src = mi["ah_offer"]
    else:
        # estimated Asian main line from the market (or model) view
        ref_dd = dd
        if mi.get("_mkt_goals"):
            ref_dd = mk.diff_dist(mk.score_matrix(*mi["_mkt_goals"], rho))
        line, oh, oa, src = mk.main_handicap_line(ref_dd), config.DEFAULT_ASIAN_ODDS, config.DEFAULT_ASIAN_ODDS, "est"
    if mi.get("ah_offer") or mi.get("_mkt_goals"):
        cands = []
        for side, odds in (("home", oh), ("away", oa)):
            pr = mk.handicap_probs(dd, line, side)
            cands.append({"market": "AH", "sel": side, "line": line, "odds": odds, "src": src, "probs": pr,
                          "p": mk.effective_win_prob(pr), "ev": mk.expected_return(pr, odds), "fair": mk.fair_odds(pr)})
        best = max(cands, key=lambda c: c["ev"])
        best["score"] = best["ev"] - penalty
        best["stars"] = stars_for("AH", best["score"])
        res["picks"]["AH"] = best

    # --- Goal line (over / under)
    if mi.get("ou_offer"):
        line, oo, ou, src = mi["ou_offer"]
        cands = []
        for side, odds in (("over", oo), ("under", ou)):
            pr = mk.total_probs(td, line, side)
            cands.append({"market": "OU", "sel": side, "line": line, "odds": odds, "src": src, "probs": pr,
                          "p": mk.effective_win_prob(pr), "ev": mk.expected_return(pr, odds), "fair": mk.fair_odds(pr)})
        best = max(cands, key=lambda c: c["ev"])
        best["score"] = best["ev"] - penalty
        best["stars"] = stars_for("OU", best["score"])
        res["picks"]["OU"] = best

    # --- Full-time result (never below the minimum price)
    if mi.get("x_offer"):
        cands = []
        for sel, p, odds in (("H", ph, mi["x_offer"][0]), ("D", pd_, mi["x_offer"][1]), ("A", pa, mi["x_offer"][2])):
            if odds < min_1x2_odds:
                continue
            pr = {"win": p, "half_win": 0.0, "push": 0.0, "half_loss": 0.0, "loss": 1 - p}
            cands.append({"market": "1X2", "sel": sel, "line": None, "odds": odds, "src": mi["x_src"], "probs": pr,
                          "p": p, "ev": p * odds - 1, "fair": 1 / p if p > 0 else float("inf")})
        if cands:
            best = max(cands, key=lambda c: c["ev"])
            best["score"] = best["ev"] - penalty - (0.02 if best["sel"] == "D" else 0.0)
            best["stars"] = stars_for("1X2", best["score"])
            res["picks"]["1X2"] = best
        else:
            res["picks"]["1X2_skipped"] = True  # every outcome priced below the floor
    return res


def alerts(row, mi: dict, model_p, total_goals: float, entropy: float, disagree: float) -> list[str]:
    """Early-warning flags. row: feature row (rest days, history counts, aggregate score)."""
    a = []
    ref = mi.get("x_ref")
    if ref:
        mp = mk.devig_power(ref)
        if mp is not None:
            fav = int(np.argmax([mp[0], mp[2]])) * 2
            if mp[fav] >= 0.55 and model_p[fav] <= mp[fav] - 0.08:
                a.append("upset")
    if entropy >= 0.975:
        a.append("high_entropy")
    rh, ra = getattr(row, "rest_h", np.nan), getattr(row, "rest_a", np.nan)
    if not getattr(row, "is_intl", 0) and rh == rh and ra == ra:
        if (rh <= 3.2 and ra >= 5) or (ra <= 3.2 and rh >= 5):
            a.append("fatigue")
    if disagree >= 0.08:
        a.append("disagree")
    if min(getattr(row, "n_h", 99), getattr(row, "n_a", 99)) < 8:
        a.append("low_data")
    agg = getattr(row, "agg_gd", np.nan)
    if agg == agg and abs(agg) >= 2:
        a.append("second_leg")
    if total_goals >= 3.4:
        a.append("goal_fest")
    elif total_goals <= 2.0:
        a.append("tight")
    return a


def settle(pick: dict, hg: int, ag: int) -> float:
    """Profit in units for a settled pick (stake 1)."""
    if pick["market"] == "AH":
        diff = hg - ag if pick["sel"] == "home" else ag - hg
        line = pick["line"] if pick["sel"] == "home" else -pick["line"]
        r = mk.settle_result(diff, line)
    elif pick["market"] == "OU":
        tot = hg + ag
        a, b = mk.split_line(pick["line"])
        comp = lambda t: 1.0 if t > 1e-9 else (-1.0 if t < -1e-9 else 0.0)  # noqa: E731
        if pick["sel"] == "over":
            r = (comp(tot - a) + comp(tot - b)) / 2
        else:
            r = (comp(a - tot) + comp(b - tot)) / 2
    else:
        res = "H" if hg > ag else ("D" if hg == ag else "A")
        r = 1.0 if res == pick["sel"] else -1.0
    odds = pick["odds"]
    if r == 1.0:
        return odds - 1
    if r == 0.5:
        return (odds - 1) / 2
    if r == -0.5:
        return -0.5
    if r == -1.0:
        return -1.0
    return 0.0


def outcome_label(profit: float, odds: float) -> str:
    if abs(profit) < 1e-9:
        return "push"
    if profit < 0:
        return "half_loss" if abs(profit + 0.5) < 1e-9 else "loss"
    return "half_win" if abs(profit - (odds - 1) / 2) < 1e-9 else "win"
