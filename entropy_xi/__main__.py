"""Command line: python -m entropy_xi <command>

  build      download / refresh all sources and rebuild the unified match table
  train      features + walk-forward training + production models  (--fast for a quick run)
  backtest   evaluate walk-forward predictions, calibrate stars, write the backtest report
  daily      the daily job: refresh data, settle yesterday, predict the next window, export the site
  export     rebuild website JSON from existing predictions
"""
from __future__ import annotations

import argparse
import sys
import time


def _log(msg: str):
    print(time.strftime("[%H:%M:%S] ") + msg, flush=True)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="entropy_xi")
    ap.add_argument("command", choices=["build", "train", "backtest", "daily", "export"])
    ap.add_argument("--fast", action="store_true", help="smaller models (quick check)")
    ap.add_argument("--retrain", action="store_true", help="daily: force retraining production models")
    ap.add_argument("--no-network", action="store_true", help="daily: use cached data only")
    a = ap.parse_args(argv)
    if a.command == "build":
        from .data import build
        build.build(log=_log)
    elif a.command == "train":
        from .pipeline import train
        train.run_all(fast=a.fast, log=_log)
    elif a.command == "backtest":
        from .pipeline import backtest
        backtest.run(log=_log)
    elif a.command == "daily":
        from .pipeline import daily
        daily.run(retrain=a.retrain, network=not a.no_network, log=_log)
    elif a.command == "export":
        from .pipeline import export
        export.run(log=_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
