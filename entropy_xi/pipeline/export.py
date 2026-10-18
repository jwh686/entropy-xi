"""Write the static website data (site/data/*.json)."""
from __future__ import annotations

import json
import math
from collections import defaultdict

import joblib
import numpy as np
import pandas as pd

from .. import __version__, config
from ..data import build as data_build
from . import ledger
from .backtest import outcome_units

ZH_PATH = config.ROOT / "entropy_xi" / "data" / "names_zh.json"


def _clean(o):
    """Recursively replace NaN / inf / pandas NA with None so the output is strict JSON."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(o) else None
    if o is pd.NA or o is pd.NaT:
        return None
    return o


def _dump(name: str, obj):
    path = config.SITE_DATA / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_clean(obj), ensure_ascii=False, separators=(",", ":"), default=_default, allow_nan=False),
                    encoding="utf-8")


def _default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not math.isfinite(o) else round(float(o), 4)
    if isinstance(o, (pd.Timestamp,)):
        return o.isoformat()
    if isinstance(o, np.bool_):
        return bool(o)
    return str(o)


def zh_names() -> dict:
    try:
        return json.loads(ZH_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ---------------------------------------------------------------------------
# Team histories
# ---------------------------------------------------------------------------
def long_table(matches: pd.DataFrame) -> pd.DataFrame:
    p = matches[(matches["status"] == "played") & matches["hg"].notna()]
    cols = ["mid", "date", "comp", "pool", "season"]
    h = p[cols].assign(team=p["home"], opp=p["away"], opp_name=p["away_name"], gf=p["hg"], ga=p["ag"], venue="H",
                       sotf=p.get("h_sot"), sota=p.get("a_sot"))
    a = p[cols].assign(team=p["away"], opp=p["home"], opp_name=p["home_name"], gf=p["ag"], ga=p["hg"], venue="A",
                       sotf=p.get("a_sot"), sota=p.get("h_sot"))
    neutral = p["neutral"].fillna(False).astype(bool).values
    h.loc[neutral, "venue"] = "N"
    a.loc[neutral, "venue"] = "N"
    lt = pd.concat([h, a]).sort_values("date")
    lt["res"] = np.where(lt["gf"] > lt["ga"], "W", np.where(lt["gf"] == lt["ga"], "D", "L"))
    return lt


def _form_rows(g: pd.DataFrame, n: int) -> list:
    out = []
    for r in g.tail(n).itertuples(index=False):
        out.append([r.date.strftime("%Y-%m-%d"), r.comp, r.opp, r.opp_name, r.venue, int(r.gf), int(r.ga), r.res])
    return out[::-1]


def _stats(g: pd.DataFrame) -> dict | None:
    if g.empty:
        return None
    n = len(g)
    w = int((g["res"] == "W").sum())
    d = int((g["res"] == "D").sum())
    sot = g["sotf"].dropna()
    sota = g["sota"].dropna()
    return {
        "n": n, "w": w, "d": d, "l": n - w - d, "gf": int(g["gf"].sum()), "ga": int(g["ga"].sum()),
        "ppg": round((3 * w + d) / n, 2), "o25": round(float(((g["gf"] + g["ga"]) > 2.5).mean()), 3),
        "btts": round(float(((g["gf"] > 0) & (g["ga"] > 0)).mean()), 3), "cs": round(float((g["ga"] == 0).mean()), 3),
        "sotf": round(float(sot.mean()), 2) if len(sot) else None, "sota": round(float(sota.mean()), 2) if len(sota) else None,
    }


def team_context(lt_by_team: dict, team: str, comp: str, season, before: pd.Timestamp) -> dict:
    g = lt_by_team.get(team)
    if g is None:
        return {"form": [], "last10": None, "home": None, "away": None, "season": None}
    g = g[g["date"] < before]
    season_g = g[(g["comp"] == comp) & (g["season"] == season)] if comp else g.iloc[0:0]
    return {
        "form": _form_rows(g, 8),
        "last10": _stats(g.tail(10)),
        "home": _stats(g[g["venue"] == "H"].tail(10)),
        "away": _stats(g[g["venue"] == "A"].tail(10)),
        "season": _stats(season_g),
    }


def h2h(lt_by_team: dict, home: str, away: str, before: pd.Timestamp, n: int = 8) -> dict:
    g = lt_by_team.get(home)
    if g is None:
        return {"rows": [], "w": 0, "d": 0, "l": 0}
    g = g[(g["opp"] == away) & (g["date"] < before)]
    rows = _form_rows(g, n)
    return {"rows": rows, "w": int((g["res"] == "W").sum()), "d": int((g["res"] == "D").sum()),
            "l": int((g["res"] == "L").sum()), "total": int(len(g))}


# ---------------------------------------------------------------------------
# Performance aggregation
# ---------------------------------------------------------------------------
def _agg(recs: list[dict], market: str | None = None, min_stars: int = 0) -> dict:
    won = dec = profit = 0.0
    n = 0
    odds = []
    for r in recs:
        for k, p in r.get("picks", {}).items():
            if market and k != market:
                continue
            if p["stars"] < min_stars or k not in r.get("settled", {}):
                continue
            s = r["settled"][k]
            w, d = outcome_units(s["profit"], p["odds"])
            won += w
            dec += d
            profit += s["profit"]
            n += 1
            odds.append(p["odds"])
    return {"n": n, "hit": round(won / dec, 4) if dec else None, "roi": round(profit / n, 4) if n else None,
            "profit": round(profit, 2), "avg_odds": round(float(np.mean(odds)), 3) if odds else None}


def _lean(recs: list[dict]) -> dict:
    s = [r for r in recs if r.get("status") == "settled"]
    if not s:
        return {"n": 0}
    return {"n": len(s), "x_acc": round(float(np.mean([r["lean_hit"] for r in s])), 4),
            "ou_acc": round(float(np.mean([r["ou25_hit"] for r in s])), 4)}


def performance_block(recs: list[dict], min_stars: int) -> dict:
    settled = [r for r in recs if r.get("status") == "settled"]
    out = {"matches": len(settled), "lean": _lean(settled)}
    for mk in ("AH", "OU", "1X2"):
        out[mk] = {"rec": _agg(settled, mk, min_stars), "all": _agg(settled, mk, 0),
                   "by_star": {s: _agg([r for r in settled], mk, s) for s in range(1, 6)}}
    out["rec"] = _agg(settled, None, min_stars)
    # Daily cumulative series (recommended picks)
    by_day = defaultdict(list)
    for r in settled:
        by_day[r["bj_date"]].append(r)
    series, cum, won_c, dec_c = [], 0.0, 0.0, 0.0
    for d in sorted(by_day):
        a = _agg(by_day[d], None, min_stars)
        if a["n"] == 0:
            continue
        cum += a["profit"]
        for r in by_day[d]:
            for k, p in r.get("picks", {}).items():
                if p["stars"] >= min_stars and k in r.get("settled", {}):
                    w, dd = outcome_units(r["settled"][k]["profit"], p["odds"])
                    won_c += w
                    dec_c += dd
        series.append([d, a["n"], a["hit"], round(cum, 2), round(won_c / dec_c, 4) if dec_c else None])
    out["series"] = series
    # Cumulative profit per market over every directional pick (no star filter)
    per = {}
    for mk in ("AH", "OU", "1X2"):
        cum, s = 0.0, []
        for d in sorted(by_day):
            a = _agg(by_day[d], mk, 0)
            if a["n"]:
                cum += a["profit"]
                s.append([d, round(cum, 2)])
        per[mk] = s
    out["series_all"] = per
    by_comp = defaultdict(list)
    for r in settled:
        by_comp[r["comp"]].append(r)
    out["by_comp"] = {c: _agg(v, None, min_stars) | {"lean": _lean(v)} for c, v in by_comp.items()}
    return out


def backtest_block() -> dict | None:
    path = config.PROCESSED / "backtest_report.json"
    if not path.exists():
        return None
    rep = json.loads(path.read_text(encoding="utf-8"))
    out = {"validation_end": rep.get("validation_end"), "star_rules": rep.get("star_rules"), "pools": {}}
    for pool, r in rep["pools"].items():
        out["pools"][pool] = {"prob": r.get("prob"), "final": r.get("final"), "market": r.get("market"), "model": r.get("model")}
    picks_path = config.PROCESSED / "backtest_picks.pkl"
    if picks_path.exists():
        bp = pd.read_pickle(picks_path)
        bp = bp[(bp["strategy"] == "final") & (bp["stars"] >= 3)]
        seasons = []
        for (fold, mkt), g in bp.groupby(["fold", "market"]):
            wd = [outcome_units(p, o) for p, o in zip(g["profit"], g["odds"])]
            dec = sum(d for _, d in wd)
            seasons.append({"season": int(fold), "market": mkt, "n": int(len(g)),
                            "hit": round(sum(w for w, _ in wd) / dec, 4) if dec else None,
                            "roi": round(float(g["profit"].mean()), 4)})
        out["by_season"] = seasons
        comp_rows = []
        hold = bp[bp["fold"] > rep.get("validation_end", 2021)]
        for (comp, mkt), g in hold.groupby(["comp", "market"]):
            if comp not in config.DISPLAY_COMPS:
                continue
            wd = [outcome_units(p, o) for p, o in zip(g["profit"], g["odds"])]
            dec = sum(d for _, d in wd)
            comp_rows.append({"comp": comp, "market": mkt, "n": int(len(g)),
                              "hit": round(sum(w for w, _ in wd) / dec, 4) if dec else None,
                              "roi": round(float(g["profit"].mean()), 4)})
        out["by_comp"] = comp_rows
    probs_path = config.PROCESSED / "backtest_probs.pkl"
    if probs_path.exists():
        pr = pd.read_pickle(probs_path)
        pr = pr[pr["fold"] > rep.get("validation_end", 2021)]
        bins = np.linspace(0, 1, 11)
        cal = []
        for k, col in ((0, "p_h"), (1, "p_d"), (2, "p_a")):
            p = pr[col].values
            y = (pr["res"].values == k).astype(float)
            idx = np.digitize(p, bins) - 1
            for b in range(10):
                sel = idx == b
                if sel.sum() >= 40:
                    cal.append([round(float(p[sel].mean()), 3), round(float(y[sel].mean()), 3), int(sel.sum())])
        out["calibration"] = cal
    return out


# ---------------------------------------------------------------------------
def run(log=print, matches: pd.DataFrame | None = None, feats: dict | None = None):
    if matches is None:
        matches, _ = data_build.load()
    teams = pd.read_pickle(config.PROCESSED / "teams.pkl")
    zh = zh_names()
    now = pd.Timestamp.now(tz="UTC")
    live = ledger.load(ledger.LIVE)
    replay = ledger.load(ledger.REPLAY)
    lt = long_table(matches)
    lt_by_team = {k: g for k, g in lt.groupby("team")}
    seasons = matches.set_index("mid")["season"].to_dict()

    # --- team directory (everyone referenced by published records + display competitions, recent)
    recent = matches[(matches["date"] >= now - pd.Timedelta(days=730)) & matches["comp"].isin(config.DISPLAY_COMPS)]
    keys = set(recent["home"]) | set(recent["away"])
    for r in list(live.values()) + list(replay.values()):
        keys |= {r["home"], r["away"]}
    tinfo = teams.set_index("key")
    team_dir = {}
    for k in keys:
        if k not in tinfo.index:
            continue
        t = tinfo.loc[k]
        if isinstance(t, pd.DataFrame):
            t = t.iloc[0]
        name = t["name"]
        team_dir[k] = {"name": name, "zh": zh.get(name), "abbr": t.get("abbr"), "color": t.get("color"),
                       "league": t.get("league"), "pool": t.get("pool")}

    # --- upcoming predictions
    cutoff = (now - pd.Timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    preview = ledger.load(ledger.PREVIEW)
    upcoming = [r for r in live.values() if r["status"] == "pending" and r["kickoff"] >= cutoff]
    seen = {r["mid"] for r in upcoming}
    upcoming += [r for r in preview.values() if r["mid"] not in seen and r["kickoff"] >= cutoff]
    upcoming.sort(key=lambda r: r["kickoff"])
    enriched = []
    for r in upcoming:
        ko = pd.Timestamp(r["kickoff"])
        season = seasons.get(r["mid"])
        e = dict(r)
        e["ctx"] = {"home": team_context(lt_by_team, r["home"], r["comp"], season, ko),
                    "away": team_context(lt_by_team, r["away"], r["comp"], season, ko),
                    "h2h": h2h(lt_by_team, r["home"], r["away"], ko)}
        enriched.append(e)
    _dump("predictions.json", {"generated": now.isoformat(), "matches": enriched})

    # --- results history (settled live + replay), newest first, by Beijing date
    def slim(r):
        keep = ("mid", "pool", "comp", "kickoff", "bj_date", "home", "away", "home_name", "away_name", "mode",
                "published", "picks", "settled", "result", "status", "alerts", "best_stars", "lean_hit", "ou25_hit")
        out = {k: r.get(k) for k in keep}
        out["p"] = r["model"]["p"]
        out["lhla"] = [r["model"]["lh"], r["model"]["la"]]
        out["fair"] = [r["model"]["fair_ah"], r["model"]["fair_ou"]]
        return out

    hist = [slim(r) for r in list(live.values()) + list(replay.values()) if r["status"] in ("settled", "void")]
    hist.sort(key=lambda r: r["kickoff"], reverse=True)
    _dump("results.json", {"generated": now.isoformat(), "matches": hist})

    # --- performance
    min_stars = 3
    perf = {
        "generated": now.isoformat(), "min_stars": min_stars, "live_start": config.LIVE_START,
        "live": performance_block(list(live.values()), min_stars),
        "replay": performance_block(list(replay.values()), min_stars),
        "backtest": backtest_block(),
    }
    _dump("performance.json", perf)

    # --- team files
    rt = {}
    for pool in ("club", "intl"):
        p = config.PROCESSED / f"ratings_{pool}.joblib"
        if p.exists():
            rt.update(joblib.load(p)["elo_track"])
    for k in team_dir:
        g = lt_by_team.get(k)
        if g is None:
            continue
        track = rt.get(k, [])
        track = [(d, e) for d, e in track if d >= now - pd.Timedelta(days=365 * 5)]
        # one point per ~2 weeks keeps files small
        sampled, last = [], None
        for d, e in track:
            if last is None or (d - last).days >= 14:
                sampled.append([d.strftime("%Y-%m-%d"), e])
                last = d
        if track:
            sampled.append([track[-1][0].strftime("%Y-%m-%d"), track[-1][1]])
        team_dir[k]["elo"] = sampled[-1][1] if sampled else None
        team_dir[k]["n"] = int(len(g))
        _dump(f"teams/{k.replace(':', '_')}.json", {
            "key": k, **team_dir[k], "elo_track": sampled,
            "matches": _form_rows(g, 60),
            "all": _stats(g), "last20": _stats(g.tail(20)),
            "home": _stats(g[g["venue"] == "H"].tail(20)), "away": _stats(g[g["venue"] == "A"].tail(20)),
        })
    _dump("teams.json", team_dir)

    comps = {k: {"zh": v["zh"], "en": v["en"], "group": v["group"]} for k, v in config.COMPETITIONS.items() if v["display"]}
    _dump("meta.json", {
        "generated": now.isoformat(), "version": __version__, "live_start": config.LIVE_START,
        "competitions": comps, "min_1x2_odds": config.MIN_1X2_ODDS,
        "db": {"matches": int((matches["status"] == "played").sum()), "teams": int(matches["home"].nunique()),
               "first": str(matches["date"].min().date()), "last": str(matches[matches["status"] == "played"]["date"].max().date())},
        "upcoming": len(enriched),
    })
    log(f"Exported site data: {len(enriched)} upcoming, {len(hist)} settled records, {len(team_dir)} teams")
