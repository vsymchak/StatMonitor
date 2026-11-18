import os
from datetime import timezone, timedelta

# Автоматичне завантаження з файлу .env (якщо присутній)
def _load_env_file():
    candidates = [
        ".env",
        os.path.join(os.path.dirname(__file__), "..", ".env"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            try:
                with open(c, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            k, v = line.split("=", 1)
                            k = k.strip()
                            v = v.strip().strip('"').strip("'")
                            if k not in os.environ:
                                os.environ[k] = v
            except Exception:
                pass
            break

_load_env_file()

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

API_KEY = os.environ.get("ODDS_API_KEY")
API_KEY_RESERVE = os.environ.get("ODDS_API_KEY_RESERVE")
API_KEY_RESERVE1 = os.environ.get("ODDS_API_KEY_RESERVE1")
API_KEY_RESERVE2 = os.environ.get("ODDS_API_KEY_RESERVE2")
API_KEY_RESERVE3 = os.environ.get("ODDS_API_KEY_RESERVE3")

ALL_ODDS_API_KEYS = [k for k in (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3) if k]
SUPABASE_DB_URL = os.environ.get("SUPABASE_DB_URL")
DB_URL = SUPABASE_DB_URL
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or os.environ.get("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID") or os.environ.get("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

INITIAL_BANKROLL = 10000.00
DASHBOARD_URL = os.environ.get("DASHBOARD_URL") or "https://statmonitor.streamlit.app"

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
