# 熵锋奕 · Entropy XI

Football big-data prediction and early-warning engine with a static, blue "tech" website.

* **Asian handicap direction** and **goal line (over/under)** for every covered match, priced against
  Bet365 lines (football-data.co.uk) or DraftKings lines (ESPN). Where no Asian line is published, an
  estimated Asian main line is derived from market prices.
* **Full-time result (1X2)**, but never an outcome priced below **1.40**.
* **Star ratings (★–★★★★★)**: only ★★★+ are "recommended"; most matches get no recommendation.
* **Early warnings**: upset risk, high entropy, fatigue, algorithm disagreement, thin data, 2nd-leg context, line movement.
* **Team database**: H2H, form, home/away splits and Elo trend for every team in the covered competitions.
* **Daily update** with a **frozen ledger**: predictions are published before kick-off and never edited; results are settled on the 90-minute score.

Covered: Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Chinese Super League, UEFA Champions League,
Europa League, Conference League, AFC Champions League Elite, Club World Cup, World Cup + qualifiers, Euro + qualifiers,
Nations League, Copa América, Asian Cup, AFCON, Gold Cup and A-level friendlies. Another ~25 leagues are downloaded only to
feed the ratings (European / Asian cup opponents). China Sports Lottery prices are not model inputs.

## How it works

| Stage | What happens | Code |
|---|---|---|
| Data | ESPN scoreboards (global team ids, results, stats, live DraftKings lines), football-data.co.uk (Bet365 / market / exchange 1X2, O/U 2.5 and Asian handicap, opening and closing), martj42 internationals since 1872 | `entropy_xi/data/` |
| Ratings | Elo, Pi-ratings, online Poisson attack/defence (OPR), one chronological pass (no look-ahead) | `features/engine.py` |
| Features | ProphitBet-style form windows, extended across seasons and adjusted for opponent strength; shots on target, rest, congestion, H2H, aggregate score | `features/engine.py` |
| Models | Poisson GLM + LightGBM-Poisson (+ OPR) for expected goals; logistic regression, random forest, XGBoost, MLP + Dixon–Coles for 1X2; ensemble weights from out-of-sample predictions only; reconciliation of 1X2 with the score matrix | `models/predictor.py` |
| Market | Market-implied expected goals (de-vigged consensus), blended with the model at the out-of-sample optimal weight; handicap/goal-line settlement maths incl. quarter lines | `models/markets.py`, `models/picks.py` |
| Validation | Walk-forward by season (club folds from Aug 2013, international folds from Jan 2012); 2013–2021 for choosing settings, 2022+ untouched hold-out | `pipeline/train.py`, `pipeline/backtest.py` |
| Publishing | Every 3 h: refresh → rebuild → predict next 36 h → freeze in ledger → settle → export JSON | `pipeline/daily.py`, `pipeline/export.py` |

## What the backtest says (walk-forward, hold-out = seasons 2022/23 onward)

| | Asian handicap | Goal line 2.5 | 1X2 (≥1.40) |
|---|---|---|---|
| Pure multi-algorithm model, all picks | hit 49.6%, ROI −3.7% | 46.8%, −5.8% | 31.4%, −9.8% |
| Market consensus, all picks | 49.1%, −3.7% | 50.2%, −4.2% | 35.3%, −6.3% |
| Published basis (MAC), all picks | 50.2%, −2.4% | 51.9%, −4.4% | 34.2%, −5.9% |
| Published ★★★+ only | **67 picks, 53.7%, +2.9%** | none (tier disabled) | **169 picks, 26.6%, +6.2%** |

* 1X2 most-likely-outcome accuracy: 51.3% (clubs, 115k matches), 60.3% (national teams). O/U 2.5 direction: 57.1% / 59.6%.
* On 1X2 log loss the pure model (1.003) is clearly worse than the market (0.987); the optimal blend puts 100% weight on the market,
  which is why published probabilities are market-anchored. The ★★★+ samples are small — treat them as unproven.

## Run it

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python -X utf8 -m entropy_xi build      # download + unify data (~15 min first time)
.\.venv\Scripts\python -X utf8 -m entropy_xi train      # walk-forward + production models (~6 min)
.\.venv\Scripts\python -X utf8 -m entropy_xi backtest   # honest evaluation + season replay
.\.venv\Scripts\python -X utf8 -m entropy_xi daily      # publish today's predictions, settle, export site data
.\.venv\Scripts\python scripts\serve.py                 # http://localhost:8765
```

Use `-X utf8` on Windows (GBK console).

## Daily automation

* **Windows**: `scripts\register_task.ps1 -Time "11:00"` registers a daily scheduled task running `scripts\run_daily.ps1`
  (which also rebuilds/retrains on Mondays). Logs go to `logs\`.
* **Cloud (recommended for a public site)**: push the repository to GitHub, enable *Pages → Source: GitHub Actions*.
  `.github/workflows/daily.yml` runs every 3 hours, commits the frozen ledger (`data/ledger/`) and
  `site/data/`, and deploys `site/` to GitHub Pages. The git history doubles as a public audit trail.

## Data & integrity notes

* Bet365 Asian-handicap odds exist in football-data from 2019/20; earlier seasons are evaluated at the market-average
  Asian price on the same line. ESPN removes odds after a match, so UCL/UEL/ACL/international backtests report
  probability accuracy only; their priced record starts with the live ledger.
* The "season replay" on the site uses models trained before the season — it is a simulation and is labelled as such.
  The live record starts on `LIVE_START` in `entropy_xi/config.py`.
* Betting markets are efficient. The backtest report (`data/processed/backtest_report.json`, also on the site) is the
  reference for what the model can and cannot do — it does not promise profit.

## Layout

```
entropy_xi/           Python package (data, features, models, pipeline)
site/                 static website (index.html, assets/, data/*.json written by the pipeline)
data/ledger/          frozen live ledger + season replay (commit these)
scripts/              serve, Windows task, bulk download
.github/workflows/    daily cloud job + GitHub Pages deploy
```
