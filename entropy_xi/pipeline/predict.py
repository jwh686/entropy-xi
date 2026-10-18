"""Turn model + market information into publishable match records (shared by live and replay)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

from .. import config
from ..models import markets as mk
from ..models import picks as pk

def _iso(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%SZ")


def bj_date(ts) -> str:
    return pd.Timestamp(ts).tz_convert(config.BJT).strftime("%Y-%m-%d")


def _r(x, n=4):
    if x is None:
        return None
    try:
        if isinstance(x, float) and not math.isfinite(x):
            return None
        return round(float(x), n)
    except (TypeError, ValueError):
        return None


def _clean_pick(p: dict) -> dict:
    return {"market": p["market"], "sel": p["sel"], "line": p["line"], "odds": _r(p["odds"], 3), "src": p["src"],
            "p": _r(p["p"]), "ev": _r(p["ev"]), "fair": _r(p["fair"], 3), "stars": int(p["stars"]),
            "probs": {k: _r(v) for k, v in p["probs"].items()}}


def line_move(mr) -> dict | None:
    """DraftKings open -> current movement from ESPN (implied home-win probability and goal line)."""
    g = lambda c: getattr(mr, c, None)  # noqa: E731
    o = [g("ml_home_open"), g("ml_draw_open"), g("ml_away_open")]
    c = [g("ml_home_close"), g("ml_draw_close"), g("ml_away_close")]
    out = {}
    try:
        po, pc = mk.devig_power(o), mk.devig_power(c)
        if po is not None and pc is not None:
            out["home_prob_move"] = round(float(pc[0] - po[0]), 4)
    except Exception:
        pass
    lo, lc = g("ou_line_open"), g("ou_line_close")
    if lo is not None and lc is not None and not pd.isna(lo) and not pd.isna(lc):
        out["goal_line_move"] = float(lc) - float(lo)
    return out or None


def build_record(mr, fr, pr, *, mode: str, published: str, mac=None, mkt="auto") -> dict:
    """mr: match row, fr: feature row, pr: prediction row (m_lh, m_la, m_p*, disagree, rho).
    mac: market-anchored corrected expected goals (league matches with prices)."""
    mi = pk.market_inputs(mr)
    if isinstance(mkt, str):
        mkt = pk.market_goals(mi, pr.rho) if mi["has_market"] else None
    lh, la, basis = pk.final_goals((pr.m_lh, pr.m_la), mkt, mac)
    ev = pk.evaluate_match(lh, la, pr.rho, dict(mi, _mkt_goals=mkt), disagree=pr.disagree,
                           n_min=min(fr.n_h, fr.n_a))
    mat = mk.score_matrix(lh, la, pr.rho)
    td = mk.total_dist(mat)
    model_p = [pr.m_ph, pr.m_pd, pr.m_pa]
    al = pk.alerts(fr, mi, model_p, lh + la, ev["entropy"], pr.disagree)
    mv = line_move(mr)
    if mv and (abs(mv.get("home_prob_move", 0)) >= 0.04 or abs(mv.get("goal_line_move", 0)) >= 0.5):
        al.append("line_move")
    if any(v.get("score", 0) >= pk.SCORE_CAP for k, v in ev["picks"].items() if not k.endswith("_skipped")):
        al.append("price_check")  # apparent edge too large to be real: stale or mismatched price
    picks = {k: _clean_pick(v) for k, v in ev["picks"].items() if not k.endswith("_skipped")}
    top = sorted(((i, j, float(mat[i, j])) for i in range(6) for j in range(6)), key=lambda x: -x[2])[:6]
    rec = {
        "mid": str(mr.mid), "pool": mr.pool, "comp": mr.comp, "kickoff": _iso(mr.date), "bj_date": bj_date(mr.date),
        "home": mr.home, "away": mr.away, "home_name": mr.home_name, "away_name": mr.away_name,
        "neutral": bool(getattr(mr, "neutral", False)) if not pd.isna(getattr(mr, "neutral", False)) else False,
        "mode": mode, "published": published,
        "model": {
            "lh": _r(lh, 3), "la": _r(la, 3), "p": [_r(x) for x in ev["p"]], "p_model": [_r(x) for x in model_p],
            "p_market": [_r(x) for x in mk.devig_power(mi["x_ref"])] if mi.get("x_ref") else None,
            "entropy": _r(ev["entropy"]), "fair_ah": ev["fair_ah"], "fair_ou": ev["fair_ou"],
            "p_over25": _r(float(td[3:].sum())), "p_btts": _r(float(1 - mat[0, :].sum() - mat[:, 0].sum() + mat[0, 0])),
            "disagree": _r(pr.disagree), "basis": basis, "rho": _r(pr.rho, 3),
            "lam_model": [_r(pr.m_lh, 3), _r(pr.m_la, 3)], "lam_market": [_r(mkt[0], 3), _r(mkt[1], 3)] if mkt else None,
            "top_scores": [[i, j, _r(p)] for i, j, p in top],
            "matrix": [[_r(float(mat[i, j]), 4) for j in range(6)] for i in range(6)],
        },
        "elo": [_r(fr.elo_h, 0), _r(fr.elo_a, 0)],
        "lines": {
            "ah": [mi["ah_offer"][0], _r(mi["ah_offer"][1], 3), _r(mi["ah_offer"][2], 3), mi["ah_offer"][3]] if mi.get("ah_offer") else None,
            "ou": [mi["ou_offer"][0], _r(mi["ou_offer"][1], 3), _r(mi["ou_offer"][2], 3), mi["ou_offer"][3]] if mi.get("ou_offer") else None,
            "x": [_r(x, 3) for x in mi["x_offer"]] + [mi["x_src"]] if mi.get("x_offer") else None,
        },
        "picks": picks,
        "x_skipped": bool(ev["picks"].get("1X2_skipped")),
        "alerts": al, "line_move": mv,
        "status": "pending",
    }
    rec["best_stars"] = max([p["stars"] for p in picks.values()] or [0])
    return rec


def settle_record(rec: dict, hg, ag, status: str) -> dict:
    if status == "void":
        rec["status"] = "void"
        return rec
    hg, ag = int(hg), int(ag)
    rec["result"] = [hg, ag]
    out = {}
    for k, p in rec["picks"].items():
        profit = pk.settle({"market": p["market"], "sel": p["sel"], "line": p["line"], "odds": p["odds"]}, hg, ag)
        out[k] = {"profit": round(profit, 4), "outcome": pk.outcome_label(profit, p["odds"])}
    rec["settled"] = out
    res = 0 if hg > ag else (1 if hg == ag else 2)
    pm = rec["model"]["p"]
    rec["lean_hit"] = int(int(np.argmax(pm)) == res)
    rec["ou25_hit"] = int((rec["model"]["p_over25"] > 0.5) == (hg + ag > 2))
    rec["status"] = "settled"
    return rec
