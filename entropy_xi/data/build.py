"""Build the unified match table.

pool "club": ESPN events (global team ids) enriched with football-data odds/stats.
pool "intl": martj42 history (1872-) + ESPN international fixtures/live lines.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np
import pandas as pd

from .. import config
from . import espn, footballdata, internationals
from .names import norm, similarity

PLAYED = {"STATUS_FULL_TIME", "STATUS_FINAL_AET", "STATUS_FINAL_PEN", "STATUS_FINAL"}
SCHEDULED = {"STATUS_SCHEDULED", "STATUS_TBD", "STATUS_DELAYED"}
COUNTRY_ALIASES = {"turkiye": "turkey", "usa": "united states", "united states of america": "united states",
                   "korea republic": "south korea", "czechia": "czech republic"}


ESPN_ODDS_FIELDS = ["ml_home_open", "ml_draw_open", "ml_away_open", "ml_home_close", "ml_draw_close", "ml_away_close",
                    "ou_line_open", "ou_over_open", "ou_under_open", "ou_line_close", "ou_over_close", "ou_under_close",
                    "sp_home_line_close", "sp_home_close", "sp_away_close"]


def _espn_odds(e: dict) -> dict:
    o = e.get("odds") or {}
    out = {k: o.get(k) for k in ESPN_ODDS_FIELDS}
    out["odds_provider"] = o.get("provider")
    return out


def _country(s) -> str | None:
    if not s or not isinstance(s, str):
        return None
    n = norm(s)
    return COUNTRY_ALIASES.get(n, n)


# ---------------------------------------------------------------------------
# Club pool
# ---------------------------------------------------------------------------
def club_matches(events: list[dict]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows, teams = [], {}
    for e in events:
        meta = config.COMPETITIONS.get(e["slug"])
        if not meta or meta["group"] == "intl":
            continue
        st = e["status"]
        if st in PLAYED:
            status = "played" if e["hg90"] is not None else "void"
        elif st in SCHEDULED:
            status = "scheduled"
        else:
            status = "void"  # postponed / cancelled / abandoned
        hst, ast = e.get("hstat") or {}, e.get("astat") or {}
        rows.append({
            "mid": e["id"], "pool": "club", "comp": e["slug"], "group": meta["group"], "season": e["season"],
            "phase": e.get("phase"), "date": e["date"], "home": "c" + e["home_id"], "away": "c" + e["away_id"],
            "home_name": e["home"], "away_name": e["away"], "hg": e["hg90"], "ag": e["ag90"],
            "hs_full": e["hs"], "as_full": e["as"], "status": status, "espn_status": st,
            "venue_country": _country(e.get("venue_country")), "note": e.get("note"), "leg": e.get("leg"),
            "h_sot": hst.get("sot"), "a_sot": ast.get("sot"), "h_shots": hst.get("shots"), "a_shots": ast.get("shots"),
            "h_corners": hst.get("corners"), "a_corners": ast.get("corners"), "h_poss": hst.get("poss"),
            **_espn_odds(e),
        })
        for side in ("home", "away"):
            tid = "c" + e[f"{side}_id"]
            t = teams.setdefault(tid, {"key": tid, "name": e[side], "abbr": e.get(f"{side}_abbr"),
                                       "color": e.get(f"{side}_color"), "pool": "club", "leagues": Counter()})
            t["name"] = e[side] or t["name"]
            if meta["group"] == "league":
                t["leagues"][e["slug"]] += 1
    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"], utc=True, errors="coerce")
    df = df.dropna(subset=["date"]).sort_values(["date", "mid"]).reset_index(drop=True)

    tdf = pd.DataFrame(teams.values())
    tdf["league"] = tdf["leagues"].apply(lambda c: c.most_common(1)[0][0] if c else None)
    tdf["country"] = tdf["league"].map(lambda s: _country(config.COMPETITIONS.get(s, {}).get("country")) if s else None)
    tdf = tdf.drop(columns=["leagues"])

    # Neutral venue: cup tie played in a country that is not the home club's.
    country = dict(zip(tdf["key"], tdf["country"]))
    hc = df["home"].map(country)
    df["neutral"] = (df["group"] == "cup") & df["venue_country"].notna() & hc.notna() & (df["venue_country"] != hc)
    return df, tdf


def _link_names(fd: pd.DataFrame, es: pd.DataFrame) -> dict[str, str]:
    """Vote FD team name -> ESPN team key using same-date fixtures (+ score agreement)."""
    votes: dict[str, Counter] = defaultdict(Counter)
    es_by_day = defaultdict(list)
    for r in es.itertuples(index=False):
        es_by_day[r.day].append(r)
    for r in fd.itertuples(index=False):
        cands = es_by_day.get(r.day, []) + es_by_day.get(r.day - 1, []) + es_by_day.get(r.day + 1, [])
        best, best_s = None, 0.0
        for c in cands:
            s = similarity(r.fd_home, c.home_name) + similarity(r.fd_away, c.away_name)
            if not np.isnan(r.fd_hg) and c.hs_full is not None and not pd.isna(c.hs_full):
                s += 0.6 if (r.fd_hg == c.hs_full and r.fd_ag == c.as_full) else -0.6
            if s > best_s:
                best, best_s = c, s
        if best is not None and best_s >= 1.4:
            votes[r.fd_home][best.home] += 1
            votes[r.fd_away][best.away] += 1
    mapping = {}
    for name, cnt in votes.items():
        key, n = cnt.most_common(1)[0]
        if n >= 2 and n >= 0.6 * sum(cnt.values()):
            mapping[name] = key
    return mapping


def link_footballdata(club: pd.DataFrame, fd: pd.DataFrame, log=print) -> tuple[pd.DataFrame, dict]:
    """Attach football-data odds & stats to ESPN club matches. Returns (club, name maps per slug)."""
    if fd.empty:
        return club, {}
    epoch = pd.Timestamp("1970-01-01")
    club = club.copy()
    club["day"] = ((club["date"].dt.tz_convert(None).dt.normalize()) - epoch).dt.days
    fd = fd.dropna(subset=["date"]).copy()
    fd["day"] = (fd["date"] - epoch).dt.days
    odds_cols = [c for c in footballdata.ODDS_COLS]
    maps = {}
    linked_parts = []
    for slug, f in fd.groupby("slug"):
        es = club[club["comp"] == slug]
        if es.empty:
            continue
        mp = _link_names(f, es)
        maps[slug] = mp
        f = f.assign(home=f["fd_home"].map(mp), away=f["fd_away"].map(mp)).dropna(subset=["home", "away"])
        idx = {}
        for r in es[["mid", "home", "away", "day"]].itertuples(index=False):
            idx[(r.home, r.away, r.day)] = r.mid
        mids = []
        for r in f[["home", "away", "day"]].itertuples(index=False):
            mid = idx.get((r.home, r.away, r.day)) or idx.get((r.home, r.away, r.day - 1)) or idx.get((r.home, r.away, r.day + 1))
            mids.append(mid)
        f = f.assign(mid=mids).dropna(subset=["mid"])
        unmapped = sorted(set(fd.loc[fd["slug"] == slug, "fd_home"]) - set(mp))
        log(f"  link {slug:8s}: {len(f):5d}/{len(fd[fd['slug'] == slug]):5d} rows, unmapped names: {unmapped[:8]}")
        linked_parts.append(f[["mid"] + odds_cols])
    if linked_parts:
        lk = pd.concat(linked_parts).drop_duplicates("mid", keep="last")
        club = club.merge(lk, on="mid", how="left")
    return club.drop(columns=["day"]), maps


# ---------------------------------------------------------------------------
# International pool
# ---------------------------------------------------------------------------
def intl_matches(events: list[dict], mj: pd.DataFrame, log=print) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    mj_names = sorted(set(mj["home_team"]) | set(mj["away_team"]))
    recent = mj[mj["date"] >= mj["date"].max() - pd.Timedelta(days=3650)]
    recent_names = sorted(set(recent["home_team"]) | set(recent["away_team"]))
    by_norm = {norm(n): n for n in mj_names}

    def to_mj(name: str) -> str | None:
        n = norm(name)
        if n in by_norm:
            return by_norm[n]
        best, bs = None, 0.0
        for cand in recent_names:
            s = similarity(name, cand)
            if s > bs:
                best, bs = cand, s
        return best if bs >= 0.86 else None

    rows = []
    for r in mj.itertuples(index=False):
        played = not (pd.isna(r.home_score) or pd.isna(r.away_score))
        rows.append({
            "mid": None, "pool": "intl", "comp": "mj:" + r.tournament,
            "group": "intl", "season": r.date.year, "phase": None, "date": r.date.tz_localize("UTC") + pd.Timedelta(hours=18),
            "home": "n:" + r.home_team, "away": "n:" + r.away_team, "home_name": r.home_team, "away_name": r.away_team,
            "hg": r.home_score if played else None, "ag": r.away_score if played else None,
            "status": "played" if played else "scheduled", "neutral": bool(r.neutral), "tournament": r.tournament,
        })
    df = pd.DataFrame(rows)
    df["mid"] = ["mj" + str(i) for i in range(len(df))]

    espn_name_map, unmatched = {}, set()
    erows = []
    for e in events:
        meta = config.COMPETITIONS.get(e["slug"])
        if not meta or meta["group"] != "intl":
            continue
        h, a = to_mj(e["home"]), to_mj(e["away"])
        espn_name_map[e["home_id"]] = h
        espn_name_map[e["away_id"]] = a
        if h is None:
            unmatched.add(e["home"])
        if a is None:
            unmatched.add(e["away"])
        if h is None or a is None:
            continue
        st = e["status"]
        status = ("played" if e["hg90"] is not None else "void") if st in PLAYED else ("scheduled" if st in SCHEDULED else "void")
        vc = _country(e.get("venue_country"))
        neutral = bool(vc) and vc != _country(h)
        erows.append({
            "mid": e["id"], "pool": "intl", "comp": e["slug"], "group": "intl", "season": e["season"], "phase": e.get("phase"),
            "date": e["date"], "home": "n:" + h, "away": "n:" + a, "home_name": h, "away_name": a,
            "hg": e["hg90"], "ag": e["ag90"], "hs_full": e["hs"], "as_full": e["as"], "status": status, "espn_status": st,
            "neutral": neutral, "tournament": config.ESPN_TO_MJ_TOURNAMENT.get(e["slug"], "Friendly"),
            "note": e.get("note"),
            "h_sot": (e.get("hstat") or {}).get("sot"), "a_sot": (e.get("astat") or {}).get("sot"),
            **_espn_odds(e),
        })
    if unmatched:
        log(f"  intl: {len(unmatched)} ESPN national-team names unmatched, e.g. {sorted(unmatched)[:10]}")
    ed = pd.DataFrame(erows)
    if not ed.empty:
        ed["date"] = pd.to_datetime(ed["date"], utc=True, errors="coerce")
        ed["day"] = ed["date"].dt.tz_convert(None).dt.normalize()
        df["day"] = df["date"].dt.tz_convert(None).dt.normalize()
        # Prefer the ESPN row (has kick-off time, ids, stats); drop martj42 duplicates within ±1 day.
        keys = set()
        for r in ed.itertuples(index=False):
            for dd in (-1, 0, 1):
                keys.add((r.home, r.away, r.day + pd.Timedelta(days=dd)))
        dup = [(h, a, d) in keys for h, a, d in zip(df["home"], df["away"], df["day"])]
        df = df[~np.array(dup)]
        df = pd.concat([df, ed], ignore_index=True).drop(columns=["day"])
    df["date"] = pd.to_datetime(df["date"], utc=True)
    df = df.sort_values(["date", "mid"]).reset_index(drop=True)
    names = sorted(set(df["home_name"]) | set(df["away_name"]))
    tdf = pd.DataFrame({"key": ["n:" + n for n in names], "name": names, "abbr": [n[:3].upper() for n in names],
                        "color": None, "pool": "intl", "league": None, "country": [_country(n) for n in names]})
    return df, tdf, espn_name_map


# ---------------------------------------------------------------------------
def build(log=print) -> dict:
    config.PROCESSED.mkdir(parents=True, exist_ok=True)
    log("Loading ESPN events ...")
    events = espn.load_all(log=log)
    log(f"  {len(events)} events")
    club, club_teams = club_matches(events)
    log(f"  club matches: {len(club)} ({(club['status'] == 'played').sum()} played)")

    log("Loading football-data odds ...")
    fd = footballdata.load_history(log=log)
    club, name_maps = link_footballdata(club, fd, log=log)

    log("Loading international history ...")
    mj = internationals.load()
    intl, intl_teams, espn_nt = intl_matches(events, mj, log=log)
    log(f"  international matches: {len(intl)}")

    matches = pd.concat([club, intl], ignore_index=True, sort=False)
    teams = pd.concat([club_teams, intl_teams], ignore_index=True, sort=False)
    matches.to_pickle(config.PROCESSED / "matches.pkl")
    teams.to_pickle(config.PROCESSED / "teams.pkl")
    pd.to_pickle({"fd_names": name_maps, "espn_nt": espn_nt}, config.PROCESSED / "name_maps.pkl")
    log(f"Saved {len(matches)} matches, {len(teams)} teams")
    return {"matches": matches, "teams": teams, "name_maps": name_maps, "espn_nt": espn_nt}


def load() -> tuple[pd.DataFrame, pd.DataFrame]:
    return pd.read_pickle(config.PROCESSED / "matches.pkl"), pd.read_pickle(config.PROCESSED / "teams.pkl")
