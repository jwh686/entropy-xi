"""ESPN public scoreboard feed: results, fixtures, match stats and live DraftKings lines.

ESPN team ids are global across competitions, which lets one rating system link
domestic leagues with European / Asian cups without any name matching.
"""
from __future__ import annotations

import gzip
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

from .. import config, http

BASE = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard?dates={dates}&limit=1000"
CACHE = config.RAW / "espn"

_MINUTE_RE = re.compile(r"(\d+)'")


def american_to_decimal(v) -> float | None:
    if v is None:
        return None
    s = str(v).strip().upper()
    if s in ("", "OFF", "N/A", "-"):
        return None
    if s == "EVEN":
        return 2.0
    try:
        a = float(s.replace("+", ""))
    except ValueError:
        return None
    if a == 0:
        return None
    return round(1 + a / 100, 4) if a > 0 else round(1 + 100 / abs(a), 4)


def _line(s) -> float | None:
    if s is None:
        return None
    m = re.search(r"[-+]?\d+(\.\d+)?", str(s))
    return float(m.group(0)) if m else None


def _parse_odds(odds_list) -> dict | None:
    if not odds_list or not odds_list[0]:
        return None
    o = odds_list[0]
    out: dict = {"provider": (o.get("provider") or {}).get("name")}
    ml = o.get("moneyline") or {}
    for side in ("home", "draw", "away"):
        node = ml.get(side) or {}
        for phase in ("open", "close"):
            out[f"ml_{side}_{phase}"] = american_to_decimal((node.get(phase) or {}).get("odds"))
    # Legacy layout.
    if out.get("ml_home_close") is None and o.get("homeTeamOdds"):
        out["ml_home_close"] = american_to_decimal(o["homeTeamOdds"].get("moneyLine"))
        out["ml_away_close"] = american_to_decimal((o.get("awayTeamOdds") or {}).get("moneyLine"))
        out["ml_draw_close"] = american_to_decimal((o.get("drawOdds") or {}).get("moneyLine"))
    tot = o.get("total") or {}
    for side in ("over", "under"):
        node = tot.get(side) or {}
        for phase in ("open", "close"):
            p = node.get(phase) or {}
            out[f"ou_{side}_{phase}"] = american_to_decimal(p.get("odds"))
            if side == "over":
                out[f"ou_line_{phase}"] = _line(p.get("line"))
    if out.get("ou_line_close") is None:
        out["ou_line_close"] = o.get("overUnder")
    sp = o.get("pointSpread") or {}
    for side in ("home", "away"):
        node = sp.get(side) or {}
        for phase in ("open", "close"):
            p = node.get(phase) or {}
            out[f"sp_{side}_{phase}"] = american_to_decimal(p.get("odds"))
            out[f"sp_{side}_line_{phase}"] = _line(p.get("line"))
    if all(v is None for k, v in out.items() if k != "provider"):
        return None
    return out


def _stat_map(comp) -> dict:
    m = {}
    for s in comp.get("statistics") or []:
        name, val = s.get("name"), s.get("displayValue")
        try:
            val = float(val)
        except (TypeError, ValueError):
            continue
        key = {"shotsOnTarget": "sot", "totalShots": "shots", "possessionPct": "poss", "wonCorners": "corners"}.get(name)
        if key:
            m[key] = val
    return m


def _minute(display: str | None) -> int | None:
    if not display:
        return None
    m = _MINUTE_RE.search(display)
    return int(m.group(1)) if m else None


def parse_event(e: dict, slug: str) -> dict | None:
    try:
        c = e["competitions"][0]
        comps = c["competitors"]
        home = next(x for x in comps if x.get("homeAway") == "home")
        away = next(x for x in comps if x.get("homeAway") == "away")
    except (KeyError, IndexError, StopIteration):
        return None
    st = c.get("status", {}).get("type", {})
    goals = []
    for d in c.get("details") or []:
        if not d.get("scoringPlay"):
            continue
        goals.append([
            (d.get("clock") or {}).get("displayValue"),
            (d.get("team") or {}).get("id"),
            int(bool(d.get("ownGoal"))), int(bool(d.get("penaltyKick"))), int(bool(d.get("shootout"))),
        ])

    def score(x):
        try:
            return int(float(x.get("score")))
        except (TypeError, ValueError):
            return None

    hs, as_ = score(home), score(away)
    status = st.get("name", "")
    hg90, ag90 = (hs, as_) if status == "STATUS_FULL_TIME" else (None, None)
    if status in ("STATUS_FINAL_AET", "STATUS_FINAL_PEN") and hs is not None:
        reg = [g for g in goals if not g[4] and (_minute(g[0]) or 999) <= 90]
        et = [g for g in goals if not g[4] and (_minute(g[0]) or 0) > 90]
        if goals and (len(reg) + len(et)) == hs + as_:
            hg90 = sum(1 for g in reg if g[1] == home["team"]["id"])
            ag90 = sum(1 for g in reg if g[1] == away["team"]["id"])
        elif not et and status == "STATUS_FINAL_PEN" and not goals and hs == as_:
            hg90, ag90 = hs, as_
    venue = c.get("venue") or {}
    addr = venue.get("address") or {}
    notes = c.get("notes") or []
    season = e.get("season") or {}
    ht, at = home["team"], away["team"]
    return {
        "id": str(e["id"]), "slug": slug, "date": e.get("date") or c.get("date"),
        "season": season.get("year"), "phase": season.get("slug"),
        "status": status, "completed": bool(st.get("completed")),
        "home_id": str(ht["id"]), "away_id": str(at["id"]),
        "home": ht.get("displayName"), "away": at.get("displayName"),
        "home_abbr": ht.get("abbreviation"), "away_abbr": at.get("abbreviation"),
        "home_color": ht.get("color"), "away_color": at.get("color"),
        "hs": hs, "as": as_, "hg90": hg90, "ag90": ag90,
        "hstat": _stat_map(home), "astat": _stat_map(away),
        "goals": goals,
        "venue_city": addr.get("city"), "venue_country": addr.get("country"),
        "home_venue": (ht.get("venue") or {}).get("id"), "venue_id": venue.get("id"),
        "note": notes[0].get("headline") if notes else None,
        "leg": (c.get("leg") or {}).get("value"),
        "odds": _parse_odds(c.get("odds")),
    }


def _fetch(slug: str, dates: str) -> list[dict]:
    r = http.get(BASE.format(slug=slug, dates=dates), timeout=90)
    events = r.json().get("events", []) if r is not None else []
    out = []
    for e in events:
        p = parse_event(e, slug)
        if p:
            out.append(p)
    return out


def _cache_path(slug: str, year: int) -> Path:
    return CACHE / slug / f"{year}.json.gz"


def fetch_year(slug: str, year: int, *, force: bool = False) -> list[dict]:
    """All events of a calendar year. Past years are cached permanently."""
    path = _cache_path(slug, year)
    fresh_needed = year >= date.today().year - 1
    if path.exists() and not force and not fresh_needed:
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    if path.exists() and not force and fresh_needed:
        age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
        if age_h < 6:
            with gzip.open(path, "rt", encoding="utf-8") as f:
                return json.load(f)
    events = _fetch(slug, str(year))
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, separators=(",", ":"))
    return events


def fetch_day(slug: str, day: date) -> list[dict]:
    """Events on one date (used for live odds snapshots and fast settlement)."""
    return _fetch(slug, day.strftime("%Y%m%d"))


def load_all(slugs=None, *, log=print) -> list[dict]:
    """Download (or read from cache) every configured competition-year."""
    this_year = date.today().year
    out: dict[str, dict] = {}
    for slug, meta in config.COMPETITIONS.items():
        if slugs and slug not in slugs:
            continue
        for year in range(meta["start"], this_year + 1):
            try:
                evs = fetch_year(slug, year, force=False)
            except Exception as exc:  # network trouble on one file should not stop the pipeline
                log(f"  ! {slug} {year}: {exc}")
                continue
            for ev in evs:
                out.setdefault(ev["id"], ev)  # config order = priority (main comp before qualifier feed)
    return list(out.values())


def snapshot_time() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
