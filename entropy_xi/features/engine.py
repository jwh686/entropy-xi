"""Single chronological pass producing leakage-free pre-match features.

For every match (played or scheduled) the features describe what was knowable
before kick-off; ratings are updated only after a played match is processed.

Rating systems (all online, all walk-forward):
  * Elo — goal-margin weighted, competition-weighted K (World Football Elo style).
  * Pi-ratings — separate home/away strength in goal-difference space (Constantinou & Fenton 2013).
  * OPR — online Poisson attack/defence ratings with per-competition goal baseline and home edge;
          an exponentially-forgetting Dixon–Coles/Maher model that yields expected goals directly.
Form features follow ProphitBet (rolling wins/losses/goals/goal-difference windows) but are
computed across seasons and competitions and adjusted for opponent strength.
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .. import config

LEAGUE_PRIOR_ELO = {
    "eng.1": 1660, "esp.1": 1650, "ger.1": 1630, "ita.1": 1630, "fra.1": 1590,
    "por.1": 1520, "ned.1": 1510, "eng.2": 1500, "bel.1": 1480, "tur.1": 1480, "rus.1": 1470,
    "esp.2": 1440, "ita.2": 1430, "ger.2": 1450, "fra.2": 1420,
    "sco.1": 1430, "gre.1": 1440, "aut.1": 1450, "sui.1": 1450, "den.1": 1440, "cze.1": 1440,
    "nor.1": 1410, "swe.1": 1400, "isr.1": 1390, "cyp.1": 1380,
    "jpn.1": 1440, "ksa.1": 1420, "chn.1": 1400, "aus.1": 1360, "tha.1": 1300,
}
CUP_DEBUT_ELO = 1360


@dataclass
class TeamState:
    elo: float
    pi_h: float = 0.0
    pi_a: float = 0.0
    att: float = 0.0
    dfn: float = 0.0
    n: int = 0
    last: pd.Timestamp | None = None
    hist: deque = field(default_factory=lambda: deque(maxlen=20))      # all venues
    hist_home: deque = field(default_factory=lambda: deque(maxlen=8))
    hist_away: deque = field(default_factory=lambda: deque(maxlen=8))
    dates: deque = field(default_factory=lambda: deque(maxlen=8))


def _pi_g(r: float) -> float:
    return math.copysign(10 ** (abs(r) / 3.0) - 1.0, r)


def _margin_mult(gd: int) -> float:
    a = abs(gd)
    if a <= 1:
        return 1.0
    if a == 2:
        return 1.5
    return (11 + a) / 8.0


class FeatureEngine:
    def __init__(self, pool: str, *, elo_k: float = 20.0, elo_hfa: float | None = None,
                 pi_lr: float = 0.035, pi_gamma: float = 0.7, opr_lr: float = 0.045,
                 opr_mu_lr: float = 0.004, opr_h_lr: float = 0.002):
        self.pool = pool
        self.elo_k = elo_k if pool == "club" else 1.0  # intl uses tournament K directly
        self.hfa = elo_hfa if elo_hfa is not None else (65.0 if pool == "club" else 100.0)
        self.pi_lr, self.pi_gamma = pi_lr, pi_gamma
        self.opr_lr, self.opr_mu_lr, self.opr_h_lr = opr_lr, opr_mu_lr, opr_h_lr
        self.teams: dict[str, TeamState] = {}
        self.mu: dict[str, float] = defaultdict(lambda: math.log(1.35))
        self.hadv: dict[str, float] = defaultdict(lambda: 0.18 if pool == "club" else 0.25)
        self.h2h: dict[tuple, deque] = defaultdict(lambda: deque(maxlen=8))
        self.first_leg: dict[tuple, tuple] = {}
        self.league_members: dict[str, set] = defaultdict(set)
        self.elo_track: dict[str, list] = defaultdict(list)

    # ------------------------------------------------------------------
    def _comp_key(self, row) -> str:
        if self.pool == "intl":
            t = row.tournament if isinstance(row.tournament, str) else "Friendly"
            return "friendly" if t == "Friendly" else ("major" if config.INTL_K.get(t, 30) >= 50 else "competitive")
        return row.comp

    def _new_team(self, key: str, comp: str, group: str) -> TeamState:
        if self.pool == "intl":
            return TeamState(elo=1500.0)
        if group == "league":
            members = [self.teams[k] for k in self.league_members[comp] if k in self.teams]
            if len(members) >= 10:
                elos = sorted(m.elo for m in members)
                q = elos[max(0, int(len(elos) * 0.15))]
                atts = sorted(m.att for m in members)
                dfns = sorted(m.dfn for m in members)
                pis_h = sorted(m.pi_h for m in members)
                pis_a = sorted(m.pi_a for m in members)
                i = max(0, int(len(members) * 0.2))
                return TeamState(elo=q, att=atts[i], dfn=dfns[i], pi_h=pis_h[i], pi_a=pis_a[i])
            elo = LEAGUE_PRIOR_ELO.get(comp, 1450)
            off = (elo - 1500) / 600.0
            return TeamState(elo=elo, att=off * 0.5, dfn=off * 0.5, pi_h=off, pi_a=off)
        return TeamState(elo=CUP_DEBUT_ELO, att=-0.15, dfn=-0.15, pi_h=-0.3, pi_a=-0.3)

    def _team(self, key, comp, group) -> TeamState:
        t = self.teams.get(key)
        if t is None:
            t = self._new_team(key, comp, group)
            self.teams[key] = t
        if group == "league":
            self.league_members[comp].add(key)
        return t

    # ------------------------------------------------------------------
    @staticmethod
    def _form(hist, n):
        h = list(hist)[-n:]
        if not h:
            return dict(ppg=np.nan, gf=np.nan, ga=np.nan, o25=np.nan, cs=np.nan, fts=np.nan, xpd=np.nan, opp=np.nan,
                        sotf=np.nan, sota=np.nan, w=np.nan, l=np.nan, bigw=np.nan)
        k = len(h)
        sot = [x for x in h if not np.isnan(x[6])]
        return dict(
            ppg=sum(x[3] for x in h) / k, gf=sum(x[1] for x in h) / k, ga=sum(x[2] for x in h) / k,
            o25=sum(1 for x in h if x[1] + x[2] > 2.5) / k, cs=sum(1 for x in h if x[2] == 0) / k,
            fts=sum(1 for x in h if x[1] == 0) / k, xpd=sum(x[3] - x[5] for x in h) / k,
            opp=sum(x[4] for x in h) / k,
            sotf=(sum(x[6] for x in sot) / len(sot)) if sot else np.nan,
            sota=(sum(x[7] for x in sot) / len(sot)) if sot else np.nan,
            w=sum(1 for x in h if x[1] > x[2]) / k, l=sum(1 for x in h if x[1] < x[2]) / k,
            bigw=sum(1 for x in h if x[1] - x[2] >= 2) / k,
        )

    def run(self, matches: pd.DataFrame) -> pd.DataFrame:
        """matches: one pool, sorted by date. Returns a feature frame aligned to matches.index."""
        out = []
        is_intl = self.pool == "intl"
        cols = matches.columns
        has = {c: c in cols for c in ("tournament", "h_sot", "a_sot", "leg", "phase", "neutral")}
        for row in matches.itertuples():
            comp = row.comp
            group = row.group
            ck = self._comp_key(row)
            H = self._team(row.home, comp, group)
            A = self._team(row.away, comp, group)
            neutral = bool(row.neutral) if has["neutral"] and not pd.isna(row.neutral) else False
            hf = 0.0 if neutral else 1.0
            date = row.date

            # --- ratings
            dr = H.elo - A.elo + self.hfa * hf
            we = 1.0 / (1.0 + 10 ** (-dr / 400.0))
            pi_gd = _pi_g(H.pi_h) - _pi_g(A.pi_a)
            mu, ha = self.mu[ck], self.hadv[ck]
            lh = math.exp(mu + ha * hf + H.att - A.dfn)
            la = math.exp(mu + A.att - H.dfn)

            fh5, fa5 = self._form(H.hist, 5), self._form(A.hist, 5)
            fh10, fa10 = self._form(H.hist, 10), self._form(A.hist, 10)
            fhv, fav = self._form(H.hist_home, 5), self._form(A.hist_away, 5)

            def rest(t):
                if t.last is None:
                    return np.nan
                return min((date - t.last).total_seconds() / 86400.0, 30.0 if is_intl else 21.0)

            def cong(t):
                return sum(1 for d in t.dates if (date - d).days <= 14)

            pair = (min(row.home, row.away), max(row.home, row.away))
            hh = [x for x in self.h2h[pair] if (date - x[0]).days <= 365 * 6][-6:]
            if hh:
                h2h_gd = sum((x[2] - x[3]) if x[1] == row.home else (x[3] - x[2]) for x in hh) / len(hh)
                h2h_goals = sum(x[2] + x[3] for x in hh) / len(hh)
            else:
                h2h_gd = h2h_goals = np.nan

            agg_gd = np.nan
            if not is_intl and group == "cup":
                fl = self.first_leg.get((row.away, row.home, comp))
                if fl is not None and 2 <= (date - fl[0]).days <= 21:
                    agg_gd = fl[2] - fl[1]  # home team's goals in leg 1 (they were away) minus opponent's

            if is_intl:
                t = row.tournament if isinstance(row.tournament, str) else "Friendly"
                imp = config.INTL_K.get(t, config.INTL_K_DEFAULT) / 40.0
            else:
                imp = config.COMPETITIONS.get(comp, {}).get("weight", 1.0)
            phase = str(row.phase or "").lower() if has["phase"] else ""
            knockout = float(any(s in phase for s in ("final", "knockout", "round-of", "playoff", "quarter", "semi")))

            out.append({
                "elo_h": H.elo, "elo_a": A.elo, "elo_dr": dr, "elo_we": we,
                "pi_h": H.pi_h, "pi_a": A.pi_a, "pi_gd": pi_gd,
                "opr_lh": lh, "opr_la": la, "opr_tot": lh + la, "opr_gd": lh - la,
                "comp_mu": 2 * math.exp(mu), "comp_hadv": ha,
                "neutral": float(neutral), "imp": imp, "knockout": knockout, "agg_gd": agg_gd,
                "is_cup": float(group == "cup"), "is_intl": float(is_intl),
                "n_h": min(H.n, 60), "n_a": min(A.n, 60),
                "rest_h": rest(H), "rest_a": rest(A), "cong_h": cong(H), "cong_a": cong(A),
                "h2h_n": len(hh), "h2h_gd": h2h_gd, "h2h_goals": h2h_goals,
                **{f"h5_{k}": v for k, v in fh5.items()}, **{f"a5_{k}": v for k, v in fa5.items()},
                **{f"h10_{k}": v for k, v in fh10.items() if k in ("ppg", "gf", "ga", "o25", "xpd", "opp", "cs", "fts")},
                **{f"a10_{k}": v for k, v in fa10.items() if k in ("ppg", "gf", "ga", "o25", "xpd", "opp", "cs", "fts")},
                "hv_ppg": fhv["ppg"], "hv_gd": fhv["gf"] - fhv["ga"] if fhv["gf"] == fhv["gf"] else np.nan,
                "av_ppg": fav["ppg"], "av_gd": fav["gf"] - fav["ga"] if fav["gf"] == fav["gf"] else np.nan,
            })

            # --- update after a played match
            if row.status != "played" or pd.isna(row.hg) or pd.isna(row.ag):
                continue
            hg, ag = int(row.hg), int(row.ag)
            gd = hg - ag
            w = 1.0 if gd > 0 else (0.5 if gd == 0 else 0.0)
            if is_intl:
                t = row.tournament if isinstance(row.tournament, str) else "Friendly"
                k = config.INTL_K.get(t, config.INTL_K_DEFAULT)
            else:
                k = self.elo_k * config.COMPETITIONS.get(comp, {}).get("weight", 1.0)
            delta = k * _margin_mult(gd) * (w - we)
            elo_h_pre, elo_a_pre = H.elo, A.elo
            H.elo += delta
            A.elo -= delta

            # Pi-ratings
            err = gd - pi_gd
            psi = math.copysign(3.0 * math.log10(1 + abs(err)), err)
            H.pi_h += self.pi_lr * psi
            H.pi_a += self.pi_lr * self.pi_gamma * psi
            A.pi_a -= self.pi_lr * psi
            A.pi_h -= self.pi_lr * self.pi_gamma * psi

            # OPR (gradient of Poisson log-likelihood in log-rate space)
            eh, ea = hg - lh, ag - la
            lr = self.opr_lr
            H.att += lr * eh
            A.dfn -= lr * eh
            A.att += lr * ea
            H.dfn -= lr * ea
            self.mu[ck] += self.opr_mu_lr * (eh + ea) / 2.0
            self.hadv[ck] += self.opr_h_lr * (eh - ea) / 2.0 * hf
            # gentle shrinkage keeps the scale identifiable
            for t in (H, A):
                t.att *= 0.9995
                t.dfn *= 0.9995

            # form records: (date, gf, ga, pts, opp_elo, exp_pts, sot_f, sot_a)
            hs = float(row.h_sot) if has["h_sot"] and not pd.isna(row.h_sot) else np.nan
            as_ = float(row.a_sot) if has["a_sot"] and not pd.isna(row.a_sot) else np.nan
            ph = 3 if gd > 0 else (1 if gd == 0 else 0)
            pa = 3 if gd < 0 else (1 if gd == 0 else 0)
            p_draw = 0.12 + 0.16 * (1 - abs(2 * we - 1))
            xph = 3 * max(we - p_draw / 2, 0.0) + p_draw
            xpa = 3 * max(1 - we - p_draw / 2, 0.0) + p_draw
            rec_h = (date, hg, ag, ph, elo_a_pre, xph, hs, as_)
            rec_a = (date, ag, hg, pa, elo_h_pre, xpa, as_, hs)
            H.hist.append(rec_h)
            A.hist.append(rec_a)
            if hf:
                H.hist_home.append(rec_h)
                A.hist_away.append(rec_a)
            self.elo_track[row.home].append((date, round(H.elo, 1)))
            self.elo_track[row.away].append((date, round(A.elo, 1)))
            H.n += 1
            A.n += 1
            H.last = A.last = date
            H.dates.append(date)
            A.dates.append(date)
            self.h2h[pair].append((date, row.home, hg, ag))
            if not is_intl and group == "cup":
                self.first_leg[(row.home, row.away, comp)] = (date, hg, ag)
        return pd.DataFrame(out, index=matches.index)

    # ------------------------------------------------------------------
    def snapshot(self) -> dict:
        """Current ratings for the website team pages."""
        return {k: {"elo": round(t.elo, 1), "pi_h": round(t.pi_h, 3), "pi_a": round(t.pi_a, 3),
                    "att": round(t.att, 3), "dfn": round(t.dfn, 3), "n": t.n,
                    "last": t.last.isoformat() if t.last is not None else None}
                for k, t in self.teams.items()}
