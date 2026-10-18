"""football-data.co.uk: historical results with Bet365 / exchange / market Asian-handicap,
goal-line and 1X2 prices (opening and closing), plus the weekly fixtures file with
current Bet365 Asian lines."""
from __future__ import annotations

import io
from datetime import date, datetime

import numpy as np
import pandas as pd

from .. import config, http

MAIN = "https://www.football-data.co.uk/mmz4281/{season}/{code}.csv"
EXTRA = "https://www.football-data.co.uk/new/{code}.csv"
FIXTURES = "https://www.football-data.co.uk/fixtures.csv"
CACHE = config.RAW / "footballdata"

# Canonical name -> candidate source columns, first non-null wins (older seasons used Betbrain 'Bb' columns).
ODDS_COLS = {
    # 1X2 pre-match
    "b365_h": ["B365H"], "b365_d": ["B365D"], "b365_a": ["B365A"],
    "ps_h": ["PSH"], "ps_d": ["PSD"], "ps_a": ["PSA"],
    "avg_h": ["AvgH", "BbAvH"], "avg_d": ["AvgD", "BbAvD"], "avg_a": ["AvgA", "BbAvA"],
    "max_h": ["MaxH", "BbMxH"], "max_d": ["MaxD", "BbMxD"], "max_a": ["MaxA", "BbMxA"],
    "bfe_h": ["BFEH"], "bfe_d": ["BFED"], "bfe_a": ["BFEA"],
    # 1X2 closing
    "b365c_h": ["B365CH"], "b365c_d": ["B365CD"], "b365c_a": ["B365CA"],
    "psc_h": ["PSCH"], "psc_d": ["PSCD"], "psc_a": ["PSCA"],
    "avgc_h": ["AvgCH"], "avgc_d": ["AvgCD"], "avgc_a": ["AvgCA"],
    "bfec_h": ["BFECH"], "bfec_d": ["BFECD"], "bfec_a": ["BFECA"],
    # Goal line 2.5
    "b365_o25": ["B365>2.5"], "b365_u25": ["B365<2.5"],
    "ps_o25": ["P>2.5"], "ps_u25": ["P<2.5"],
    "avg_o25": ["Avg>2.5", "BbAv>2.5"], "avg_u25": ["Avg<2.5", "BbAv<2.5"],
    "max_o25": ["Max>2.5", "BbMx>2.5"], "max_u25": ["Max<2.5", "BbMx<2.5"],
    "bfe_o25": ["BFE>2.5"], "bfe_u25": ["BFE<2.5"],
    "b365c_o25": ["B365C>2.5"], "b365c_u25": ["B365C<2.5"],
    "psc_o25": ["PC>2.5"], "psc_u25": ["PC<2.5"],
    "avgc_o25": ["AvgC>2.5"], "avgc_u25": ["AvgC<2.5"],
    "bfec_o25": ["BFEC>2.5"], "bfec_u25": ["BFEC<2.5"],
    # Asian handicap (line is the HOME handicap)
    "ah_line": ["AHh", "BbAHh"],
    "b365_ahh": ["B365AHH"], "b365_aha": ["B365AHA"],
    "ps_ahh": ["PAHH"], "ps_aha": ["PAHA"],
    "avg_ahh": ["AvgAHH", "BbAvAHH"], "avg_aha": ["AvgAHA", "BbAvAHA"],
    "max_ahh": ["MaxAHH", "BbMxAHH"], "max_aha": ["MaxAHA", "BbMxAHA"],
    "bfe_ahh": ["BFEAHH"], "bfe_aha": ["BFEAHA"],
    "ahc_line": ["AHCh"],
    "b365c_ahh": ["B365CAHH"], "b365c_aha": ["B365CAHA"],
    "psc_ahh": ["PCAHH"], "psc_aha": ["PCAHA"],
    "avgc_ahh": ["AvgCAHH"], "avgc_aha": ["AvgCAHA"],
    "bfec_ahh": ["BFECAHH"], "bfec_aha": ["BFECAHA"],
    # Match statistics
    "hst": ["HST"], "ast": ["AST"], "hsh": ["HS"], "ash": ["AS"], "hc": ["HC"], "ac": ["AC"],
    "hxg": ["HxG"], "axg": ["AxG"],
}


def season_code(start_year: int) -> str:
    return f"{start_year % 100:02d}{(start_year + 1) % 100:02d}"


def _read_csv(text: str) -> pd.DataFrame:
    # Some historical files carry trailing empty columns / latin-1 bytes.
    return pd.read_csv(io.StringIO(text), on_bad_lines="skip", low_memory=False)


def _decode(content: bytes) -> str:
    for enc in ("utf-8-sig", "latin-1"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _parse_date(s: pd.Series) -> pd.Series:
    d = pd.to_datetime(s, format="%d/%m/%Y", errors="coerce")
    d2 = pd.to_datetime(s, format="%d/%m/%y", errors="coerce")
    return d.fillna(d2)


def normalise(df: pd.DataFrame, *, home_col="HomeTeam", away_col="AwayTeam") -> pd.DataFrame:
    df = df.dropna(how="all")
    if home_col not in df.columns and "Home" in df.columns:
        home_col, away_col = "Home", "Away"
    df = df[df[home_col].notna() & df[away_col].notna()].copy()
    out = pd.DataFrame({
        "div": df.get("Div", pd.Series(index=df.index, dtype=object)),
        "date": _parse_date(df["Date"].astype(str)),
        "time": df.get("Time", pd.Series(index=df.index, dtype=object)),
        "fd_home": df[home_col].astype(str).str.strip(),
        "fd_away": df[away_col].astype(str).str.strip(),
    })
    for hg, ag in (("FTHG", "FTAG"), ("HG", "AG")):
        if hg in df.columns:
            out["fd_hg"] = pd.to_numeric(df[hg], errors="coerce")
            out["fd_ag"] = pd.to_numeric(df[ag], errors="coerce")
            break
    for name, cands in ODDS_COLS.items():
        col = None
        for c in cands:
            if c in df.columns:
                v = pd.to_numeric(df[c], errors="coerce")
                col = v if col is None else col.fillna(v)
        out[name] = col if col is not None else np.nan
    return out.reset_index(drop=True)


def fetch_main(code: str, start_year: int, *, force: bool = False) -> pd.DataFrame | None:
    path = CACHE / code / f"{season_code(start_year)}.csv"
    current = start_year >= _current_season_start()
    if path.exists() and not force:
        age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
        if not current or age_h < 6:
            return normalise(_read_csv(path.read_text(encoding="utf-8")))
    r = http.get(MAIN.format(season=season_code(start_year), code=code), ok_404=True)
    if r is None or len(r.content) < 200:
        return None
    text = _decode(r.content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return normalise(_read_csv(text))


def fetch_extra(code: str, *, force: bool = False) -> pd.DataFrame | None:
    path = CACHE / "extra" / f"{code}.csv"
    if path.exists() and not force:
        age_h = (datetime.now().timestamp() - path.stat().st_mtime) / 3600
        if age_h < 12:
            return normalise(_read_csv(path.read_text(encoding="utf-8")))
    r = http.get(EXTRA.format(code=code), ok_404=True)
    if r is None:
        return None
    text = _decode(r.content)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return normalise(_read_csv(text))


def fetch_fixtures() -> pd.DataFrame:
    """Upcoming fixtures with current Bet365 / market Asian lines (refreshed by football-data twice a week)."""
    r = http.get(FIXTURES)
    text = _decode(r.content)
    path = CACHE / "fixtures" / f"fixtures_{date.today():%Y%m%d}.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return normalise(_read_csv(text))


def _current_season_start() -> int:
    t = date.today()
    return t.year if t.month >= 7 else t.year - 1


def prefetch(log=print, workers: int = 4):
    """Download missing / stale season files in parallel (each request takes several seconds)."""
    from concurrent.futures import ThreadPoolExecutor

    cur = _current_season_start()
    jobs = []
    for meta in config.COMPETITIONS.values():
        code = meta.get("fd")
        if not code:
            continue
        for y in range(max(meta["start"] - 1, 2005), cur + 1):
            path = CACHE / code / f"{season_code(y)}.csv"
            if not path.exists() or y >= cur:
                jobs.append((code, y))
    if not jobs:
        return

    def job(arg):
        code, y = arg
        try:
            fetch_main(code, y)
            return None
        except Exception as exc:
            return f"{code} {y}: {exc}"

    with ThreadPoolExecutor(max_workers=workers) as ex:
        errs = [e for e in ex.map(job, jobs) if e]
    log(f"  football-data: fetched {len(jobs) - len(errs)}/{len(jobs)} files" + (f", errors: {errs[:3]}" if errs else ""))


def load_history(log=print) -> pd.DataFrame:
    """Every configured football-data league-season, tagged with its ESPN slug."""
    prefetch(log=log)
    frames = []
    cur = _current_season_start()
    for slug, meta in config.COMPETITIONS.items():
        code = meta.get("fd")
        if code:
            first = max(meta["start"] - 1, 2005)
            for y in range(first, cur + 1):
                try:
                    df = fetch_main(code, y)
                except Exception as exc:
                    log(f"  ! football-data {code} {y}: {exc}")
                    continue
                if df is None or df.empty:
                    continue
                df["slug"] = slug
                df["fd_season"] = y
                frames.append(df)
        if meta.get("fd_extra"):
            try:
                df = fetch_extra(meta["fd_extra"])
            except Exception as exc:
                log(f"  ! football-data extra {meta['fd_extra']}: {exc}")
                df = None
            if df is not None and not df.empty:
                df["slug"] = slug
                df["fd_season"] = df["date"].dt.year
                frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


FD_DIV_TO_SLUG = {m["fd"]: s for s, m in config.COMPETITIONS.items() if m.get("fd")}
