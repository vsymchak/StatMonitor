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


def get_secret(key: str, default=None):
    """
    Безпечне читання секретів із пріоритетом:
    1) Змінні середовища (os.environ / .env / systemd / GitHub Secrets)
    2) Streamlit Secrets (st.secrets) — захищено try/except для headless-середовищ
    """
    val = os.environ.get(key)
    if val is not None and str(val).strip() != "":
        return str(val).strip()
    try:
        import streamlit as st
        if hasattr(st, "secrets") and key in st.secrets:
            s_val = st.secrets[key]
            if s_val is not None and str(s_val).strip() != "":
                return str(s_val).strip()
    except Exception:
        pass
    return default


try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

PROPLINE_API_KEY = get_secret("PROPLINE_API") or get_secret("PROPLINE_API_KEY")
PROPLINE_BASE_URL = (get_secret("PROPLINE_BASE_URL", "https://api.prop-line.com/v1") or "https://api.prop-line.com/v1").rstrip("/")

API_KEY = get_secret("ODDS_API_KEY")
API_KEY_RESERVE = get_secret("ODDS_API_KEY_RESERVE")
API_KEY_RESERVE1 = get_secret("ODDS_API_KEY_RESERVE1")
API_KEY_RESERVE2 = get_secret("ODDS_API_KEY_RESERVE2")
API_KEY_RESERVE3 = get_secret("ODDS_API_KEY_RESERVE3")

ALL_ODDS_API_KEYS = [k for k in (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3) if k]
DATABASE_URL = get_secret("DATABASE_URL") or get_secret("SUPABASE_DB_URL")
SUPABASE_DB_URL = DATABASE_URL
DB_URL = DATABASE_URL
SECRET_KEY = get_secret("SECRET_KEY", "")
TG_BOT_TOKEN = get_secret("TG_BOT_TOKEN") or get_secret("TELEGRAM_BOT_TOKEN")
TG_CHAT_ID = get_secret("TG_CHAT_ID") or get_secret("TELEGRAM_CHAT_ID")
GEMINI_API_KEY = get_secret("GEMINI_API_KEY")

INITIAL_BANKROLL = 10000.00
DASHBOARD_URL = get_secret("DASHBOARD_URL") or "https://statmonitor-6zj9cutprcpvckgecdxrk4.streamlit.app"

# SPEC-42: Золотий стандарт якості ШІ: поріг впевненості Gemini для відбору ставок
# Знижено вимогу до 7/10 для розширення вибірки активних ставок
DEFAULT_MIN_CONFIDENCE = int(get_secret("MIN_CONFIDENCE_THRESHOLD", 7))

# SPEC-39: Конфігурація Cloudflare R2 / S3 Cold Odds Archive
R2_ACCOUNT_ID = get_secret("R2_ACCOUNT_ID")
R2_ACCESS_KEY_ID = get_secret("R2_ACCESS_KEY_ID")
R2_SECRET_ACCESS_KEY = get_secret("R2_SECRET_ACCESS_KEY")
R2_BUCKET_NAME = get_secret("R2_BUCKET_NAME") or "statmonitor-cold-archive"
R2_ENDPOINT_URL = get_secret("R2_ENDPOINT_URL") or (f"https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com" if R2_ACCOUNT_ID else None)
LOCAL_ARCHIVE_DIR = get_secret("LOCAL_ARCHIVE_DIR") or "archive/parquet"

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
