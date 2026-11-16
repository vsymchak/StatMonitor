import os
import json
from pathlib import Path

DEFAULT_LEAGUES_CONFIG = {
    "version": "1.0",
    "leagues": [
        {"key": "soccer_epl", "title": "Англія (АПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_spain_la_liga", "title": "Іспанія (Ла Ліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_italy_serie_a", "title": "Італія (Серія А)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_germany_bundesliga", "title": "Німеччина (Бундесліга)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_france_ligue_one", "title": "Франція (Ліга 1)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_ukraine_premier_league", "title": "Україна (УПЛ)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_poland_ekstraklasa", "title": "Польща (Екстракласа)", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_uefa_champs_league", "title": "Ліга Чемпіонів УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_uefa_europa_league", "title": "Ліга Європи УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_uefa_conference_league", "title": "Ліга Конференцій УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_uefa_europa_conference_league", "title": "Ліга Конференцій УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "soccer_uefa_nations_league", "title": "Ліга Націй УЄФА", "category": "soccer", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.40, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "basketball_nba", "title": "США (NBA)", "category": "basketball", "enabled": True, "min_drop_pct": 4.0, "min_odds": 1.35, "max_odds": 4.20, "markets": ["h2h", "totals", "spreads"]},
        {"key": "tennis_atp_tour_finals", "title": "Теніс (ATP Finals)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "tennis_atp_finals", "title": "Теніс (ATP Finals)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
        {"key": "tennis_wta_finals", "title": "Теніс (WTA Finals)", "category": "tennis", "enabled": True, "min_drop_pct": 5.0, "min_odds": 1.35, "max_odds": 4.00, "markets": ["h2h", "totals", "spreads"]},
    ]
}

def resolve_config_path(config_path=None):
    """Визначає повний шлях до файлу конфігурації ліг."""
    if config_path:
        return Path(config_path)
    env_path = os.environ.get("LEAGUES_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    
    # Шукаємо від поточної директорії або від кореня проєкту
    base_dir = Path(__file__).resolve().parent.parent
    default_file = base_dir / "config" / "leagues.json"
    return default_file

def load_leagues_config(config_path=None):
    """
    Завантажує конфігурацію ліг із JSON-файлу.
    При відсутності файлу чи помилці повертає DEFAULT_LEAGUES_CONFIG.
    """
    path = resolve_config_path(config_path)
    if not path.exists():
        return DEFAULT_LEAGUES_CONFIG

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict) and "leagues" in data and isinstance(data["leagues"], list):
                return data
    except Exception as e:
        print(f"Warning: Failed to load leagues config from {path}: {e}. Using fallback defaults.")

    return DEFAULT_LEAGUES_CONFIG

def get_active_sports_map(config=None):
    """Повертає словник {sport_key: localized_title} тільки для активних ліг (enabled=True)."""
    cfg = config or load_leagues_config()
    res = {}
    for item in cfg.get("leagues", []):
        if item.get("enabled", True):
            res[item["key"]] = item.get("title", item["key"])
    return res

def get_active_target_sports(config=None):
    """Повертає список ключів активних ліг (enabled=True)."""
    cfg = config or load_leagues_config()
    return [item["key"] for item in cfg.get("leagues", []) if item.get("enabled", True)]

def get_league_thresholds(sport_key, config=None):
    """
    Повертає налаштування порогів для конкретної ліги:
    - min_drop_pct: мінімальне просідання (%)
    - min_odds: мінімальний коефіцієнт
    - max_odds: максимальний коефіцієнт
    - markets: перелік маркетів
    """
    cfg = config or load_leagues_config()
    for item in cfg.get("leagues", []):
        if item.get("key") == sport_key:
            return {
                "min_drop_pct": float(item.get("min_drop_pct", 5.0)),
                "min_odds": float(item.get("min_odds", 1.40)),
                "max_odds": float(item.get("max_odds", 4.00)),
                "markets": item.get("markets", ["h2h", "totals", "spreads"]),
            }

    # Значення за замовчуванням
    return {
        "min_drop_pct": 5.0,
        "min_odds": 1.40,
        "max_odds": 4.00,
        "markets": ["h2h", "totals", "spreads"],
    }
