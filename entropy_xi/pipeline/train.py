"""Feature computation, walk-forward training and the production model.

Walk-forward protocol (no look-ahead):
  * club pool: folds start every 1 August; intl pool: every 1 January.
  * For fold Y the base learners see only matches before the fold start (rolling window).
  * Ensemble weights / Dixon–Coles rho / market weight for fold Y are learned from the
    out-of-sample predictions of earlier folds only.
"""
from __future__ import annotations

import time

import joblib
import numpy as np
import pandas as pd

from .. import config
from ..data import build as data_build
from ..features.engine import FeatureEngine
from ..models.picks import market_goals, market_inputs
from ..models.predictor import BaseModels, Blender, feature_columns

FIRST_FOLD = {"club": 2013, "intl": 2012}
TRAIN_YEARS = {"club": 9, "intl": 22}
MIN_HISTORY = 5


def fold_starts(pool: str, last_year: int) -> list[pd.Timestamp]:
    md = "08-01" if pool == "club" else "01-01"
    return [pd.Timestamp(f"{y}-{md}", tz="UTC") for y in range(FIRST_FOLD[pool], last_year + 1)]


def compute_features(matches: pd.DataFrame, log=print) -> dict:
    out = {}
    for pool in ("club", "intl"):
        m = matches[matches["pool"] == pool].sort_values(["date", "mid"])
        t = time.time()
        eng = FeatureEngine(pool)
        f = eng.run(m)
        log(f"  features {pool}: {len(f)} rows x {f.shape[1]} cols in {time.time() - t:.0f}s")
        f.to_pickle(config.PROCESSED / f"features_{pool}.pkl")
        joblib.dump({"snapshot": eng.snapshot(), "elo_track": dict(eng.elo_track)},
                    config.PROCESSED / f"ratings_{pool}.joblib", compress=3)
        out[pool] = (m, f, eng)
    return out


def _train_mask(m: pd.DataFrame, f: pd.DataFrame, end: pd.Timestamp, years: int) -> pd.Series:
    start = end - pd.DateOffset(years=years)
    return ((m["status"] == "played") & m["hg"].notna() & (m["date"] < end) & (m["date"] >= start)
            & (f["n_h"] >= MIN_HISTORY) & (f["n_a"] >= MIN_HISTORY))


def _weights(dates: pd.Series, end: pd.Timestamp, half_life_years: float = 4.0) -> np.ndarray:
    age = (end - dates).dt.days.values / 365.25
    return 0.5 ** (age / half_life_years)


def walk_forward(pool: str, m: pd.DataFrame, f: pd.DataFrame, *, fast: bool = False, last_year: int | None = None,
                 log=print) -> pd.DataFrame:
    """Out-of-sample component predictions for every match from the first fold onward."""
    feats = feature_columns(f)
    last_year = last_year or pd.Timestamp.now(tz="UTC").year
    starts = fold_starts(pool, last_year)
    parts = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else pd.Timestamp("2100-01-01", tz="UTC")
        test = (m["date"] >= start) & (m["date"] < end) & m["status"].isin(["played", "scheduled"])
        if not test.any():
            continue
        tr = _train_mask(m, f, start, TRAIN_YEARS[pool])
        t = time.time()
        bm = BaseModels(feats, fast=fast).fit(f.loc[tr], m.loc[tr, "hg"].astype(int).values,
                                              m.loc[tr, "ag"].astype(int).values, _weights(m.loc[tr, "date"], start))
        comp = bm.predict(f.loc[test])
        comp["fold"] = start.year
        parts.append(comp)
        log(f"  {pool} fold {start.date()}: train {tr.sum():6d}  test {test.sum():5d}  ({time.time() - t:.0f}s)")
    oos = pd.concat(parts)
    oos.to_pickle(config.PROCESSED / f"oos_{pool}.pkl")
    return oos


def blend_folds(pool: str, m: pd.DataFrame, f: pd.DataFrame, oos: pd.DataFrame, lookback: int = 3,
                log=print) -> tuple[pd.DataFrame, dict]:
    """Combine OOS components fold by fold with weights learned on earlier folds only."""
    played = (m.loc[oos.index, "status"] == "played") & m.loc[oos.index, "hg"].notna()
    folds = sorted(oos["fold"].unique())
    out, blenders = [], {}
    for y in folds:
        prev = oos[(oos["fold"] < y) & (oos["fold"] >= y - lookback) & played]
        b = Blender()
        if len(prev) > 500:
            b.fit(prev, m.loc[prev.index, "hg"].values, m.loc[prev.index, "ag"].values)
        cur = oos[oos["fold"] == y]
        comb = b.combine(cur)
        comb["fold"] = y
        comb["rho"] = b.rho
        out.append(comb)
        blenders[y] = b.to_dict()
        log(f"  blend {pool} {y}: goal_w={np.round(b.goal_w, 2)} cls_w={np.round(b.cls_w, 2)} rho={b.rho:+.2f}")
    pred = pd.concat(out)
    pred.to_pickle(config.PROCESSED / f"pred_{pool}.pkl")
    return pred, blenders


def market_goal_table(m: pd.DataFrame, idx, log=print) -> pd.DataFrame:
    """Market-implied expected goals for every match with prices (cached; slow least-squares)."""
    path = config.PROCESSED / "market_goals.pkl"
    cache = pd.read_pickle(path) if path.exists() else pd.DataFrame(columns=["mk_lh", "mk_la"])
    todo = [i for i in idx if i not in cache.index]
    rows = {}
    t = time.time()
    sub = m.loc[todo]
    for r in sub.itertuples():
        mi = market_inputs(r)
        if not mi["has_market"]:
            continue
        g = market_goals(mi, -0.06)
        if g:
            rows[r.Index] = g
    if rows:
        new = pd.DataFrame.from_dict(rows, orient="index", columns=["mk_lh", "mk_la"])
        cache = pd.concat([cache[~cache.index.isin(new.index)], new])
        cache.to_pickle(path)
    log(f"  market goals: {len(rows)} new fits in {time.time() - t:.0f}s (cache {len(cache)})")
    return cache.astype(float)


def train_production(pool: str, m: pd.DataFrame, f: pd.DataFrame, oos: pd.DataFrame, *, fast=False, log=print) -> dict:
    """Base learners on all data to date + blender from the latest OOS folds."""
    now = pd.Timestamp.now(tz="UTC")
    feats = feature_columns(f)
    tr = _train_mask(m, f, now, TRAIN_YEARS[pool])
    t = time.time()
    bm = BaseModels(feats, fast=fast).fit(f.loc[tr], m.loc[tr, "hg"].astype(int).values,
                                          m.loc[tr, "ag"].astype(int).values, _weights(m.loc[tr, "date"], now))
    played = (m.loc[oos.index, "status"] == "played") & m.loc[oos.index, "hg"].notna()
    last = sorted(oos["fold"].unique())[-3:]
    prev = oos[oos["fold"].isin(last) & played]
    b = Blender().fit(prev, m.loc[prev.index, "hg"].values, m.loc[prev.index, "ag"].values)
    bundle = {"pool": pool, "base": bm, "blender": b, "features": feats, "trained": now.isoformat(),
              "n_train": int(tr.sum())}
    config.MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, config.MODEL_DIR / f"model_{pool}.joblib", compress=3)
    log(f"  production {pool}: {tr.sum()} rows, {time.time() - t:.0f}s, weights {b.to_dict()}")
    return bundle


def load_production(pool: str) -> dict:
    return joblib.load(config.MODEL_DIR / f"model_{pool}.joblib")


def run_all(*, fast: bool = False, log=print):
    matches, _ = data_build.load()
    feats = compute_features(matches, log=log)
    result = {}
    for pool in ("club", "intl"):
        m, f, _ = feats[pool]
        oos = walk_forward(pool, m, f, fast=fast, log=log)
        pred, blenders = blend_folds(pool, m, f, oos, log=log)
        train_production(pool, m, f, oos, fast=fast, log=log)
        result[pool] = (m, f, pred, blenders)
    return result
