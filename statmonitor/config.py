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

TARGET_SPORTS = [
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_ukraine_premier_league", "soccer_poland_ekstraklasa",
    "soccer_uefa_champs_league", "soccer_uefa_europa_league",
    "soccer_uefa_conference_league", "soccer_uefa_nations_league",
    "basketball_nba", "tennis_atp_tour_finals", "tennis_wta_finals",
]

SPORTS_MAP = {
    "soccer_uefa_nations_league": "Ліга Націй УЄФА",
    "soccer_uefa_champs_league": "Ліга Чемпіонів УЄФА",
    "soccer_uefa_europa_league": "Ліга Європи УЄФА",
    "soccer_uefa_europa_conference_league": "Ліга Конференцій УЄФА",
    "soccer_epl": "Англія (АПЛ)",
    "soccer_spain_la_liga": "Іспанія (Ла Ліга)",
    "soccer_italy_serie_a": "Італія (Серія А)",
    "soccer_germany_bundesliga": "Німеччина (Бундесліга)",
    "soccer_france_ligue_one": "Франція (Ліга 1)",
    "soccer_poland_ekstraklasa": "Польща (Екстракласа)",
    "soccer_ukraine_premier_league": "Україна (УПЛ)",
    "basketball_nba": "США (NBA)",
    "tennis_atp_finals": "Теніс (ATP Finals)",
    "tennis_wta_finals": "Теніс (WTA Finals)",
}
