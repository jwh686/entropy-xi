"""Sanity checks for handicap / goal-line settlement and probability maths.
Run: python -m tests.test_markets"""
import math

import numpy as np

from entropy_xi.models import markets as mk


def test_settlement():
    # Home -0.75: win by 2+ = win, win by 1 = half-win, draw/loss = loss
    assert mk.settle_result(2, -0.75) == 1.0
    assert mk.settle_result(1, -0.75) == 0.5
    assert mk.settle_result(0, -0.75) == -1.0
    # Home -0.25: draw = half-loss
    assert mk.settle_result(0, -0.25) == -0.5
    assert mk.settle_result(1, -0.25) == 1.0
    # Away +0.25 (home -0.25): draw = half-win for away
    assert mk.settle_result(0, 0.25) == 0.5
    # Level ball: draw = push
    assert mk.settle_result(0, 0.0) == 0.0
    # -1.0: win by exactly 1 = push
    assert mk.settle_result(1, -1.0) == 0.0
    assert mk.split_line(-0.75) == (-1.0, -0.5)
    assert mk.split_line(2.25) == (2.0, 2.5)


def test_probabilities():
    m = mk.score_matrix(1.6, 1.0, -0.06)
    assert abs(m.sum() - 1) < 1e-9
    h, d, a = mk.outcome_probs(m)
    assert abs(h + d + a - 1) < 1e-9 and h > a
    dd = mk.diff_dist(m)
    ph = mk.handicap_probs(dd, -0.5, "home")
    assert abs(ph["win"] - h) < 1e-9
    pa = mk.handicap_probs(dd, -0.5, "away")
    assert abs(pa["win"] - (d + a)) < 1e-9
    td = mk.total_dist(m)
    po = mk.total_probs(td, 2.5, "over")
    assert abs(po["win"] - td[3:].sum()) < 1e-9
    # quarter goal line 2.25: exactly 2 goals -> half-loss for over
    po = mk.total_probs(td, 2.25, "over")
    assert abs(po["half_loss"] - td[2]) < 1e-9
    # EV at fair odds is zero
    pr = mk.handicap_probs(dd, -0.75, "home")
    fo = mk.fair_odds(pr)
    assert abs(mk.expected_return(pr, fo)) < 1e-9
    assert abs(mk.effective_win_prob(pr) - 1 / fo) < 1e-9
    line = mk.main_handicap_line(dd)
    assert -1.0 <= line <= 0.0


def test_implied():
    m = mk.score_matrix(1.8, 0.9, -0.06)
    p = mk.outcome_probs(m)
    po = mk.total_dist(m)[3:].sum()
    lh, la = mk.implied_goals(p1x2=p, p_over25=po)
    assert abs(lh - 1.8) < 0.02 and abs(la - 0.9) < 0.02, (lh, la)
    pw = mk.devig_power([1.5, 4.2, 6.5])
    assert abs(pw.sum() - 1) < 1e-9
    assert abs(mk.entropy_1x2([1 / 3] * 3) - 1) < 1e-9


if __name__ == "__main__":
    test_settlement()
    test_probabilities()
    test_implied()
    print("markets: all tests passed")
