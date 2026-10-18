"""Team-name normalisation and fuzzy matching between data sources."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher
from functools import lru_cache

# Abbreviations used by football-data.co.uk (expanded before comparison).
_EXPAND = {
    "man": "manchester", "utd": "united", "nott'm": "nottingham", "nottm": "nottingham", "ein": "eintracht",
    "m'gladbach": "monchengladbach", "mgladbach": "monchengladbach", "wolves": "wolverhampton", "spurs": "tottenham",
    "sheffield weds": "sheffield wednesday", "qpr": "queens park rangers", "west brom": "west bromwich albion",
    "paris sg": "paris saint germain", "psg": "paris saint germain", "st": "saint", "ath": "athletic",
    "sp": "sporting", "fc koln": "koln", "inter": "internazionale", "espanol": "espanyol", "la coruna": "deportivo la coruna",
    "vallecano": "rayo vallecano", "sociedad": "real sociedad", "betis": "real betis", "celta": "celta vigo",
    "hertha": "hertha berlin", "leverkusen": "bayer leverkusen", "dortmund": "borussia dortmund",
    "bielefeld": "arminia bielefeld", "fortuna dusseldorf": "dusseldorf", "greuther furth": "furth",
    "milan": "ac milan", "roma": "as roma", "verona": "hellas verona", "spal": "spal 2013",
    "ajaccio gfco": "gfc ajaccio", "nimes": "nimes olympique", "evian thonon gaillard": "evian",
}
# Exact cross-source aliases (normalised form -> normalised form).
ALIASES = {
    "ath madrid": "atletico madrid", "athletic madrid": "atletico madrid", "athletic bilbao": "athletic club",
    "ath bilbao": "athletic club", "sporting gijon": "sporting gijon", "fc koln": "koln", "1 fc koln": "koln",
    "fc cologne": "koln", "bayern munich": "bayern munich", "fc bayern munchen": "bayern munich",
    "internazionale": "internazionale", "inter milan": "internazionale",
    # national teams (ESPN -> martj42)
    "czechia": "czech republic", "turkiye": "turkey", "korea republic": "south korea", "republic of korea": "south korea",
    "korea dpr": "north korea", "ir iran": "iran", "cote d ivoire": "ivory coast", "cabo verde": "cape verde",
    "cape verde islands": "cape verde", "china": "china pr", "bosnia herzegovina": "bosnia and herzegovina",
    "bosnia-herzegovina": "bosnia and herzegovina", "congo dr": "dr congo", "democratic republic of the congo": "dr congo",
    "kyrgyz republic": "kyrgyzstan", "chinese taipei": "taiwan", "curacao": "curacao", "the gambia": "gambia",
    "timor leste": "east timor", "brunei darussalam": "brunei", "macao": "macau", "uae": "united arab emirates",
    "usa": "united states", "us virgin islands": "united states virgin islands", "ireland": "republic of ireland",
    "trinidad tobago": "trinidad and tobago", "antigua barbuda": "antigua and barbuda",
    "saint kitts nevis": "saint kitts and nevis", "saint vincent grenadines": "saint vincent and the grenadines",
    "sao tome principe": "sao tome and principe", "swaziland": "eswatini", "north macedonia": "north macedonia",
    "fyr macedonia": "north macedonia", "macedonia": "north macedonia",
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm(name: str) -> str:
    s = strip_accents(str(name)).lower().replace("&", " and ")
    s = re.sub(r"[.\-/]", " ", s)
    s = re.sub(r"\bst\b\.?", "saint", s)
    s = re.sub(r"[^a-z0-9' ]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return ALIASES.get(s, s)


def expand(name: str) -> str:
    s = norm(name)
    if s in _EXPAND:
        return _EXPAND[s]
    toks = [_EXPAND.get(t, t) for t in s.split()]
    return " ".join(toks)


_STOP = {"fc", "cf", "ac", "as", "sc", "club", "de", "afc", "ssc", "us", "ss", "calcio", "1", "sv", "vfl", "vfb",
         "tsg", "rc", "ogc", "sco", "ud", "cd", "rcd", "sd", "real", "fk", "and", "the", "1899", "1846", "1907", "05", "04", "96"}


@lru_cache(maxsize=200_000)
def similarity(a: str, b: str) -> float:
    """0..1 similarity robust to abbreviations and club prefixes."""
    ea, eb = expand(a), expand(b)
    if ea == eb:
        return 1.0
    ta = {t for t in ea.split() if t not in _STOP} or set(ea.split())
    tb = {t for t in eb.split() if t not in _STOP} or set(eb.split())
    jac = len(ta & tb) / max(1, len(ta | tb))
    sub = 1.0 if (ea in eb or eb in ea) else 0.0
    seq = SequenceMatcher(None, ea, eb).ratio()
    pref = 1.0 if any(x[:4] == y[:4] for x in ta for y in tb if len(x) >= 4 and len(y) >= 4) else 0.0
    return max(seq, 0.55 * jac + 0.25 * sub + 0.2 * pref + 0.25 * seq)
