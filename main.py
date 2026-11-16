"""
StatMonitor - Головний оркестратор виконання (SPEC-13 Modular Decomposition).
"""

import time
from statmonitor import (
    INITIAL_BANKROLL,
    KYIV_TZ,
    SPORTS_MAP,
    TARGET_SPORTS,
    API_KEY,
    API_KEY_RESERVE,
    SUPABASE_DB_URL,
    TG_BOT_TOKEN,
    TG_CHAT_ID,
    GEMINI_API_KEY,
    get_db,
    get_cols,
    pick,
    pick_v,
    ensure_tables,
    send_tg,
    send_photo,
    esc,
    fmt_kyiv,
    get_sports_map,
    fetch_and_save_odds,
    build_chart,
    analyze_gemini,
    extract_short_pick,
    format_pick,
    place_paper_bet,
    eval_outcome,
    settle_and_report,
    check_alerts_and_notify,
)

def run_pipeline():
    t_start = time.time()
    s_map = get_sports_map()
    fetch_and_save_odds(s_map)
    check_alerts_and_notify(s_map, t_start=t_start)

if __name__ == "__main__":
    run_pipeline()
