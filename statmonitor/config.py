import os
from datetime import timezone, timedelta

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

API_KEY = os.environ.get("ODDS_API_KEY")
API_KEY_RESERVE = os.environ.get("ODDS_API_KEY_RESERVE")
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")
DB_URL = SUPABASE_DB_URL
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

INITIAL_BANKROLL = 10000.00

EXHAUSTED_MODELS = set()

# Динамічна конфігураційна матриця ліг (SPEC-16)
from statmonitor.league_config import (
    load_leagues_config,
    get_active_sports_map,
    get_active_target_sports,
    get_league_thresholds,
)

LEAGUES_CONFIG = load_leagues_config()
SPORTS_MAP = get_active_sports_map(LEAGUES_CONFIG)
TARGET_SPORTS = get_active_target_sports(LEAGUES_CONFIG)
