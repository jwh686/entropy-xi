"""Market-anchored correction (MAC).

Bookmaker consensus already contains most of the information in our features (out-of-sample
the pure model is clearly worse than the market). MAC therefore starts from the market's
implied expected goals and lets a heavily regularised LightGBM-Poisson learn only small,
systematic corrections from the model and feature set (log(market lambda) is the offset).
Walk-forward tests show a small but consistent likelihood gain over the raw market.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from lightgbm import LGBMRegressor

FEATS = ["mk_tot", "mk_sup", "d_lh", "d_la", "m_ph", "m_pd", "m_pa", "elo_dr", "pi_gd", "opr_gd", "opr_tot",
         "h5_xpd", "a5_xpd", "h10_xpd", "a10_xpd", "rest_h", "rest_a", "cong_h", "cong_a", "h5_sotf", "h5_sota",
         "a5_sotf", "a5_sota", "comp_mu", "comp_hadv", "h2h_gd", "h10_o25", "a10_o25", "hv_gd", "av_gd", "disagree"]
KW = dict(objective="poisson", n_estimators=150, learning_rate=0.02, num_leaves=8, min_child_samples=400,
          subsample=0.8, subsample_freq=1, colsample_bytree=0.7, reg_lambda=10, verbose=-1, random_state=11)


def frame(feat: pd.DataFrame, pred: pd.DataFrame, mg: pd.DataFrame) -> pd.DataFrame:
    """Join features, model predictions and market-implied goals (index = match index)."""
    idx = feat.index.intersection(pred.index).intersection(mg.index)
    D = pd.concat([feat.loc[idx], pred.loc[idx, ["m_lh", "m_la", "m_ph", "m_pd", "m_pa", "disagree"]], mg.loc[idx, ["mk_lh", "mk_la"]]], axis=1)
    D["mk_tot"] = D["mk_lh"] + D["mk_la"]
    D["mk_sup"] = np.log(D["mk_lh"] / D["mk_la"])
    D["d_lh"] = np.log(D["m_lh"] / D["mk_lh"])
    D["d_la"] = np.log(D["m_la"] / D["mk_la"])
    return D


class MarketCorrection:
    def fit(self, D: pd.DataFrame, hg, ag):
        self.h = LGBMRegressor(**KW).fit(D[FEATS], hg, init_score=np.log(D["mk_lh"]))
        self.a = LGBMRegressor(**KW).fit(D[FEATS], ag, init_score=np.log(D["mk_la"]))
        return self

    def predict(self, D: pd.DataFrame) -> pd.DataFrame:
        lh = np.exp(self.h.predict(D[FEATS], raw_score=True) + np.log(D["mk_lh"].values))
        la = np.exp(self.a.predict(D[FEATS], raw_score=True) + np.log(D["mk_la"].values))
        # corrections are meant to be small; cap them at +-15% to stay anchored
        lh = np.clip(lh, D["mk_lh"].values * 0.85, D["mk_lh"].values * 1.15)
        la = np.clip(la, D["mk_la"].values * 0.85, D["mk_la"].values * 1.15)
        return pd.DataFrame({"mac_lh": lh, "mac_la": la}, index=D.index)
