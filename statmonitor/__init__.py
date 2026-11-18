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
    check_odds_api_quota,
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
    calculate_kelly_fraction,
    eval_outcome,
    settle_and_report,
    manual_settle_bet,
    update_pending_bet_odds,
    parse_pick_label,
    resolve_alert_from_history,
    get_market_median_odds,
    recalculate_historical_paper_bets,
    BENCHMARK_BOOKMAKERS,
)
from statmonitor.pipeline import (
    check_alerts_and_notify,
)
from statmonitor.limiter import (
    get_budget_mode,
    classify_sports_urgency,
    filter_sports_to_poll,
    record_poll_success,
)
from statmonitor.bot import (
    handle_command,
    process_telegram_update,
    poll_updates,
    run_bot_worker,
)
from statmonitor.league_config import (
    load_leagues_config,
    get_active_sports_map,
    get_active_target_sports,
    get_league_thresholds,
)

__all__ = [
    "INITIAL_BANKROLL",
    "KYIV_TZ",
    "SPORTS_MAP",
    "TARGET_SPORTS",
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
    "get_sports_map",
    "check_odds_api_quota",
    "fetch_and_save_odds",
    "build_chart",
    "analyze_gemini",
    "extract_short_pick",
    "format_pick",
    "place_paper_bet",
    "calculate_kelly_fraction",
    "eval_outcome",
    "settle_and_report",
    "manual_settle_bet",
    "update_pending_bet_odds",
    "check_alerts_and_notify",
    "get_budget_mode",
    "classify_sports_urgency",
    "filter_sports_to_poll",
    "record_poll_success",
    "handle_command",
    "process_telegram_update",
    "poll_updates",
    "run_bot_worker",
    "load_leagues_config",
    "get_active_sports_map",
    "get_active_target_sports",
    "get_league_thresholds",
    "parse_pick_label",
    "resolve_alert_from_history",
    "get_market_median_odds",
    "recalculate_historical_paper_bets",
    "BENCHMARK_BOOKMAKERS",
]
