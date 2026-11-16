"""
StatMonitor - Інтелектуальна платформа спортивного моніторингу та предиктивної аналітики v2.0
"""

from statmonitor.config import (
    INITIAL_BANKROLL,
    KYIV_TZ,
    SPORTS_MAP,
    TARGET_SPORTS,
    API_KEY,
    API_KEY_RESERVE,
    SUPABASE_DB_URL,
    DB_URL,
    TG_BOT_TOKEN,
    TG_CHAT_ID,
    GEMINI_API_KEY,
)
from statmonitor.database import (
    get_db,
    get_cols,
    pick,
    pick_v,
    ensure_tables,
)
from statmonitor.notifier import (
    send_tg,
    send_photo,
    esc,
    fmt_kyiv,
)
from statmonitor.fetcher import (
    get_sports_map,
    fetch_and_save_odds,
)
from statmonitor.chart import (
    build_chart,
)
from statmonitor.ai import (
    analyze_gemini,
    extract_short_pick,
)
from statmonitor.paper_trading import (
    format_pick,
    place_paper_bet,
    eval_outcome,
    settle_and_report,
)
from statmonitor.pipeline import (
    check_alerts_and_notify,
)

__all__ = [
    "INITIAL_BANKROLL",
    "KYIV_TZ",
    "SPORTS_MAP",
    "API_KEY",
    "API_KEY_RESERVE",
    "SUPABASE_DB_URL",
    "TG_BOT_TOKEN",
    "TG_CHAT_ID",
    "GEMINI_API_KEY",
    "get_db",
    "get_cols",
    "pick",
    "pick_v",
    "ensure_tables",
    "send_tg",
    "send_photo",
    "esc",
    "fmt_kyiv",
    "fetch_and_save_odds",
    "build_chart",
    "analyze_gemini",
    "extract_short_pick",
    "format_pick",
    "place_paper_bet",
    "eval_outcome",
    "settle_and_report",
    "check_alerts_and_notify",
]
