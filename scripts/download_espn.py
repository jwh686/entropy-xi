"""Bulk-download ESPN history into data/raw/espn (safe to re-run; past years are cached)."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from entropy_xi import config  # noqa: E402
from entropy_xi.data import espn  # noqa: E402

if __name__ == "__main__":
    t0 = time.time()
    only = sys.argv[1:] or None
    total = 0
    for slug, meta in config.COMPETITIONS.items():
        if only and slug not in only:
            continue
        n = 0
        for year in range(meta["start"], time.localtime().tm_year + 1):
            try:
                n += len(espn.fetch_year(slug, year))
            except Exception as exc:
                print(f"  ! {slug} {year}: {exc}", flush=True)
        total += n
        print(f"{slug:22s} {n:6d} events  ({time.time() - t0:5.0f}s)", flush=True)
    print(f"done: {total} events in {time.time() - t0:.0f}s", flush=True)
