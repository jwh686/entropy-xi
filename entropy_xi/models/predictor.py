"""Multi-algorithm prediction core.

Goal models (expected goals -> full score distribution):
  * OPR        online Poisson attack/defence ratings (from the feature engine)
  * GLM        Poisson generalised linear model
  * LGBM       gradient-boosted trees with Poisson loss
1X2 classifiers (ProphitBet family, probability outputs):
  * LR         multinomial logistic regression
  * RF         random forest
  * XGB        extreme gradient boosting
  * MLP        neural network
  * DC         Dixon–Coles score matrix from the blended expected goals

Blending weights are learned only from out-of-sample (walk-forward) predictions.
The 1X2 ensemble is then reconciled with the score matrix by re-splitting the
expected goals (total kept fixed), so handicap, goal-line and 1X2 views agree.
"""
from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor
from scipy.optimize import brentq, minimize
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression, PoissonRegressor
from sklearn.neural_network import MLPClassifier
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from xgboost import XGBClassifier

from . import markets as mk

warnings.filterwarnings("ignore", category=UserWarning)

GOAL_KEYS = ["opr", "glm", "lgb"]
CLS_KEYS = ["lr", "rf", "xgb", "mlp", "dc"]

EXCLUDE = {"elo_h", "elo_a"}  # absolute levels drift; differences carry the signal


def feature_columns(feat: pd.DataFrame) -> list[str]:
    return [c for c in feat.columns if c not in EXCLUDE]


def result_label(hg, ag) -> np.ndarray:
    return np.where(hg > ag, 0, np.where(hg == ag, 1, 2))


class BaseModels:
    """All base learners trained on one training window."""

    def __init__(self, features: list[str], fast: bool = False, seed: int = 7):
        self.features = features
        self.fast = fast
        self.seed = seed

    def fit(self, X: pd.DataFrame, hg: np.ndarray, ag: np.ndarray, w: np.ndarray | None = None):
        X = X[self.features].astype(float)
        y = result_label(hg, ag)
        n_trees = 120 if self.fast else 260
        self.glm_h = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=300))
        self.glm_a = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), PoissonRegressor(alpha=1e-3, max_iter=300))
        self.glm_h.fit(X, hg, poissonregressor__sample_weight=w)
        self.glm_a.fit(X, ag, poissonregressor__sample_weight=w)
        lgb_kw = dict(objective="poisson", n_estimators=n_trees * 2, learning_rate=0.03, num_leaves=24,
                      min_child_samples=120, subsample=0.8, subsample_freq=1, colsample_bytree=0.7,
                      reg_lambda=2.0, random_state=self.seed, verbose=-1)
        self.lgb_h = LGBMRegressor(**lgb_kw).fit(X, hg, sample_weight=w)
        self.lgb_a = LGBMRegressor(**lgb_kw).fit(X, ag, sample_weight=w)

        self.lr = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), LogisticRegression(C=0.3, max_iter=600))
        self.lr.fit(X, y, logisticregression__sample_weight=w)
        self.rf = make_pipeline(SimpleImputer(strategy="median"),
                                RandomForestClassifier(n_estimators=n_trees, min_samples_leaf=60, max_features=0.3,
                                                       max_samples=0.6, n_jobs=-1, random_state=self.seed))
        self.rf.fit(X, y, randomforestclassifier__sample_weight=w)
        self.xgb = XGBClassifier(n_estimators=n_trees * 2, max_depth=4, learning_rate=0.03, subsample=0.8,
                                 colsample_bytree=0.7, min_child_weight=20, reg_lambda=2.0, objective="multi:softprob",
                                 num_class=3, tree_method="hist", random_state=self.seed, n_jobs=-1, verbosity=0)
        self.xgb.fit(X, y, sample_weight=w)
        self.mlp = make_pipeline(SimpleImputer(strategy="median"), StandardScaler(),
                                 MLPClassifier(hidden_layer_sizes=(48, 24), alpha=3e-3, learning_rate_init=1e-3,
                                               early_stopping=True, validation_fraction=0.1, n_iter_no_change=8,
                                               max_iter=120, random_state=self.seed))
        idx = np.random.default_rng(self.seed).choice(len(X), size=min(len(X), 120_000), replace=False)
        self.mlp.fit(X.iloc[idx], y[idx])
        return self

    def predict(self, X: pd.DataFrame) -> pd.DataFrame:
        F = X[self.features].astype(float)
        out = pd.DataFrame(index=X.index)
        out["opr_lh"], out["opr_la"] = X["opr_lh"].values, X["opr_la"].values
        out["glm_lh"], out["glm_la"] = self.glm_h.predict(F), self.glm_a.predict(F)
        out["lgb_lh"], out["lgb_la"] = self.lgb_h.predict(F), self.lgb_a.predict(F)
        for name, mdl in (("lr", self.lr), ("rf", self.rf), ("xgb", self.xgb), ("mlp", self.mlp)):
            p = mdl.predict_proba(F)
            p = np.clip(p, 1e-4, 1)
            p /= p.sum(1, keepdims=True)
            out[f"{name}_h"], out[f"{name}_d"], out[f"{name}_a"] = p[:, 0], p[:, 1], p[:, 2]
        for k in ("lh", "la"):
            for g in GOAL_KEYS:
                out[f"{g}_{k}"] = np.clip(out[f"{g}_{k}"], 0.08, 6.0)
        return out


def _softmax(z):
    z = np.asarray(z, float)
    e = np.exp(z - z.max())
    return e / e.sum()


class Blender:
    """Learns ensemble weights / Dixon–Coles rho from out-of-sample component predictions."""

    def __init__(self):
        self.goal_w = np.ones(len(GOAL_KEYS)) / len(GOAL_KEYS)
        self.cls_w = np.ones(len(CLS_KEYS)) / len(CLS_KEYS)
        self.rho = -0.06

    # ---- expected goals
    def blend_goals(self, comp: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        lh = np.exp(sum(w * np.log(comp[f"{g}_lh"].values) for w, g in zip(self.goal_w, GOAL_KEYS)))
        la = np.exp(sum(w * np.log(comp[f"{g}_la"].values) for w, g in zip(self.goal_w, GOAL_KEYS)))
        return lh, la

    def fit(self, comp: pd.DataFrame, hg: np.ndarray, ag: np.ndarray):
        hg = np.asarray(hg, float)
        ag = np.asarray(ag, float)
        LH = np.log(np.stack([comp[f"{g}_lh"].values for g in GOAL_KEYS], 1))
        LA = np.log(np.stack([comp[f"{g}_la"].values for g in GOAL_KEYS], 1))

        def nll_goals(z):
            w = _softmax(z)
            lh, la = np.exp(LH @ w), np.exp(LA @ w)
            return float(np.mean(lh - hg * np.log(lh) + la - ag * np.log(la)))

        self.goal_w = _softmax(minimize(nll_goals, np.zeros(len(GOAL_KEYS)), method="Nelder-Mead",
                                        options={"maxiter": 400, "xatol": 1e-4, "fatol": 1e-7}).x)
        lh, la = self.blend_goals(comp)

        # Dixon–Coles rho by exact-score likelihood on a subsample
        idx = np.random.default_rng(0).choice(len(lh), size=min(len(lh), 6000), replace=False)
        best = (1e9, -0.06)
        for rho in np.arange(-0.16, 0.05, 0.02):
            ll = 0.0
            for i in idx:
                m = mk.score_matrix(lh[i], la[i], rho)
                ll -= math.log(max(m[min(int(hg[i]), 10), min(int(ag[i]), 10)], 1e-12))
            best = min(best, (ll, rho))
        self.rho = float(best[1])

        dc = self.dc_probs(lh, la)
        P = np.stack([np.stack([comp[f"{k}_h"].values, comp[f"{k}_d"].values, comp[f"{k}_a"].values], 1)
                      if k != "dc" else dc for k in CLS_KEYS], 0)  # (K, n, 3)
        y = result_label(hg, ag)
        onehot = np.eye(3)[y]

        def nll_cls(z):
            w = _softmax(z)
            p = np.tensordot(w, P, axes=1)
            return float(-np.mean(np.log(np.clip((p * onehot).sum(1), 1e-12, 1))))

        self.cls_w = _softmax(minimize(nll_cls, np.zeros(len(CLS_KEYS)), method="Nelder-Mead",
                                       options={"maxiter": 600, "xatol": 1e-4, "fatol": 1e-7}).x)
        return self

    def dc_probs(self, lh, la) -> np.ndarray:
        out = np.empty((len(lh), 3))
        for i in range(len(lh)):
            out[i] = mk.outcome_probs(mk.score_matrix(lh[i], la[i], self.rho))
        return out

    def combine(self, comp: pd.DataFrame) -> pd.DataFrame:
        """Final model view per match: reconciled expected goals + ensemble 1X2 + disagreement."""
        lh, la = self.blend_goals(comp)
        dc = self.dc_probs(lh, la)
        stack = []
        for k in CLS_KEYS:
            stack.append(dc if k == "dc" else np.stack([comp[f"{k}_h"], comp[f"{k}_d"], comp[f"{k}_a"]], 1))
        P = np.stack(stack, 0)
        p = np.tensordot(self.cls_w, P, axes=1)
        spread = P[:, :, [0, 2]].std(0).max(1)  # algorithm disagreement on home/away win
        lh2, la2 = reconcile(lh, la, p, self.rho)
        out = pd.DataFrame({"m_lh": lh2, "m_la": la2, "m_ph": p[:, 0], "m_pd": p[:, 1], "m_pa": p[:, 2],
                            "disagree": spread, "raw_lh": lh, "raw_la": la}, index=comp.index)
        return out

    def to_dict(self):
        return {"goal_w": dict(zip(GOAL_KEYS, map(float, self.goal_w))),
                "cls_w": dict(zip(CLS_KEYS, map(float, self.cls_w))), "rho": self.rho}


def reconcile(lh, la, p1x2, rho) -> tuple[np.ndarray, np.ndarray]:
    """Re-split each match's total expected goals so the score matrix's (P(H) - P(A))
    matches the ensemble's. Keeps the goal-line view (total) and aligns the handicap view."""
    lh, la = np.asarray(lh, float).copy(), np.asarray(la, float).copy()
    for i in range(len(lh)):
        tot = lh[i] + la[i]
        target = p1x2[i, 0] - p1x2[i, 2]

        def f(s):
            m = mk.score_matrix(tot * s, tot * (1 - s), rho)
            h, _, a = mk.outcome_probs(m)
            return (h - a) - target

        try:
            s = brentq(f, 0.03, 0.97, xtol=1e-4)
            lh[i], la[i] = tot * s, tot * (1 - s)
        except ValueError:
            pass
    return lh, la
