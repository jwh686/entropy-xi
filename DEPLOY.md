# Deploying 熵锋奕 · Entropy XI to GitHub Pages

The workflow `.github/workflows/daily.yml` runs every day at **04:00 UTC = 12:00 Beijing**. It refreshes the data,
settles finished matches, publishes the next 36 h of predictions (frozen in `data/ledger/`), commits the ledger and
`site/data/`, and deploys `site/` to GitHub Pages. On Mondays, and whenever its cache is empty, it also rebuilds the data,
retrains the walk-forward models and re-runs the backtest.

## One-time setup

1. **Git for Windows**: `winget install --id Git.Git -e`, then open a new terminal.
2. **GitHub account**: sign up at https://github.com if you don't have one.
3. **Create an empty public repository**, e.g. `entropy-xi`: https://github.com/new
   * Public: free GitHub Pages needs a public repo. The code and the prediction ledger become visible, and the git history
     doubles as the audit trail proving that picks were not edited after kick-off.
   * Do **not** add a README, .gitignore or licence. The repo must be empty.
4. **Push** (from the project folder):
   ```
   git remote add origin https://github.com/<your-username>/entropy-xi.git
   git push -u origin main
   ```
   A browser window from Git Credential Manager asks you to sign in to GitHub the first time.
5. **Turn on Pages**: repo → *Settings* → *Pages* → *Build and deployment* → Source: **GitHub Actions**.
6. **First run**: repo → *Actions* → *entropy-xi-daily* → *Run workflow*. The first run starts from an empty cache, so it
   downloads ~140k matches, trains and backtests (about 30–45 minutes). Later daily runs take about 5–10 minutes.
7. The site is published at `https://<your-username>.github.io/entropy-xi/`.

## Notes

* Run the daily job in **one place only** (cloud *or* this PC). Two schedules would produce two diverging ledgers.
* Scheduled runs can start 10–60 minutes late when GitHub is busy. GitHub pauses schedules after 60 days without repository
  activity, but the daily commits count as activity.
* To change the time, edit the `cron` line (it is in UTC). To force a retrain, run the workflow manually on a Monday or
  delete the cache under *Actions → Caches*.
* GitHub Pages can be slow or unreachable from mainland China. A custom domain (*Settings → Pages → Custom domain*) or a
  mirror on a China-reachable static host can be added later without changing the pipeline.
