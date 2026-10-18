"""Append-only prediction ledger.

Every published match record is frozen at publication (before kick-off). Later runs may
only (a) settle it with the final 90-minute score, or (b) replace a record that carried no
picks at all (e.g. no prices yet) while the match has not started. Replay records produced
by the walk-forward backtest are stored separately and always labelled as such.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from .. import config

LIVE = config.LEDGER_DIR / "live.json"
REPLAY = config.LEDGER_DIR / "replay.json"
PREVIEW = config.LEDGER_DIR / "preview.json"


def load(path: Path = LIVE) -> dict[str, dict]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save(data: dict[str, dict], path: Path = LIVE):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copyfile(path, path.with_suffix(".bak.json"))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    tmp.replace(path)


def publish(ledger: dict, rec: dict, now_iso: str) -> bool:
    """Insert a record if new; replace only pick-less records before kick-off. Returns True if written."""
    old = ledger.get(rec["mid"])
    if old is None:
        ledger[rec["mid"]] = rec
        return True
    if old["status"] == "pending" and not old.get("picks") and rec.get("picks") and rec["kickoff"] > now_iso:
        rec["first_published"] = old.get("published")
        ledger[rec["mid"]] = rec
        return True
    return False
