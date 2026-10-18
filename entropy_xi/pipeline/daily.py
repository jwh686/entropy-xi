"""The daily job.

1. Refresh sources (ESPN current year + next-days odds, football-data current season and
   fixtures with Bet365 Asian lines, international results).
2. Rebuild the match table and features (walk-forward pass up to today).
3. Retrain production models weekly (or on demand).
4. Publish predictions for matches kicking off in the next window; freeze them in the ledger.
5. Settle every pending record whose match has finished (90-minute score).
6. Export website data.
"""
from __future__ import annotations

import gzip
import json
from datetime import date, timedelta

import joblib
import pandas as pd

from .. import config
from ..data import build as data_build
from ..data import espn, footballdata, internationals
from ..models import picks as pk
from ..models.meta import frame
from . import export, ledger, train
from .predict import build_record, settle_record

RETRAIN_DAYS = 7


def refresh_sources(log=print):
    today = date.today()
    years = [today.year] + ([today.year - 1] if today.month == 1 else [])
    for slug, meta in config.COMPETITIONS.items():
        for y in years:
            if y < meta["start"]:
                continue
            try:
                evs = espn.fetch_year(slug, y, force=True)
            except Exception as exc:
                log(f"  ! ESPN {slug} {y}: {exc}")
                continue
            if not meta["display"]:
                continue
            # Next-days scoreboards carry the freshest DraftKings lines; merge them into the cache.
            soon = {(today + timedelta(days=d)).isoformat() for d in range(0, 3)}
            if not any(e["status"] == "STATUS_SCHEDULED" and (e["date"] or "")[:10] in soon for e in evs):
                continue
            fresh = {}
            for d in range(0, 3):
                try:
                    for e in espn.fetch_day(slug, today + timedelta(days=d)):
                        fresh[e["id"]] = e
                except Exception as exc:
                    log(f"  ! ESPN day {slug}: {exc}")
            if fresh:
                path = espn._cache_path(slug, y)
                merged = [fresh.pop(e["id"], e) for e in evs] + [e for e in fresh.values() if (e["date"] or "")[:4] == str(y)]
                with gzip.open(path, "wt", encoding="utf-8") as f:
                    json.dump(merged, f, ensure_ascii=False, separators=(",", ":"))
    # Current-season football-data files and international results are force-refreshed: file
    # mtimes are unreliable after a CI cache restore, so age-based freshness checks cannot be trusted.
    season = footballdata._current_season_start()
    for slug, meta in config.COMPETITIONS.items():
        try:
            if meta.get("fd"):
                footballdata.fetch_main(meta["fd"], season, force=True)
            if meta.get("fd_extra"):
                footballdata.fetch_extra(meta["fd_extra"], force=True)
        except Exception as exc:
            log(f"  ! football-data {slug}: {exc}")
    try:
        internationals.load(max_age_h=0)
    except Exception as exc:
        log(f"  ! international results: {exc}")


def attach_fixture_odds(m: pd.DataFrame, idx, log=print) -> pd.DataFrame:
    """Merge football-data fixtures.csv (current Bet365 Asian lines) onto upcoming ESPN matches."""
    try:
        fx = footballdata.fetch_fixtures()
    except Exception as exc:
        log(f"  ! fixtures.csv: {exc}")
        return m
    maps = pd.read_pickle(config.PROCESSED / "name_maps.pkl")["fd_names"]
    fx["slug"] = fx["div"].map(footballdata.FD_DIV_TO_SLUG)
    fx = fx.dropna(subset=["slug"])
    sub = m.loc[idx]
    key = {}
    for i, r in sub.iterrows():
        d = r["date"].tz_convert("Europe/London").date() if r["date"].tzinfo else r["date"].date()
        key[(r["comp"], r["home"], r["away"], d)] = i
    n = 0
    odds_cols = list(footballdata.ODDS_COLS)
    for r in fx.itertuples(index=False):
        mp = maps.get(r.slug, {})
        h, a = mp.get(r.fd_home), mp.get(r.fd_away)
        if not h or not a or pd.isna(r.date):
            continue
        for dd in (0, -1, 1):
            i = key.get((r.slug, h, a, (r.date + pd.Timedelta(days=dd)).date()))
            if i is not None:
                for c in odds_cols:
                    v = getattr(r, c, None)
                    if v is not None and not pd.isna(v):
                        m.at[i, c] = v
                n += 1
                break
    log(f"  fixtures.csv: Bet365 lines attached to {n} upcoming matches")
    return m


def predict_records(up: pd.DataFrame, f: pd.DataFrame, bundle: dict, mac_model, now_iso: str):
    """Yield (record, kickoff) for the given upcoming matches with the production models."""
    comp = bundle["base"].predict(f.loc[up.index])
    pred = bundle["blender"].combine(comp)
    pred["rho"] = bundle["blender"].rho
    # market-implied goals, then the market-anchored correction for league matches
    mkts = {}
    for mr in up.itertuples():
        mi = pk.market_inputs(mr)
        mkts[mr.Index] = pk.market_goals(mi, bundle["blender"].rho) if mi["has_market"] else None
    mac = {}
    have = {i: g for i, g in mkts.items() if g}
    if mac_model is not None and have:
        mg = pd.DataFrame(have, index=["mk_lh", "mk_la"]).T.astype(float)
        lg = [i for i in mg.index if up.at[i, "group"] == "league"]
        if lg:
            mp = mac_model.predict(frame(f.loc[lg], pred.loc[lg], mg.loc[lg]))
            mac = {i: (mp.at[i, "mac_lh"], mp.at[i, "mac_la"]) for i in mp.index}
    for mr, fr, pr in zip(up.itertuples(), f.loc[up.index].itertuples(), pred.itertuples()):
        rec = build_record(mr, fr, pr, mode="live", published=now_iso, mac=mac.get(mr.Index), mkt=mkts[mr.Index])
        yield rec, mr.date


def run(*, retrain: bool = False, network: bool = True, log=print):
    now = pd.Timestamp.now(tz="UTC")
    now_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if network:
        log("Refreshing sources ...")
        refresh_sources(log=log)
    log("Rebuilding match table ...")
    data_build.build(log=log)
    matches, _ = data_build.load()
    log("Computing features ...")
    feats = train.compute_features(matches, log=log)

    led = ledger.load()
    mac_path = config.MODEL_DIR / "mac.joblib"
    mac_model = joblib.load(mac_path) if mac_path.exists() else None
    window_end = now + pd.Timedelta(hours=config.PUBLISH_WINDOW_HOURS)
    preview_end = now + pd.Timedelta(hours=config.PREVIEW_WINDOW_HOURS)
    published, preview = 0, []
    for pool in ("club", "intl"):
        m, f, _ = feats[pool]
        model_path = config.MODEL_DIR / f"model_{pool}.joblib"
        bundle = train.load_production(pool) if model_path.exists() else None
        stale = bundle is None or (now - pd.Timestamp(bundle["trained"])).days >= RETRAIN_DAYS
        if (retrain or stale) and (config.PROCESSED / f"oos_{pool}.pkl").exists():
            log(f"Retraining production model ({pool}) ...")
            bundle = train.train_production(pool, m, f, pd.read_pickle(config.PROCESSED / f"oos_{pool}.pkl"), log=log)
        if bundle is None:
            log(f"  ! no model for {pool}; run `python -m entropy_xi train` first")
            continue
        up = m[(m["status"] == "scheduled") & (m["date"] >= now) & (m["date"] <= preview_end)
               & m["comp"].isin(config.DISPLAY_COMPS)]
        if up.empty:
            log(f"  {pool}: no display matches in the next {config.PREVIEW_WINDOW_HOURS}h")
            continue
        if pool == "club" and network:
            m = attach_fixture_odds(m, up.index, log=log)
            up = m.loc[up.index]
        for rec, ko in predict_records(up, f, bundle, mac_model, now_iso):
            if ko <= window_end:
                published += int(ledger.publish(led, rec, now_iso))
            else:
                rec["mode"] = "preview"  # shown on the site, not frozen, no stars until it enters the window
                for p in rec["picks"].values():
                    p["stars"] = 0
                rec["best_stars"] = 0
                preview.append(rec)
    log(f"Published {published} new match predictions; {len(preview)} in preview")
    ledger.save({r["mid"]: r for r in preview}, ledger.PREVIEW)

    # Settle
    allm = matches.set_index("mid")
    settled = 0
    for mid, rec in led.items():
        if rec["status"] != "pending" or rec["kickoff"] > now_iso or mid not in allm.index:
            continue
        r = allm.loc[mid]
        if isinstance(r, pd.DataFrame):
            r = r.iloc[0]
        if r["status"] == "played" and pd.notna(r["hg"]):
            settle_record(rec, r["hg"], r["ag"], "played")
            settled += 1
        elif r["status"] == "void" and (now - pd.Timestamp(rec["kickoff"])).days >= 2:
            settle_record(rec, None, None, "void")
            settled += 1
    log(f"Settled {settled} records")
    ledger.save(led)
    export.run(log=log, matches=matches, feats=feats)
