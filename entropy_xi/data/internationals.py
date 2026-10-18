"""Full A-level international results since 1872 (martj42/international_results)."""
from __future__ import annotations

import io
from datetime import datetime

import pandas as pd

from .. import config, http

URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
CACHE = config.RAW / "international" / "results.csv"


def load(*, max_age_h: float = 12) -> pd.DataFrame:
    if not CACHE.exists() or (datetime.now().timestamp() - CACHE.stat().st_mtime) / 3600 > max_age_h:
        try:
            text = http.get(URL).text
            CACHE.parent.mkdir(parents=True, exist_ok=True)
            CACHE.write_text(text, encoding="utf-8")
        except Exception:
            if not CACHE.exists():
                raise
    df = pd.read_csv(io.StringIO(CACHE.read_text(encoding="utf-8")))
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["neutral"] = df["neutral"].astype(str).str.upper().eq("TRUE")
    df["home_score"] = pd.to_numeric(df["home_score"], errors="coerce")
    df["away_score"] = pd.to_numeric(df["away_score"], errors="coerce")
    return df.dropna(subset=["date"]).reset_index(drop=True)
