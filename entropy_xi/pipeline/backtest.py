"""Walk-forward backtest: settle every out-of-sample pick against the price that was on offer
before kick-off, then report hit rate / ROI by market, star level, competition and season.

Probability bases compared (all strictly out-of-sample):
  * model   — the multi-algorithm ensemble alone
  * market  — expected goals implied by the de-vigged consensus price
  * final   — market-anchored correction (MAC) where prices exist in a league, else market, else model

Validation folds (<= VALIDATION_END) choose the star thresholds; later folds are the untouched
hold-out reported on the website."""
from __future__ import annotations

import json
import time

import joblib
import numpy as np
import pandas as pd

from .. import config
from ..data import build as data_build
from ..models import markets as mk
from ..models import picks as pk
from ..models.meta import MarketCorrection, frame
from . import train

VALIDATION_END = 2021
MAC_YEARS = 8


def outcome_units(profit: float, odds: float) -> tuple[float, float]:
    """(won, decided) contribution of one settled pick for the hit-rate metric."""
    lab = pk.outcome_label(profit, odds)
    return {"win": (1, 1), "half_win": (0.5, 0.5), "push": (0, 0), "half_loss": (0, 0.5), "loss": (0, 1)}[lab]


def summarize(df: pd.DataFrame) -> dict:
    if df.empty:
        return {"n": 0, "hit": None, "roi": None, "profit": 0.0, "avg_odds": None}
    wd = [outcome_units(p, o) for p, o in zip(df["profit"], df["odds"])]
    won = sum(w for w, _ in wd)
    dec = sum(d for _, d in wd)
    return {"n": int(len(df)), "hit": round(won / dec, 4) if dec else None,
            "roi": round(float(df["profit"].sum() / len(df)), 4), "profit": round(float(df["profit"].sum()), 2),
            "avg_odds": round(float(df["odds"].mean()), 3)}


# ---------------------------------------------------------------------------
def mac_walk_forward(m: pd.DataFrame, f: pd.DataFrame, pred: pd.DataFrame, mg: pd.DataFrame, log=print) -> pd.DataFrame:
    """Out-of-sample MAC expected goals for league matches with prices."""
    D = frame(f, pred, mg)
    D = D[(m.loc[D.index, "group"] == "league").values]
    D["fold"] = pred.loc[D.index, "fold"]
    played = (m.loc[D.index, "status"] == "played").values & m.loc[D.index, "hg"].notna().values
    out = []
    for y in sorted(D["fold"].unique()):
        tr = D[played & (D["fold"] < y) & (D["fold"] >= y - MAC_YEARS)]
        te = D[D["fold"] == y]
        if len(tr) < 3000 or te.empty:
            continue
        mc = MarketCorrection().fit(tr, m.loc[tr.index, "hg"].values, m.loc[tr.index, "ag"].values)
        out.append(mc.predict(te))
    mac = pd.concat(out) if out else pd.DataFrame(columns=["mac_lh", "mac_la"])
    mac.to_pickle(config.PROCESSED / "mac_oos.pkl")
    log(f"  MAC walk-forward: {len(mac)} matches")
    return mac


def train_mac_production(m, f, pred, mg, log=print):
    D = frame(f, pred, mg)
    D = D[((m.loc[D.index, "group"] == "league") & (m.loc[D.index, "status"] == "played") & m.loc[D.index, "hg"].notna()).values]
    D = D[m.loc[D.index, "date"] >= pd.Timestamp.now(tz="UTC") - pd.DateOffset(years=MAC_YEARS)]
    mc = MarketCorrection().fit(D, m.loc[D.index, "hg"].values, m.loc[D.index, "ag"].values)
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(mc, config.MODEL_DIR / "mac.joblib", compress=3)
    log(f"  MAC production: {len(D)} rows")


# ---------------------------------------------------------------------------
def evaluate_pool(pool: str, m: pd.DataFrame, f: pd.DataFrame, pred: pd.DataFrame, mg: pd.DataFrame | None,
                  mac: pd.DataFrame | None, log=print) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (picks ledger, per-match probability ledger) for played OOS matches."""
    played = pred.index[(m.loc[pred.index, "status"] == "played").values & m.loc[pred.index, "hg"].notna().values]
    P, M, F = pred.loc[played], m.loc[played], f.loc[played]
    rows, prob_rows = [], []
    t = time.time()
    for r, mr, fr in zip(P.itertuples(), M.itertuples(), F.itertuples()):
        mi = pk.market_inputs(mr)
        mkt = (mg.at[r.Index, "mk_lh"], mg.at[r.Index, "mk_la"]) if mg is not None and r.Index in mg.index else None
        mc = (mac.at[r.Index, "mac_lh"], mac.at[r.Index, "mac_la"]) if mac is not None and r.Index in mac.index else None
        hg, ag = int(mr.hg), int(mr.ag)
        res_i = 0 if hg > ag else (1 if hg == ag else 2)
        n_min = min(fr.n_h, fr.n_a)
        strategies = [("final", pk.final_goals((r.m_lh, r.m_la), mkt, mc)[:2])]
        if mkt is not None:
            strategies += [("market", mkt), ("model", (r.m_lh, r.m_la))]
        for strat, (lh, la) in strategies:
            ev = pk.evaluate_match(lh, la, r.rho, dict(mi, _mkt_goals=mkt), disagree=r.disagree, n_min=n_min)
            if strat == "final":
                mat = mk.score_matrix(lh, la, r.rho)
                mp = mk.devig_power(mi["x_ref"]) if mi.get("x_ref") else None
                prob_rows.append({
                    "idx": r.Index, "fold": r.fold, "comp": mr.comp, "date": mr.date, "res": res_i,
                    "p_h": ev["p"][0], "p_d": ev["p"][1], "p_a": ev["p"][2],
                    "m_ph": r.m_ph, "m_pd": r.m_pd, "m_pa": r.m_pa,
                    "mk_ph": mp[0] if mp is not None else np.nan, "mk_pd": mp[1] if mp is not None else np.nan,
                    "mk_pa": mp[2] if mp is not None else np.nan,
                    "p_o25": float(mk.total_dist(mat)[3:].sum()), "over25": int(hg + ag > 2),
                    "entropy": ev["entropy"], "has_market": mkt is not None, "has_mac": mc is not None,
                })
            for mkey, pick in ev["picks"].items():
                if mkey.endswith("_skipped") or pick["src"] == "est":
                    continue  # estimated lines carry no real price -> not settled in the backtest
                profit = pk.settle(pick, hg, ag)
                rows.append({
                    "idx": r.Index, "fold": r.fold, "strategy": strat, "comp": mr.comp, "date": mr.date,
                    "market": pick["market"], "sel": pick["sel"], "line": pick["line"], "odds": pick["odds"],
                    "src": pick["src"], "p": pick["p"], "ev": pick["ev"], "score": pick["score"], "stars": pick["stars"],
                    "profit": profit, "outcome": pk.outcome_label(profit, pick["odds"]),
                })
    log(f"  evaluated {pool}: {len(played)} matches -> {len(rows)} picks in {time.time() - t:.0f}s")
    return pd.DataFrame(rows), pd.DataFrame(prob_rows)


def prob_metrics(pr: pd.DataFrame) -> dict:
    """Probabilistic accuracy (all matches, no odds needed)."""
    def ll(cols, df):
        p = df[cols].values
        p = p / p.sum(1, keepdims=True)
        return float(-np.mean(np.log(np.clip(p[np.arange(len(df)), df["res"].values], 1e-12, 1))))

    def acc(cols, df):
        return float(np.mean(np.argmax(df[cols].values, 1) == df["res"].values))

    out = {"n": int(len(pr)), "logloss": round(ll(["p_h", "p_d", "p_a"], pr), 4), "acc": round(acc(["p_h", "p_d", "p_a"], pr), 4),
           "model_logloss": round(ll(["m_ph", "m_pd", "m_pa"], pr), 4), "model_acc": round(acc(["m_ph", "m_pd", "m_pa"], pr), 4),
           "ou25_acc": round(float(np.mean((pr["p_o25"] > 0.5).astype(int) == pr["over25"])), 4)}
    mm = pr[pr["mk_ph"].notna()]
    if len(mm):
        out["with_market"] = {
            "n": int(len(mm)),
            "final_logloss": round(ll(["p_h", "p_d", "p_a"], mm), 4),
            "model_only_logloss": round(ll(["m_ph", "m_pd", "m_pa"], mm), 4),
            "market_logloss": round(ll(["mk_ph", "mk_pd", "mk_pa"], mm), 4),
            "final_acc": round(acc(["p_h", "p_d", "p_a"], mm), 4),
            "model_acc": round(acc(["m_ph", "m_pd", "m_pa"], mm), 4),
            "market_acc": round(acc(["mk_ph", "mk_pd", "mk_pa"], mm), 4),
        }
    return out


def star_table(picks: pd.DataFrame) -> dict:
    out = {}
    for mkt, g in picks.groupby("market"):
        out[mkt] = {int(s): summarize(gg) for s, gg in g.groupby("stars")}
        out[mkt]["rec"] = summarize(g[g["stars"] >= pk.MIN_RECOMMEND_STARS])
        out[mkt]["all"] = summarize(g)
    return out


def restar(picks: pd.DataFrame, rules: dict) -> pd.DataFrame:
    """Re-grade stars with the given rules (thresholds change without re-evaluating matches)."""
    picks = picks.copy()
    picks["stars"] = [pk.stars_for(m, s, rules) for m, s in zip(picks["market"], picks["score"])]
    return picks


TIER_MIN_N = {3: 300, 4: 120, 5: 50}


def choose_star_rules(val: pd.DataFrame, log=print) -> dict:
    """Pick star thresholds on validation folds only.
    Tier k uses the score threshold with the best validation ROI among thresholds that keep at
    least TIER_MIN_N[k] picks and are not below the previous tier; a tier whose best ROI is
    negative is disabled (threshold 9.9). 1 star = positive estimated value; 2 stars = halfway."""
    grid = np.round(np.arange(0.02, 0.1201, 0.005), 3)
    rules = {}
    for mkt in ("AH", "OU", "1X2"):
        v = val[(val["market"] == mkt) & (val["score"] < pk.SCORE_CAP)]
        th = {}
        lo = 0.02
        for k in (3, 4, 5):
            best = None
            for t in grid[grid >= lo]:
                sub = v[v["score"] >= t]
                if len(sub) < TIER_MIN_N[k]:
                    break
                roi = sub["profit"].mean()
                if best is None or roi > best[1]:
                    best = (float(t), float(roi), len(sub))
            if best is None or best[1] < 0:
                th[k] = 9.9
                lo = 9.9
            else:
                th[k] = best[0]
                lo = best[0] + 0.005
        t3 = th[3] if th[3] < 9 else 0.04
        rules[mkt] = [0.0, round(t3 / 2, 4), th[3], th[4], th[5]]
        log(f"  star rules {mkt}: {rules[mkt]}")
    return rules


def run(log=print) -> dict:
    matches, _ = data_build.load()
    report = {"generated": pd.Timestamp.now(tz="UTC").isoformat(), "validation_end": VALIDATION_END,
              "star_rules": pk.STAR_RULES, "pools": {}}
    all_picks, all_probs = [], []
    for pool in ("club", "intl"):
        m = matches[matches["pool"] == pool]
        f = pd.read_pickle(config.PROCESSED / f"features_{pool}.pkl")
        pred = pd.read_pickle(config.PROCESSED / f"pred_{pool}.pkl")
        mg = mac = None
        if pool == "club":
            mg = train.market_goal_table(m, pred.index, log=log)
            mac = mac_walk_forward(m, f, pred, mg, log=log)
            train_mac_production(m, f, pred, mg, log=log)
        picks, probs = evaluate_pool(pool, m, f, pred, mg, mac, log=log)
        picks["pool"], probs["pool"] = pool, pool
        all_picks.append(picks)
        all_probs.append(probs)
        report["pools"][pool] = {"prob": prob_metrics(probs)}
    picks = pd.concat(all_picks, ignore_index=True)
    probs = pd.concat(all_probs, ignore_index=True)

    # Star thresholds from validation folds of the published ("final") basis, then re-grade everything.
    final = picks[picks["strategy"] == "final"]
    rules = choose_star_rules(final[final["fold"] <= VALIDATION_END], log=log)
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    pk.STAR_RULES_PATH.write_text(json.dumps({"rules": rules, "chosen_on": f"folds <= {VALIDATION_END}",
                                              "tier_min_n": TIER_MIN_N, "score_cap": pk.SCORE_CAP}), encoding="utf-8")
    pk.STAR_RULES.clear()
    pk.STAR_RULES.update(rules)
    report["star_rules"] = rules
    picks = restar(picks, rules)
    for pool in report["pools"]:
        g0 = picks[picks["pool"] == pool]
        for strat, g in g0.groupby("strategy"):
            report["pools"][pool][strat] = {"validation": star_table(g[g["fold"] <= VALIDATION_END]),
                                            "holdout": star_table(g[g["fold"] > VALIDATION_END])}
    picks.to_pickle(config.PROCESSED / "backtest_picks.pkl")
    probs.to_pickle(config.PROCESSED / "backtest_probs.pkl")
    (config.PROCESSED / "backtest_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    log("Backtest report written to data/processed/backtest_report.json")
    make_replay(matches, log=log)
    return report


REPLAY_START = {"club": "2026-08-01", "intl": "2026-06-01"}


def make_replay(matches: pd.DataFrame, log=print):
    """Season-to-date records from the walk-forward fold (models trained before the season)."""
    from . import ledger
    from .predict import build_record, settle_record

    today_bj = pd.Timestamp.now(tz=config.BJT).normalize().tz_convert("UTC")
    mac_path = config.PROCESSED / "mac_oos.pkl"
    mac = pd.read_pickle(mac_path) if mac_path.exists() else pd.DataFrame(columns=["mac_lh", "mac_la"])
    out = {}
    for pool in ("club", "intl"):
        m = matches[matches["pool"] == pool]
        f = pd.read_pickle(config.PROCESSED / f"features_{pool}.pkl")
        pred = pd.read_pickle(config.PROCESSED / f"pred_{pool}.pkl")
        sel = m[(m["date"] >= pd.Timestamp(REPLAY_START[pool], tz="UTC")) & (m["date"] < today_bj)
                & m["comp"].isin(config.DISPLAY_COMPS) & m["status"].isin(["played", "void"])]
        sel = sel[sel.index.isin(pred.index)]
        P = pred.loc[sel.index]
        for mr, fr, pr in zip(sel.itertuples(), f.loc[sel.index].itertuples(), P.itertuples()):
            mc = (mac.at[mr.Index, "mac_lh"], mac.at[mr.Index, "mac_la"]) if mr.Index in mac.index else None
            rec = build_record(mr, fr, pr, mode="replay", published="walk-forward", mac=mc)
            settle_record(rec, mr.hg, mr.ag, "played" if mr.status == "played" else "void")
            out[rec["mid"]] = rec
    ledger.save(out, ledger.REPLAY)
    log(f"Replay ledger: {len(out)} matches since {REPLAY_START}")
