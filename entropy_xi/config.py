"""Central configuration: paths, competitions, model and publishing rules."""
from __future__ import annotations

from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RAW = DATA / "raw"
PROCESSED = DATA / "processed"
LEDGER_DIR = DATA / "ledger"
MODEL_DIR = ROOT / "models"
SITE = ROOT / "site"
SITE_DATA = SITE / "data"

# Display timezone: Beijing time (no DST), the audience's reference clock.
BJT = timezone(timedelta(hours=8), name="BJT")

# ---------------------------------------------------------------------------
# Competitions.
#   group: "league" | "cup" | "intl"
#   display: shown on the website (predictions published)
#   start: first ESPN calendar year to download
#   fd: football-data.co.uk code (main leagues: per-season CSV with Bet365 Asian lines)
#   weight: Elo K multiplier (importance)
# ---------------------------------------------------------------------------
COMPETITIONS: dict[str, dict] = {
    # --- Big Five (display, with Bet365 Asian lines from football-data) ---
    "eng.1": dict(zh="英超", en="Premier League", group="league", display=True, start=2008, fd="E0", country="England"),
    "esp.1": dict(zh="西甲", en="La Liga", group="league", display=True, start=2008, fd="SP1", country="Spain"),
    "ita.1": dict(zh="意甲", en="Serie A", group="league", display=True, start=2008, fd="I1", country="Italy"),
    "ger.1": dict(zh="德甲", en="Bundesliga", group="league", display=True, start=2008, fd="D1", country="Germany"),
    "fra.1": dict(zh="法甲", en="Ligue 1", group="league", display=True, start=2008, fd="F1", country="France"),
    "chn.1": dict(zh="中超", en="Chinese Super League", group="league", display=True, start=2016, fd_extra="CHN", country="China"),
    # --- Supporting leagues: feed the unified club ratings (European / Asian cup opponents) ---
    "eng.2": dict(zh="英冠", en="Championship", group="league", display=False, start=2012, fd="E1", country="England"),
    "esp.2": dict(zh="西乙", en="La Liga 2", group="league", display=False, start=2014, fd="SP2", country="Spain"),
    "ita.2": dict(zh="意乙", en="Serie B", group="league", display=False, start=2014, fd="I2", country="Italy"),
    "ger.2": dict(zh="德乙", en="2. Bundesliga", group="league", display=False, start=2014, fd="D2", country="Germany"),
    "fra.2": dict(zh="法乙", en="Ligue 2", group="league", display=False, start=2014, fd="F2", country="France"),
    "por.1": dict(zh="葡超", en="Primeira Liga", group="league", display=False, start=2012, fd="P1", country="Portugal"),
    "ned.1": dict(zh="荷甲", en="Eredivisie", group="league", display=False, start=2012, fd="N1", country="Netherlands"),
    "bel.1": dict(zh="比甲", en="Belgian Pro League", group="league", display=False, start=2012, fd="B1", country="Belgium"),
    "tur.1": dict(zh="土超", en="Süper Lig", group="league", display=False, start=2012, fd="T1", country="Turkey"),
    "sco.1": dict(zh="苏超", en="Scottish Premiership", group="league", display=False, start=2012, fd="SC0", country="Scotland"),
    "gre.1": dict(zh="希腊超", en="Greek Super League", group="league", display=False, start=2012, fd="G1", country="Greece"),
    "aut.1": dict(zh="奥地利甲", en="Austrian Bundesliga", group="league", display=False, start=2012, country="Austria"),
    "sui.1": dict(zh="瑞士超", en="Swiss Super League", group="league", display=False, start=2012, country="Switzerland"),
    "den.1": dict(zh="丹麦超", en="Danish Superliga", group="league", display=False, start=2012, country="Denmark"),
    "nor.1": dict(zh="挪超", en="Eliteserien", group="league", display=False, start=2012, country="Norway"),
    "swe.1": dict(zh="瑞典超", en="Allsvenskan", group="league", display=False, start=2012, country="Sweden"),
    "rus.1": dict(zh="俄超", en="Russian Premier League", group="league", display=False, start=2012, country="Russia"),
    "isr.1": dict(zh="以超", en="Israeli Premier League", group="league", display=False, start=2014, country="Israel"),
    "cyp.1": dict(zh="塞浦路斯甲", en="Cypriot First Division", group="league", display=False, start=2014, country="Cyprus"),
    "jpn.1": dict(zh="日职联", en="J1 League", group="league", display=False, start=2014, country="Japan"),
    "ksa.1": dict(zh="沙特联", en="Saudi Pro League", group="league", display=False, start=2014, country="Saudi Arabia"),
    "aus.1": dict(zh="澳超", en="A-League", group="league", display=False, start=2014, country="Australia"),
    "tha.1": dict(zh="泰超", en="Thai League 1", group="league", display=False, start=2016, country="Thailand"),
    # --- Club cups ---
    "uefa.champions": dict(zh="欧冠", en="UEFA Champions League", group="cup", display=True, start=2008, weight=1.3),
    "uefa.europa": dict(zh="欧联", en="UEFA Europa League", group="cup", display=True, start=2008, weight=1.15),
    "uefa.europa.conf": dict(zh="欧协联", en="UEFA Conference League", group="cup", display=True, start=2021, weight=1.0),
    "uefa.champions_qual": dict(zh="欧冠资格赛", en="UCL Qualifying", group="cup", display=False, start=2010, weight=1.0),
    "uefa.europa_qual": dict(zh="欧联资格赛", en="UEL Qualifying", group="cup", display=False, start=2010, weight=0.9),
    "afc.champions": dict(zh="亚冠精英", en="AFC Champions League Elite", group="cup", display=True, start=2010, weight=1.2),
    "afc.cup": dict(zh="亚冠二级", en="AFC Champions League Two", group="cup", display=False, start=2014, weight=1.0),
    "fifa.cwc": dict(zh="世俱杯", en="FIFA Club World Cup", group="cup", display=True, start=2010, weight=1.2),
    # --- National teams (history from martj42 dataset; ESPN for fixtures + live lines) ---
    "fifa.world": dict(zh="世界杯", en="FIFA World Cup", group="intl", display=True, start=2025),
    "fifa.worldq.uefa": dict(zh="世预赛欧洲区", en="WC Qualifying UEFA", group="intl", display=True, start=2025),
    "fifa.worldq.afc": dict(zh="世预赛亚洲区", en="WC Qualifying AFC", group="intl", display=True, start=2025),
    "fifa.worldq.conmebol": dict(zh="世预赛南美区", en="WC Qualifying CONMEBOL", group="intl", display=True, start=2025),
    "fifa.worldq.concacaf": dict(zh="世预赛中北美区", en="WC Qualifying CONCACAF", group="intl", display=True, start=2025),
    "fifa.worldq.caf": dict(zh="世预赛非洲区", en="WC Qualifying CAF", group="intl", display=True, start=2025),
    "uefa.euro": dict(zh="欧洲杯", en="UEFA Euro", group="intl", display=True, start=2025),
    "uefa.euroq": dict(zh="欧预赛", en="Euro Qualifying", group="intl", display=True, start=2025),
    "uefa.nations": dict(zh="欧国联", en="UEFA Nations League", group="intl", display=True, start=2025),
    "conmebol.america": dict(zh="美洲杯", en="Copa América", group="intl", display=True, start=2025),
    "afc.asian.cup": dict(zh="亚洲杯", en="AFC Asian Cup", group="intl", display=True, start=2025),
    "caf.nations": dict(zh="非洲杯", en="Africa Cup of Nations", group="intl", display=True, start=2025),
    "concacaf.gold": dict(zh="金杯赛", en="CONCACAF Gold Cup", group="intl", display=True, start=2025),
    "fifa.friendly": dict(zh="国际友谊赛", en="International Friendly", group="intl", display=True, start=2025),
}

DISPLAY_COMPS = [k for k, v in COMPETITIONS.items() if v["display"]]

# martj42 tournament name -> Elo K factor (eloratings.net convention).
INTL_K = {
    "FIFA World Cup": 60,
    "UEFA Euro": 50, "Copa América": 50, "AFC Asian Cup": 50, "African Cup of Nations": 50,
    "Gold Cup": 50, "Confederations Cup": 50, "CONCACAF Championship": 50,
    "FIFA World Cup qualification": 40, "UEFA Euro qualification": 40, "UEFA Nations League": 40,
    "AFC Asian Cup qualification": 40, "African Cup of Nations qualification": 40,
    "Copa América qualification": 40, "CONCACAF Nations League": 35, "Gold Cup qualification": 35,
    "Friendly": 20,
}
INTL_K_DEFAULT = 30
# ESPN international slug -> martj42 tournament name.
ESPN_TO_MJ_TOURNAMENT = {
    "fifa.world": "FIFA World Cup",
    "fifa.worldq.uefa": "FIFA World Cup qualification",
    "fifa.worldq.afc": "FIFA World Cup qualification",
    "fifa.worldq.conmebol": "FIFA World Cup qualification",
    "fifa.worldq.concacaf": "FIFA World Cup qualification",
    "fifa.worldq.caf": "FIFA World Cup qualification",
    "uefa.euro": "UEFA Euro",
    "uefa.euroq": "UEFA Euro qualification",
    "uefa.nations": "UEFA Nations League",
    "conmebol.america": "Copa América",
    "afc.asian.cup": "AFC Asian Cup",
    "caf.nations": "African Cup of Nations",
    "concacaf.gold": "Gold Cup",
    "fifa.friendly": "Friendly",
}

# ---------------------------------------------------------------------------
# Publishing rules.
# ---------------------------------------------------------------------------
MIN_1X2_ODDS = 1.40          # never recommend a full-time result priced below this
PUBLISH_WINDOW_HOURS = 36    # matches kicking off within this window are published and frozen
PREVIEW_WINDOW_HOURS = 96    # later matches are shown as un-frozen previews (no stars)
DEFAULT_ASIAN_ODDS = 1.90    # settlement price assumed when only an estimated Asian line exists
LIVE_START = "2026-10-19"    # first day of the frozen live ledger (Beijing date)
