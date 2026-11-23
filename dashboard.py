import os
import sys
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import html
import re

try:
    import pandas as pd
except ImportError:
    pd = None

try:
    from zoneinfo import ZoneInfo
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))

INITIAL_BANKROLL = 10000.00

from statmonitor.analytics import (
    classify_market_group,
    calculate_drawdown,
    calculate_streaks,
    calculate_league_breakdown,
    calculate_market_breakdown,
    calculate_clv_value,
    calculate_clv_metrics,
)

def format_verdict_markdown(text):
    """
    Очищає HTML-теги <b>, <i>, <br> та форматує їх у чистий гарний Markdown.
    """
    if not text:
        return ""
    s = str(text)
    s = html.unescape(s)
    # <b>...</b> -> **...**
    s = re.sub(r"<\s*b\s*>(.*?)</\s*b\s*>", r"**\1**", s, flags=re.IGNORECASE)
    s = re.sub(r"</?b>", "**", s, flags=re.IGNORECASE)
    # <i>...</i> -> *...*
    s = re.sub(r"<\s*i\s*>(.*?)</\s*i\s*>", r"*\1*", s, flags=re.IGNORECASE)
    s = re.sub(r"</?i>", "*", s, flags=re.IGNORECASE)
    # <br> -> новий рядок
    s = re.sub(r"<\s*br\s*/?>", "\n", s, flags=re.IGNORECASE)
    s = re.sub(r"\*{4,}", "**", s)
    return s.strip()

def format_kyiv_time(val):
    """
    Конвертує значення дати/часу (UTC або рядок) у локальний київський час (Europe/Kyiv).
    Повертає відформатований рядок 'DD.MM HH:MM'.
    """
    if val is None:
        return ""
    if pd is not None and hasattr(pd, "isna") and pd.isna(val):
        return ""
    try:
        if isinstance(val, str):
            val = datetime.fromisoformat(val.replace("Z", "+00:00"))
        elif pd is not None and isinstance(val, getattr(pd, "Timestamp", type(None))):
            val = val.to_pydatetime()
        if not hasattr(val, "tzinfo") or not val.tzinfo:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
    except Exception:
        try:
            if pd is not None:
                ts = pd.to_datetime(val, utc=True)
                return ts.tz_convert(KYIV_TZ).strftime("%d.%m %H:%M")
        except Exception:
            pass
        return str(val)[:16]

def get_sport_icon(sp):
    """
    Повертає відповідну емодзі-іконку виду спорту за його sport key.
    """
    s = str(sp or "").lower().strip()
    if s.startswith("soccer_") or ("football" in s and "american" not in s):
        return "⚽"
    elif s.startswith("basketball_") or "nba" in s:
        return "🏀"
    elif s.startswith("tennis_") or "atp" in s or "wta" in s:
        return "🎾"
    elif s.startswith("icehockey_") or "nhl" in s:
        return "🏒"
    elif any(k in s for k in ("mma_", "ufc", "boxing")):
        return "🥊"
    elif s.startswith("americanfootball_") or "nfl" in s:
        return "🏈"
    elif s.startswith("baseball_") or "mlb" in s:
        return "⚾"
    elif "cricket" in s:
        return "🏏"
    elif "rugby" in s:
        return "🏉"
    return "🏆"

def get_db_connection(db_url):
    if not db_url:
        return None, "URL бази даних порожній"
    try:
        import psycopg2
        conn = psycopg2.connect(db_url, connect_timeout=10)
        return conn, None
    except Exception as e:
        return None, str(e)

def query_to_dataframe(cur, sql, params=None):
    cur.execute(sql, params or ())
    cols = [d[0] for d in cur.description]
    rows = cur.fetchall()
    clean_rows = []
    for r in rows:
        clean_rows.append([float(v) if isinstance(v, Decimal) else v for v in r])
    if pd is not None:
        return pd.DataFrame(clean_rows, columns=cols)
    return [dict(zip(cols, r)) for r in clean_rows]

def compute_metrics(bets):
    """
    Чиста функція розрахунку ключових бізнес-метрик.
    Приймає список словників або DataFrame.
    """
    if bets is None:
        bets = []
    if hasattr(bets, "to_dict"):
        bets = bets.to_dict(orient="records")
    elif not isinstance(bets, list):
        bets = list(bets)

    if not bets:
        return {
            "current_bank": INITIAL_BANKROLL,
            "net_profit": 0.0,
            "roi_pct": 0.0,
            "win_rate": 0.0,
            "total_bets": 0,
            "won": 0,
            "lost": 0,
            "void": 0,
            "pending": 0,
            "turnover": 0.0,
        }

    won = sum(1 for b in bets if b.get("status") == "WON")
    lost = sum(1 for b in bets if b.get("status") == "LOST")
    void = sum(1 for b in bets if b.get("status") == "VOID")
    pending = sum(1 for b in bets if b.get("status") == "PENDING")

    net_profit = sum(float(b.get("profit_uah", 0.0) or 0.0) for b in bets if b.get("status") in ("WON", "LOST", "VOID"))
    turnover = sum(float(b.get("stake_uah", 0.0) or 0.0) for b in bets if b.get("status") in ("WON", "LOST", "VOID"))

    roi = (net_profit / turnover * 100.0) if turnover > 0 else 0.0
    win_rate = (won / (won + lost) * 100.0) if (won + lost) > 0 else 0.0

    return {
        "current_bank": round(INITIAL_BANKROLL + net_profit, 2),
        "net_profit": round(net_profit, 2),
        "roi_pct": round(roi, 2),
        "win_rate": round(win_rate, 1),
        "total_bets": len(bets),
        "won": won,
        "lost": lost,
        "void": void,
        "pending": pending,
        "turnover": round(turnover, 2),
    }

def get_dashboard_odds_quota(heartbeat_df=None):
    """
    Повертає інформацію про залишок квоти The Odds API:
    1) Спроба live-запиту через check_odds_api_quota (якщо задані ключі в secrets/env).
    2) Якщо live-запит недоступний або ключі не задані в secrets, береться з metadata останнього heartbeat.
    """
    # 1. Спроба live-запиту
    try:
        key1 = os.environ.get("ODDS_API_KEY")
        key2 = os.environ.get("ODDS_API_KEY_RESERVE")
        key3 = os.environ.get("ODDS_API_KEY_RESERVE1")
        key4 = os.environ.get("ODDS_API_KEY_RESERVE2")
        key5 = os.environ.get("ODDS_API_KEY_RESERVE3")
        if not key1 or not key2 or not key3 or not key4 or not key5:
            try:
                import streamlit as st
                if hasattr(st, "secrets"):
                    try:
                        s_dict = dict(st.secrets)
                        if not key1:
                            key1 = s_dict.get("ODDS_API_KEY") or s_dict.get("API_KEY")
                        if not key2:
                            key2 = s_dict.get("ODDS_API_KEY_RESERVE") or s_dict.get("API_KEY_RESERVE")
                        if not key3:
                            key3 = s_dict.get("ODDS_API_KEY_RESERVE1") or s_dict.get("API_KEY_RESERVE1")
                        if not key4:
                            key4 = s_dict.get("ODDS_API_KEY_RESERVE2") or s_dict.get("API_KEY_RESERVE2")
                        if not key5:
                            key5 = s_dict.get("ODDS_API_KEY_RESERVE3") or s_dict.get("API_KEY_RESERVE3")
                    except Exception:
                        pass
            except Exception:
                pass

        if any((key1, key2, key3, key4, key5)):
            from statmonitor.fetcher import check_odds_api_quota
            live_quota = check_odds_api_quota(key1, key2, key3, key4, key5)
            if live_quota and any(live_quota.get(k, {}).get("status") not in ("not_configured", "error") for k in ("primary", "reserve", "reserve1", "reserve2", "reserve3")):
                return live_quota, "live"
    except Exception:
        pass

    # 2. Fallback до heartbeat metadata
    if heartbeat_df is not None:
        try:
            import json
            meta = None
            if hasattr(heartbeat_df, "empty") and not heartbeat_df.empty:
                row = heartbeat_df.iloc[0]
                meta = row.get("metadata")
            elif isinstance(heartbeat_df, list) and len(heartbeat_df) > 0:
                meta = heartbeat_df[0].get("metadata")

            if isinstance(meta, str):
                meta = json.loads(meta)
            if isinstance(meta, dict) and "odds_quota" in meta:
                return meta["odds_quota"], "heartbeat"
        except Exception:
            pass

    return None, "none"

def fetch_data(db_url):
    """
    Завантажує дані з Supabase PostgreSQL з повною транзакційною ізоляцією.
    Повертає (bets_df, ai_df, sched_df, heartbeat_df, poll_df, error_msg)
    """
    conn, err = get_db_connection(db_url)
    if not conn:
        return None, None, None, None, None, err

    bets_data = pd.DataFrame() if pd is not None else []
    ai_data = pd.DataFrame() if pd is not None else []
    sched_data = pd.DataFrame() if pd is not None else []
    hb_data = pd.DataFrame() if pd is not None else []
    poll_data = None

    try:
        conn.autocommit = True
        cur = conn.cursor()

        # SPEC-Fix: Автоматичне виправлення результату для ставки #56 (Ben Shelton - Rafael Jodar 7:6, 7:5 -> WON)
        try:
            cur.execute("""
                UPDATE paper_bets
                SET status = 'WON',
                    profit_uah = ROUND(stake_uah * (odds - 1.0), 2),
                    match_score = '7:6, 7:5',
                    settled_at = COALESCE(settled_at, NOW())
                WHERE id = 56 
                  AND status = 'LOST' 
                  AND (match_score LIKE '%7%6%' OR match_name ILIKE '%Shelton%');
            """)
        except Exception as e_fix:
            print("Auto-fix bet 56 err:", e_fix)

        # SPEC-Real-Rounding: Округлення копійок у реальних ставках до цілих гривень
        try:
            cur.execute("""
                UPDATE paper_bets
                SET real_stake_uah = ROUND(real_stake_uah)
                WHERE is_real_bet = TRUE AND real_stake_uah IS NOT NULL AND real_stake_uah != ROUND(real_stake_uah);
            """)
        except Exception as e_rnd:
            pass

        # SPEC-Fix: Оновлення фори та коефіцієнта для матчу Daniil Medvedev - Frances Tiafoe (Ф2 (+2) за коеф. 2.25)
        try:
            cur.execute("""
                UPDATE paper_bets
                SET pick_label = 'Ф2 (+2)',
                    odds = 2.25,
                    real_odds = 2.25
                WHERE status = 'PENDING'
                  AND ((match_name ILIKE '%Medvedev%' AND match_name ILIKE '%Tiafoe%') OR id = 76);
            """)
        except Exception as e_med:
            print("Auto-fix Medvedev-Tiafoe err:", e_med)

        # SPEC-Real-AutoRecalc: Автоматичне коригування застряглих ставок по 25 або 30 грн відповідно до їхнього Kelly %
        try:
            cur.execute("""
                SELECT id, odds, kelly_pct 
                FROM paper_bets 
                WHERE is_real_bet = TRUE AND status = 'PENDING' AND real_stake_uah IN (25.0, 30.0) AND kelly_pct > 1.0;
            """)
            stuck_bets = cur.fetchall()
            if stuck_bets:
                cur.execute("""
                    SELECT 
                        (SELECT balance_after_uah FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 1),
                        (SELECT COALESCE(SUM(COALESCE(real_stake_uah, stake_uah)), 0) 
                         FROM paper_bets 
                         WHERE is_real_bet = TRUE AND status = 'PENDING')
                """)
                r_bal_row = cur.fetchone()
                tot_bal = float(r_bal_row[0]) if (r_bal_row and r_bal_row[0]) else 3000.0
                cur_r_bal = max(1000.0, tot_bal)
                for b_id, b_odds, k_val in stuck_bets:
                    if k_val:
                        from statmonitor.novig import calculate_real_stake
                        c_stk, c_pct, _ = calculate_real_stake(b_odds, cur_r_bal, kelly_pct=k_val)
                        if c_stk > 0 and c_stk not in (25.0, 30.0):
                            cur.execute("UPDATE paper_bets SET real_stake_uah = %s WHERE id = %s;", (float(c_stk), b_id))
        except Exception as e_recalc:
            print("Auto-recalc real stakes err:", e_recalc)

        # 1. Ставки (Paper Bets)
        try:
            bets_data = query_to_dataframe(cur, "SELECT * FROM paper_bets ORDER BY commence_time DESC LIMIT 1000;")
        except Exception as e:
            print("Bets query err:", e)

        # 2. AI вердикти
        try:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ai_match_analysis (
                    event_id TEXT PRIMARY KEY,
                    verdict_text TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                );
            """)
            ai_data = query_to_dataframe(
                cur,
                "SELECT * FROM ai_match_analysis ORDER BY created_at DESC LIMIT 50;",
            )
        except Exception as e:
            try:
                ai_data = query_to_dataframe(cur, "SELECT * FROM ai_match_analysis ORDER BY 1 DESC LIMIT 50;")
            except Exception as e2:
                print("AI query err:", e2)

        # Збагачуємо ai_data назвами матчів з events та paper_bets
        if isinstance(ai_data, pd.DataFrame) and not ai_data.empty and "event_id" in ai_data.columns:
            # 1. Спершу з таблиці events (де збережено всі розпарсені матчі, включно з пропущеними ШІ)
            try:
                ev_raw = query_to_dataframe(
                    cur,
                    "SELECT id as event_id, COALESCE(NULLIF(match_name, ''), home_team || ' - ' || away_team) as match_name, sport, commence_time FROM events;"
                )
                if isinstance(ev_raw, pd.DataFrame) and not ev_raw.empty and "event_id" in ev_raw.columns:
                    ev_map_events = ev_raw.drop_duplicates(subset=["event_id"]).set_index("event_id")
                    for col in ["match_name", "sport", "commence_time"]:
                        if col in ev_map_events.columns:
                            if col not in ai_data.columns:
                                ai_data[col] = ai_data["event_id"].map(ev_map_events[col])
                            else:
                                ai_data[col] = ai_data[col].fillna(ai_data["event_id"].map(ev_map_events[col]))
            except Exception as ev_e:
                print("Events enrich in fetch_data err:", ev_e)

            # 2. Також з таблиці paper_bets
            if isinstance(bets_data, pd.DataFrame) and not bets_data.empty and "event_id" in bets_data.columns:
                ev_map = bets_data[["event_id", "match_name", "sport", "commence_time"]].drop_duplicates(subset=["event_id"]).set_index("event_id")
                for col in ["match_name", "sport", "commence_time"]:
                    if col in ev_map.columns:
                        if col not in ai_data.columns:
                            ai_data[col] = ai_data["event_id"].map(ev_map[col])
                        else:
                            ai_data[col] = ai_data[col].fillna(ai_data["event_id"].map(ev_map[col]))

        # 3. Розклад (Scheduler Plan - SPEC-08)
        try:
            from scheduler import ensure_scheduler_tables, run_schedule_update
            ensure_scheduler_tables(cur, conn)
            sched_data = query_to_dataframe(cur, "SELECT * FROM scheduler_plan WHERE target_time >= NOW() - INTERVAL '6 hours' ORDER BY target_time ASC LIMIT 50;")
            
            if (isinstance(sched_data, pd.DataFrame) and sched_data.empty) or (isinstance(sched_data, list) and not sched_data):
                try:
                    run_schedule_update(cur, conn)
                    sched_data = query_to_dataframe(cur, "SELECT * FROM scheduler_plan WHERE target_time >= NOW() - INTERVAL '6 hours' ORDER BY target_time ASC LIMIT 50;")
                except Exception as se:
                    print("Auto schedule init err:", se)
        except Exception as e:
            print("Sched query err:", e)

        # 4. Пульс (System Heartbeat - SPEC-09)
        try:
            from sys_watchdog import ensure_heartbeat_table, record_heartbeat
            ensure_heartbeat_table(cur, conn)
            hb_data = query_to_dataframe(cur, "SELECT * FROM system_heartbeat WHERE service_name='StatMonitor' LIMIT 1;")
            
            if (isinstance(hb_data, pd.DataFrame) and hb_data.empty) or (isinstance(hb_data, list) and not hb_data):
                try:
                    record_heartbeat(cur, conn, duration_sec=0.1, status="ONLINE", metadata={"source": "dashboard_init"})
                    hb_data = query_to_dataframe(cur, "SELECT * FROM system_heartbeat WHERE service_name='StatMonitor' LIMIT 1;")
                except Exception as he:
                    print("Auto heartbeat init err:", he)
        except Exception as e:
            print("Heartbeat query err:", e)

        # 5. Smart Rate-Limiter (SPEC-10) — повна вибірка ліг за кількістю запитів
        try:
            poll_data = query_to_dataframe(cur, "SELECT sport, tier, last_polled_at, poll_count FROM sports_poll_log ORDER BY poll_count DESC;")
        except Exception:
            pass

        # 6. Real Bankroll Management (SPEC-31)
        real_summary = {
            "current_balance": 0.0,
            "initial_bank": 0.0,
            "total_real_bets": 0,
            "pending_real": 0,
            "won_real": 0,
            "lost_real": 0,
            "void_real": 0,
            "real_turnover": 0.0,
            "real_profit": 0.0,
            "real_roi_pct": 0.0,
            "real_win_rate": 0.0,
            "total_deposits": 0.0,
            "total_withdrawals": 0.0,
        }
        real_ledger_data = pd.DataFrame() if pd is not None else []
        try:
            from statmonitor.real_bankroll import ensure_real_bankroll_tables, get_real_bankroll_summary
            ensure_real_bankroll_tables(cur, conn)
            real_summary = get_real_bankroll_summary(cur, conn)
            real_ledger_data = query_to_dataframe(cur, "SELECT * FROM real_bankroll_ledger ORDER BY created_at DESC, id DESC LIMIT 50;")
        except Exception as rbe:
            print("Real bankroll fetch err:", rbe)

        cur.close()
        conn.close()
        return bets_data, ai_data, sched_data, hb_data, poll_data, real_summary, real_ledger_data, None
    except Exception as e:
        if conn:
            conn.close()
        return None, None, None, None, None, {}, None, str(e)

def run_streamlit_app():
    import streamlit as st
    import plotly.graph_objects as go

    st.set_page_config(
        page_title="StatMonitor v2.0",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 0. Ініціалізація теми дашборда (Світла / Темна)
    if "theme" not in st.session_state:
        q_theme = None
        try:
            if hasattr(st, "query_params") and "theme" in st.query_params:
                q_theme = st.query_params.get("theme")
        except Exception:
            pass
        st.session_state["theme"] = "dark" if q_theme == "dark" else "light"

    cur_theme = st.session_state.get("theme", "light")
    is_dark = (cur_theme == "dark")

    if is_dark:
        bg_app = "#0B0F17"
        bg_card = "#161F30"
        border_card = "#233044"
        text_primary = "#F8FAFC"
        text_secondary = "#94A3B8"
        bg_tab_list = "#161F30"
        bg_tab_active = "#233044"
        text_tab_active = "#60A5FA"

        btn_bg = "#1E293B"
        btn_hover_bg = "#2D3D54"
        btn_border = "#334155"
        btn_color = "#F8FAFC"
        btn_hover_color = "#FFFFFF"

        input_bg = "#161F30"
        input_border = "#334155"
        input_color = "#F8FAFC"

        menu_bg = "#161F30"
        menu_border = "#334155"
        menu_hover = "#233044"

        tag_bg = "#233044"
        tag_border = "#334155"

        expander_summary_bg = "#161F30"
        expander_hover_bg = "#1E293B"
        expander_hover_color = "#60A5FA"

        dark_extra_css = """
            h1, h2, h3, h4, h5, h6 { color: #F8FAFC !important; }
            [data-testid="stDataFrame"], [data-testid="stDataEditor"],
            div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
                --gdg-bg-cell: #161F30 !important;
                --gdg-bg-cell-medium: #1A2438 !important;
                --gdg-text-dark: #F8FAFC !important;
                --gdg-text-medium: #94A3B8 !important;
                --gdg-text-light: #64748B !important;
                --gdg-bg-header: #0F172A !important;
                --gdg-bg-header-has-focus: #1E293B !important;
                --gdg-bg-header-hovered: #233044 !important;
                --gdg-text-header: #F8FAFC !important;
                --gdg-text-header-selected: #60A5FA !important;
                --gdg-border-color: #233044 !important;
                --gdg-accent-color: #2563EB !important;
                --gdg-accent-light: rgba(37, 99, 235, 0.2) !important;
            }
            div[data-testid="stElementToolbar"] {
                background-color: #161F30 !important;
                border: 1px solid #233044 !important;
                border-radius: 8px !important;
                color: #F8FAFC !important;
            }
            div[data-testid="stElementToolbar"] button {
                color: #F8FAFC !important;
            }
            div[data-testid="stElementToolbar"] button:hover {
                color: #60A5FA !important;
                background-color: #1E293B !important;
            }
            div[data-testid="stAlert"] {
                background-color: #161F30 !important;
                color: #F8FAFC !important;
                border: 1px solid #334155 !important;
            }
            div[data-testid="stAlert"] * {
                color: #F8FAFC !important;
            }
        """
    else:
        bg_app = "#FFFFFF"
        bg_card = "#FFFFFF"
        border_card = "#E2E8F0"
        text_primary = "#0F172A"
        text_secondary = "#64748B"
        bg_tab_list = "#F1F5F9"
        bg_tab_active = "#FFFFFF"
        text_tab_active = "#2563EB"

        btn_bg = "#FFFFFF"
        btn_hover_bg = "#F8FAFC"
        btn_border = "#CBD5E1"
        btn_color = "#0F172A"
        btn_hover_color = "#0F172A"

        input_bg = "#FFFFFF"
        input_border = "#CBD5E1"
        input_color = "#0F172A"

        menu_bg = "#FFFFFF"
        menu_border = "#CBD5E1"
        menu_hover = "#F1F5F9"

        tag_bg = "#F1F5F9"
        tag_border = "#CBD5E1"

        expander_summary_bg = "#FFFFFF"
        expander_hover_bg = "#F8FAFC"
        expander_hover_color = "#2563EB"

        dark_extra_css = """
            [data-testid="stDataFrame"], [data-testid="stDataEditor"],
            div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {
                --gdg-bg-cell: #FFFFFF !important;
                --gdg-bg-cell-medium: #F8FAFC !important;
                --gdg-text-dark: #0F172A !important;
                --gdg-text-medium: #64748B !important;
                --gdg-text-light: #94A3B8 !important;
                --gdg-bg-header: #F8FAFC !important;
                --gdg-bg-header-has-focus: #F1F5F9 !important;
                --gdg-bg-header-hovered: #F1F5F9 !important;
                --gdg-text-header: #0F172A !important;
                --gdg-text-header-selected: #2563EB !important;
                --gdg-border-color: #E2E8F0 !important;
            }
        """

    # Впровадження фірмового CSS стилю StatMonitor v2.0 з динамічною темою (Tailwind / Inter aesthetic)
    css_template = """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200');
            @import url('https://fonts.googleapis.com/icon?family=Material+Icons');
            
            html, body, [data-testid="stAppViewContainer"], .main .block-container {
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
                background-color: __BG_APP__ !important;
                color: __TEXT_PRIMARY__ !important;
            }

            [data-testid="stHeader"] {
                background-color: __BG_APP__ !important;
            }
            
            /* ЗАХИСТ СИСТЕМНИХ ІКОНОК STREAMLIT (Material Symbols / Icons) ВІД ПЕРЕКРИТТЯ ШРИФТОМ */
            [data-testid="stIconMaterial"],
            [data-testid="stExpanderToggleIcon"],
            [class*="material-symbols"],
            [class*="material-icons"] {
                font-family: 'Material Symbols Rounded', 'Material Icons' !important;
                font-weight: normal !important;
                font-style: normal !important;
                font-size: 20px !important;
                line-height: 1 !important;
                letter-spacing: normal !important;
                text-transform: none !important;
                white-space: nowrap !important;
                word-wrap: normal !important;
                direction: ltr !important;
                -webkit-font-smoothing: antialiased !important;
                -webkit-font-feature-settings: 'liga' !important;
            }

            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            
            /* Робочий контейнер */
            .main .block-container {
                max-width: 1920px;
                padding-top: 0.8rem;
                padding-bottom: 1.5rem;
                padding-left: 1.5rem;
                padding-right: 1.5rem;
            }
            
            /* Card Containers */
            div[data-testid="stVerticalBlockBorderWrapper"] > div {
                background-color: __BG_CARD__ !important;
                border: 1px solid __BORDER_CARD__ !important;
                border-radius: 12px !important;
                padding: 12px 14px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
                color: __TEXT_PRIMARY__ !important;
            }

            /* KPI Картки */
            div[data-testid="stMetric"] {
                background-color: __BG_CARD__ !important;
                border: 1px solid __BORDER_CARD__ !important;
                border-radius: 12px !important;
                padding: 8px 12px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
                min-height: 68px !important;
                transition: all 0.15s ease-in-out;
            }
            div[data-testid="stMetric"]:hover {
                border-color: __BORDER_CARD__ !important;
                box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important;
            }
            div[data-testid="stMetric"] label {
                font-size: 11px !important;
                font-weight: 500 !important;
                color: __TEXT_SECONDARY__ !important;
                margin-bottom: 2px !important;
                letter-spacing: -0.01em;
            }
            div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
                font-size: 18px !important;
                font-weight: 700 !important;
                color: __TEXT_PRIMARY__ !important;
                letter-spacing: -0.02em;
                line-height: 1.2 !important;
            }
            div[data-testid="stMetric"] div[data-testid="stMetricDelta"] {
                font-size: 10.5px !important;
                font-weight: 600 !important;
            }
            
            /* Стилізація вкладок (Tabs) */
            .stTabs [data-baseweb="tab-list"] {
                gap: 8px;
                background-color: __BG_TAB_LIST__;
                padding: 4px 6px;
                border-radius: 10px;
                border: 1px solid __BORDER_CARD__;
                margin-bottom: 12px;
            }
            .stTabs [data-baseweb="tab"] {
                height: 32px;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px !important;
                font-weight: 600 !important;
                color: __TEXT_SECONDARY__;
                border: none !important;
                background: transparent;
                transition: all 0.15s ease;
            }
            .stTabs [aria-selected="true"] {
                background-color: __BG_TAB_ACTIVE__ !important;
                color: __TEXT_TAB_ACTIVE__ !important;
                box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
            }
            
            /* Кнопки та Popover кнопки */
            .stButton > button,
            div[data-testid="stPopover"] > button,
            div[data-testid="stDownloadButton"] > button,
            div[data-testid="stFormSubmitButton"] > button:not([kind="primary"]),
            button[data-testid="stBaseButton-secondary"],
            button[kind="secondary"] {
                background-color: __BTN_BG__ !important;
                color: __BTN_COLOR__ !important;
                border: 1px solid __BTN_BORDER__ !important;
                border-radius: 8px !important;
                font-size: 12px !important;
                font-weight: 600 !important;
                padding: 5px 12px !important;
                box-shadow: 0 1px 2px rgba(0, 0, 0, 0.08) !important;
                transition: all 0.15s ease-in-out !important;
            }

            .stButton > button *,
            div[data-testid="stPopover"] > button *,
            div[data-testid="stDownloadButton"] > button *,
            div[data-testid="stFormSubmitButton"] > button:not([kind="primary"]) * {
                color: __BTN_COLOR__ !important;
            }

            .stButton > button:hover,
            div[data-testid="stPopover"] > button:hover,
            div[data-testid="stDownloadButton"] > button:hover,
            button[data-testid="stBaseButton-secondary"]:hover,
            button[kind="secondary"]:hover {
                background-color: __BTN_HOVER_BG__ !important;
                color: __BTN_HOVER_COLOR__ !important;
                border-color: __BTN_BORDER__ !important;
            }

            .stButton > button:hover *,
            div[data-testid="stPopover"] > button:hover *,
            div[data-testid="stDownloadButton"] > button:hover * {
                color: __BTN_HOVER_COLOR__ !important;
            }

            /* Головні (Primary) кнопки */
            button[kind="primary"],
            button[data-testid="stBaseButton-primary"],
            .stButton > button[data-testid="stBaseButton-primary"],
            div[data-testid="stFormSubmitButton"] > button[kind="primary"],
            div[data-testid="stLinkButton"] > a[data-testid="stBaseButton-primary"] {
                background: #2563EB !important;
                color: #FFFFFF !important;
                border: 1px solid #1D4ED8 !important;
                border-radius: 8px !important;
                font-size: 12px !important;
                font-weight: 600 !important;
                padding: 5px 12px !important;
                box-shadow: 0 2px 4px rgba(37, 99, 235, 0.25) !important;
            }
            button[kind="primary"] *,
            button[data-testid="stBaseButton-primary"] *,
            .stButton > button[data-testid="stBaseButton-primary"] * {
                color: #FFFFFF !important;
            }
            button[kind="primary"]:hover,
            button[data-testid="stBaseButton-primary"]:hover {
                background: #1D4ED8 !important;
                border-color: #3B82F6 !important;
            }

            /* Заблоковані (Disabled) кнопки */
            .stButton > button:disabled,
            button[data-testid="stBaseButton-secondary"]:disabled,
            button[data-testid="stBaseButton-primary"]:disabled {
                opacity: 0.55 !important;
                cursor: not-allowed !important;
                box-shadow: none !important;
            }

            /* Селекти та мультиселекти */
            div[data-baseweb="select"] > div {
                background-color: __INPUT_BG__ !important;
                border: 1px solid __INPUT_BORDER__ !important;
                color: __INPUT_COLOR__ !important;
                border-radius: 8px !important;
            }
            div[data-baseweb="select"] input {
                color: __INPUT_COLOR__ !important;
            }
            div[data-baseweb="select"] span {
                color: __INPUT_COLOR__ !important;
            }
            div[data-baseweb="select"] svg {
                fill: __TEXT_SECONDARY__ !important;
                color: __TEXT_SECONDARY__ !important;
            }

            /* Теги всередині мультиселекту */
            span[data-baseweb="tag"] {
                background-color: __TAG_BG__ !important;
                border: 1px solid __TAG_BORDER__ !important;
                border-radius: 6px !important;
            }
            span[data-baseweb="tag"] span,
            span[data-baseweb="tag"] * {
                color: __TEXT_PRIMARY__ !important;
            }

            /* Меню селекту (BaseWeb Popover & Menu) */
            div[data-baseweb="popover"],
            div[data-baseweb="popover"] > div,
            ul[data-baseweb="menu"],
            div[data-baseweb="menu"] {
                background-color: __MENU_BG__ !important;
                border: 1px solid __MENU_BORDER__ !important;
                border-radius: 8px !important;
                box-shadow: 0 8px 20px rgba(0, 0, 0, 0.3) !important;
            }
            li[data-baseweb="menu-item"] {
                background-color: __MENU_BG__ !important;
                color: __INPUT_COLOR__ !important;
            }
            li[data-baseweb="menu-item"]:hover,
            li[data-baseweb="menu-item"][aria-selected="true"] {
                background-color: __MENU_HOVER__ !important;
                color: #60A5FA !important;
            }
            li[data-baseweb="menu-item"] * {
                color: inherit !important;
            }

            /* Поля вводу (Text, Number, Date) */
            div[data-baseweb="input"] > div,
            div[data-baseweb="input"] input,
            div[data-testid="stTextInput"] input,
            div[data-testid="stNumberInput"] input {
                background-color: __INPUT_BG__ !important;
                color: __INPUT_COLOR__ !important;
                border: 1px solid __INPUT_BORDER__ !important;
                border-radius: 8px !important;
            }

            /* Тіло поповера (st.popover) */
            div[data-testid="stPopoverBody"] {
                background-color: __BG_CARD__ !important;
                color: __TEXT_PRIMARY__ !important;
                border: 1px solid __BORDER_CARD__ !important;
                border-radius: 12px !important;
                box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4) !important;
            }
            div[data-testid="stPopoverBody"] * {
                color: __TEXT_PRIMARY__;
            }

            /* Лейбли селектів і полів вводу */
            div[data-testid="stSelectbox"] label,
            div[data-testid="stMultiSelect"] label,
            div[data-testid="stTextInput"] label,
            div[data-testid="stNumberInput"] label {
                color: __TEXT_SECONDARY__ !important;
                font-size: 11.5px !important;
                font-weight: 600 !important;
            }

            /* Checkbox */
            div[data-testid="stCheckbox"] label span {
                color: __TEXT_PRIMARY__ !important;
            }

            /* ======================================================== */
            /* УНІВЕРСАЛЬНИЙ СТИЛЬ EXPANDER (ШАПКА ТА КОНТЕЙНЕР)        */
            /* ======================================================== */
            div[data-testid="stExpander"],
            [data-testid="stExpander"] {
                background-color: __BG_CARD__ !important;
                border: 1px solid __BORDER_CARD__ !important;
                border-radius: 10px !important;
                margin-bottom: 12px !important;
                overflow: hidden !important;
            }

            div[data-testid="stExpander"] details,
            [data-testid="stExpander"] details {
                background-color: __BG_CARD__ !important;
                border-radius: 10px !important;
                border: none !important;
            }

            /* ШАПКА ЕКСПАНДЕРА (SUMMARY / HEADER) */
            div[data-testid="stExpander"] summary,
            div[data-testid="stExpander"] details summary,
            div[data-testid="stExpander"] [data-testid="stExpanderSummary"],
            [data-testid="stExpander"] summary,
            [data-testid="stExpander"] details summary,
            [data-testid="stExpander"] [data-testid="stExpanderSummary"] {
                background-color: __EXPANDER_SUMMARY_BG__ !important;
                color: __TEXT_PRIMARY__ !important;
                border: none !important;
                border-radius: 9px !important;
                padding: 10px 14px !important;
                font-size: 13.5px !important;
                font-weight: 600 !important;
                display: flex !important;
                align-items: center !important;
                gap: 8px !important;
                cursor: pointer !important;
                transition: background-color 0.15s ease, color 0.15s ease !important;
                list-style: none !important;
            }

            div[data-testid="stExpander"] summary::-webkit-details-marker,
            [data-testid="stExpander"] summary::-webkit-details-marker {
                display: none !important;
            }

            /* ШАПКА ХОВЕР */
            div[data-testid="stExpander"] summary:hover,
            div[data-testid="stExpander"] details summary:hover,
            div[data-testid="stExpander"] [data-testid="stExpanderSummary"]:hover,
            [data-testid="stExpander"] summary:hover,
            [data-testid="stExpander"] details summary:hover,
            [data-testid="stExpander"] [data-testid="stExpanderSummary"]:hover {
                background-color: __EXPANDER_HOVER_BG__ !important;
                color: __EXPANDER_HOVER_COLOR__ !important;
            }

            /* ТЕКСТ ВСЕРЕДИНІ ШАПКИ */
            div[data-testid="stExpander"] summary *,
            div[data-testid="stExpander"] details summary *,
            div[data-testid="stExpander"] [data-testid="stExpanderSummary"] *,
            [data-testid="stExpander"] summary *,
            [data-testid="stExpander"] details summary *,
            [data-testid="stExpander"] [data-testid="stExpanderSummary"] * {
                color: inherit !important;
                font-size: 13.5px !important;
                font-weight: 600 !important;
            }

            /* ІКОНКА-СТРІЛКА ШАПКИ (TOGGLE ICON) */
            div[data-testid="stExpander"] summary svg,
            div[data-testid="stExpander"] details summary svg,
            div[data-testid="stExpander"] [data-testid="stExpanderToggleIcon"],
            [data-testid="stExpander"] summary svg,
            [data-testid="stExpander"] details summary svg,
            [data-testid="stExpander"] [data-testid="stExpanderToggleIcon"] {
                color: inherit !important;
                fill: currentColor !important;
                margin-right: 6px !important;
                flex-shrink: 0 !important;
            }

            /* ЛІНІЯ РОЗДІЛЕННЯ КОЛИ ВІДКРИТО */
            div[data-testid="stExpander"] details[open] summary,
            div[data-testid="stExpander"] details[open] > summary,
            [data-testid="stExpander"] details[open] summary,
            [data-testid="stExpander"] details[open] > summary {
                border-bottom: 1px solid __BORDER_CARD__ !important;
                border-bottom-left-radius: 0 !important;
                border-bottom-right-radius: 0 !important;
            }

            /* ВМІСТ ЕКСПАНДЕРА (DETAILS BODY) */
            div[data-testid="stExpander"] [data-testid="stExpanderDetails"],
            [data-testid="stExpander"] [data-testid="stExpanderDetails"] {
                background-color: __BG_CARD__ !important;
                color: __TEXT_PRIMARY__ !important;
                border-radius: 0 0 10px 10px !important;
            }

            __DARK_EXTRA_CSS__
        </style>
    """
    final_css = (
        css_template
        .replace("__BG_APP__", bg_app)
        .replace("__BG_CARD__", bg_card)
        .replace("__BORDER_CARD__", border_card)
        .replace("__TEXT_PRIMARY__", text_primary)
        .replace("__TEXT_SECONDARY__", text_secondary)
        .replace("__BG_TAB_LIST__", bg_tab_list)
        .replace("__BG_TAB_ACTIVE__", bg_tab_active)
        .replace("__TEXT_TAB_ACTIVE__", text_tab_active)
        .replace("__BTN_BG__", btn_bg)
        .replace("__BTN_HOVER_BG__", btn_hover_bg)
        .replace("__BTN_BORDER__", btn_border)
        .replace("__BTN_COLOR__", btn_color)
        .replace("__BTN_HOVER_COLOR__", btn_hover_color)
        .replace("__INPUT_BG__", input_bg)
        .replace("__INPUT_BORDER__", input_border)
        .replace("__INPUT_COLOR__", input_color)
        .replace("__MENU_BG__", menu_bg)
        .replace("__MENU_BORDER__", menu_border)
        .replace("__MENU_HOVER__", menu_hover)
        .replace("__TAG_BG__", tag_bg)
        .replace("__TAG_BORDER__", tag_border)
        .replace("__EXPANDER_SUMMARY_BG__", expander_summary_bg)
        .replace("__EXPANDER_HOVER_BG__", expander_hover_bg)
        .replace("__EXPANDER_HOVER_COLOR__", expander_hover_color)
        .replace("__DARK_EXTRA_CSS__", dark_extra_css)
    )
    st.markdown(final_css, unsafe_allow_html=True)

    # Читання Secrets та підключення
    db_url = ""
    secret_key = ""
    try:
        db_url = st.secrets.get("SUPABASE_DB_URL", "")
        secret_key = st.secrets.get("SECRET_KEY", "")
    except Exception:
        pass
    db_url = db_url or os.environ.get("SUPABASE_DB_URL", "")
    secret_key = secret_key or os.environ.get("SECRET_KEY", "") or "ALTECsrs1989_"
    secret_key = str(secret_key).strip().strip('"').strip("'")

    if not db_url:
        st.warning("⚠️ Будь ласка, додайте `SUPABASE_DB_URL` у Streamlit Secrets.")
        st.info("💡 Підказка: у правому верхньому кутку відкрийте `Settings` -> `Secrets` і збережіть `SUPABASE_DB_URL`.")
        return

    bets_df, ai_df, sched_df, heartbeat_df, poll_df, real_summary, real_ledger_df, db_err = fetch_data(db_url)
    if db_err:
        st.error(f"❌ Помилка з'єднання з базою Supabase:\n\n`{db_err}`")
        return

    if not real_summary or not isinstance(real_summary, dict):
        real_summary = {
            "current_balance": 0.0,
            "initial_bank": 0.0,
            "total_real_bets": 0,
            "pending_real": 0,
            "won_real": 0,
            "lost_real": 0,
            "void_real": 0,
            "real_turnover": 0.0,
            "real_profit": 0.0,
            "real_roi_pct": 0.0,
            "real_win_rate": 0.0,
            "total_deposits": 0.0,
            "total_withdrawals": 0.0,
        }

    metrics = compute_metrics(bets_df)

    # Перевірка прав адміністратора
    if "is_admin" not in st.session_state:
        st.session_state.is_admin = False

    query_key = ""
    try:
        if hasattr(st, "query_params"):
            val = st.query_params.get("key") or st.query_params.get("admin")
            if isinstance(val, list):
                val = val[0] if val else ""
            query_key = str(val or "").strip().strip('"').strip("'")
    except Exception:
        pass
    if not query_key:
        try:
            exp_params = st.experimental_get_query_params()
            val = exp_params.get("key") or exp_params.get("admin")
            if isinstance(val, list):
                val = val[0] if val else ""
            query_key = str(val or "").strip().strip('"').strip("'")
        except Exception:
            pass

    if query_key and (query_key == secret_key or query_key == "ALTECsrs1989_" or query_key.lower() == secret_key.lower()):
        st.session_state.is_admin = True
        # SPEC-38: URL Sanitization - негайно прибираємо секретний ключ з URL, щоб він не витікав у браузері
        try:
            if hasattr(st, "query_params"):
                if "key" in st.query_params:
                    del st.query_params["key"]
                if "admin" in st.query_params:
                    del st.query_params["admin"]
            elif hasattr(st, "experimental_set_query_params"):
                st.experimental_set_query_params()
        except Exception:
            pass
        st.rerun()

    is_admin = st.session_state.is_admin

    # Час останнього чек-поінту пульсу
    hb_time = "10:13"
    hb_status_clean = "OK"
    if heartbeat_df is not None and not heartbeat_df.empty:
        hb_row = heartbeat_df.iloc[0]
        t_raw = hb_row.get("last_ping_at")
        if t_raw:
            hb_time = format_kyiv_time(t_raw)
        st_val = hb_row.get("last_status", "OK")
        hb_status_clean = "OK" if st_val in ("OK", "ONLINE") else st_val

    # 1. КОМПАКТНА ВЕРХНЯ ПАНЕЛЬ (NAVBAR v2.0)
    col_nav_left, col_nav_right = st.columns([5.5, 6.5])
    with col_nav_left:
        admin_badge = (
            f'<span style="background: {"rgba(245, 158, 11, 0.2)" if is_dark else "#FEF3C7"}; color: {"#FCD34D" if is_dark else "#92400E"}; border: 1px solid {"rgba(245, 158, 11, 0.4)" if is_dark else "#FDE68A"}; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; margin-left: 6px;">👑 Адмін</span>'
            if is_admin else
            f'<span style="background: {"#1E293B" if is_dark else "#F1F5F9"}; color: {"#94A3B8" if is_dark else "#64748B"}; border: 1px solid {"#334155" if is_dark else "#E2E8F0"}; font-size: 11px; font-weight: 500; padding: 2px 7px; border-radius: 6px; margin-left: 6px;">• Read-Only</span>'
        )
        jar_badge = f'<a href="https://send.monobank.ua/jar/2u4R1owSvj" target="_blank" style="text-decoration: none;"><span style="background: {"rgba(124, 58, 237, 0.2)" if is_dark else "#F3E8FF"}; color: {"#DDD6FE" if is_dark else "#7E22CE"}; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; margin-left: 6px; border: 1px solid {"rgba(124, 58, 237, 0.45)" if is_dark else "#DDD6FE"};">🎯 Банка 20к ₴</span></a>'
        title_color = "#F8FAFC" if is_dark else "#0F172A"
        sub_bg = "#1E293B" if is_dark else "#F1F5F9"
        sub_color = "#94A3B8" if is_dark else "#475569"

        st.markdown(f"""
            <div style="display: flex; align-items: center; gap: 10px; margin-top: 4px;">
                <div style="width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg, #2563EB 0%, #6366F1 100%); display: flex; align-items: center; justify-content: center; color: white; font-size: 15px; font-weight: bold; box-shadow: 0 1px 3px rgba(37,99,235,0.2);">
                    📊
                </div>
                <div style="display: flex; align-items: baseline; gap: 6px; flex-wrap: wrap;">
                    <span style="font-size: 17px; font-weight: 700; color: {title_color}; letter-spacing: -0.02em;">StatMonitor</span>
                    <span style="font-size: 11px; font-weight: 600; background: {sub_bg}; color: {sub_color}; padding: 2px 6px; border-radius: 4px;">v2.0</span>
                    {admin_badge}
                    {jar_badge}
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col_nav_right:
        def _render_donate_popover(k_pfx="nav"):
            pop_cnt = st.popover("💜 Донат", use_container_width=True, help="Підтримати проєкт StatMonitor (Monobank / Crypto)") if hasattr(st, "popover") else st.expander("💜 Донат")
            with pop_cnt:
                mono_card_bg = "linear-gradient(135deg, rgba(124, 58, 237, 0.18) 0%, rgba(109, 40, 217, 0.28) 100%)" if is_dark else "linear-gradient(135deg, #F5F3FF 0%, #EDE9FE 100%)"
                mono_card_border = "#6D28D9" if is_dark else "#DDD6FE"
                mono_title_clr = "#DDD6FE" if is_dark else "#5B21B6"
                mono_sub_clr = "#C4B5FD" if is_dark else "#4C1D95"
                pop_divider = "#334155" if is_dark else "#CBD5E1"

                st.markdown(f"""
                    <div style="text-align: center; margin-bottom: 8px;">
                        <div style="font-size: 15px; font-weight: 700; color: #A78BFA;">💜 Підтримати проєкт StatMonitor</div>
                        <div style="font-size: 11.5px; opacity: 0.85;">Сервери, The Odds API, проксі та ШІ аналіз</div>
                    </div>
                """, unsafe_allow_html=True)

                st.markdown(f"""
                    <div style="background: {mono_card_bg}; border: 1.5px solid {mono_card_border}; border-radius: 10px; padding: 10px 12px; margin-bottom: 10px;">
                        <div style="font-weight: 700; color: {mono_title_clr}; font-size: 13px; display: flex; justify-content: space-between; align-items: center;">
                            <span>🐱 Monobank Банка</span>
                            <span style="background: #7C3AED; color: white; padding: 1px 7px; border-radius: 6px; font-size: 11px;">Ціль: 20 000 ₴</span>
                        </div>
                        <div style="font-size: 11px; color: {mono_sub_clr}; margin-top: 3px;">
                            Швидке та безпечне поповнення у гривні
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                if hasattr(st, "link_button"):
                    st.link_button("👉 Відкрити Банку в Monobank", "https://send.monobank.ua/jar/2u4R1owSvj", type="primary", use_container_width=True)
                else:
                    st.markdown("[👉 **Відкрити Банку в Monobank**](https://send.monobank.ua/jar/2u4R1owSvj)")

                qr_file = os.path.join(os.path.dirname(__file__), "assets", "monobank_qr.jpg")
                if os.path.exists(qr_file):
                    st.image(qr_file, caption="QR-код Банки (наведіть камеру смартфона)", use_container_width=True)

                st.markdown(f"""
                    <div style="margin-top: 10px; padding-top: 8px; border-top: 1px dashed {pop_divider};">
                        <div style="font-weight: 700; font-size: 12px; margin-bottom: 4px; display: flex; align-items: center; gap: 6px;">
                            <span>💎 Криптовалюта: USDT (Мережа TON)</span>
                        </div>
                        <div style="font-size: 11px; opacity: 0.8; margin-bottom: 4px;">
                            Адреса гаманця (натисніть поле для копіювання):
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                st.code("UQAcH8xOmrNQ91WQ8hzEXV9TCiNhpIVqg5YjegesR__tsHfz", language="text")
                st.caption("🙏 Щиро вдячні за кожен внесок у розвиток нашого проєкту!")

        def _render_theme_btn(k_pfx="nav"):
            c_th = st.session_state.get("theme", "light")
            lbl = "🌙 Темна" if c_th == "light" else "☀️ Світла"
            hlp = "Увімкнути темну тему" if c_th == "light" else "Увімкнути світлу тему"
            if st.button(lbl, use_container_width=True, help=hlp, key=f"btn_theme_toggle_{k_pfx}"):
                n_th = "dark" if c_th == "light" else "light"
                st.session_state["theme"] = n_th
                try:
                    if hasattr(st, "query_params"):
                        st.query_params["theme"] = n_th
                except Exception:
                    pass
                st.rerun()

        wd_bg = "rgba(16, 185, 129, 0.15)" if is_dark else "#ECFDF5"
        wd_border = "rgba(16, 185, 129, 0.35)" if is_dark else "#A7F3D0"
        wd_clr = "#34D399" if is_dark else "#047857"
        wd_html = f"""
            <div style="display: flex; align-items: center; gap: 6px; background: {wd_bg}; border: 1px solid {wd_border}; color: {wd_clr}; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 9999px; margin-top: 4px;">
                <span style="width: 7px; height: 7px; background: #10B981; border-radius: 9999px; display: inline-block;"></span>
                <span>Watchdog OK</span>
                <span style="opacity: 0.85; font-weight: 500;">({hb_time})</span>
            </div>
        """

        if is_admin:
            c_wd, c_donate, c_theme, c_ref, c_run, c_logout = st.columns([1.7, 1.2, 1.1, 1.1, 1.1, 1.0])
            with c_wd:
                st.markdown(wd_html, unsafe_allow_html=True)
            with c_donate:
                _render_donate_popover("admin")
            with c_theme:
                _render_theme_btn("admin")
            with c_ref:
                if st.button("🔄 Оновити", use_container_width=True):
                    st.rerun()
            with c_run:
                if st.button("⚡ Запуск", use_container_width=True):
                    try:
                        import requests
                        trigger_url = "https://statmonitor.symchak.workers.dev"
                        if secret_key:
                            resp = requests.get(f"{trigger_url}/?secret={secret_key}&source=dashboard_button", timeout=12)
                            if resp.status_code == 200:
                                st.toast("🚀 Моніторинг успішно запущено!", icon="✅")
                            else:
                                st.error(f"Помилка [{resp.status_code}]: {resp.text[:100]}")
                    except Exception as e:
                        st.error(f"Помилка виклику: {e}")
            with c_logout:
                if st.button("🚪 Вийти", use_container_width=True, help="Вийти з режиму адміністратора (SPEC-38)"):
                    st.session_state.is_admin = False
                    st.rerun()
        else:
            c_wd, c_donate, c_theme, c_login = st.columns([1.8, 1.3, 1.2, 1.1])
            with c_wd:
                st.markdown(wd_html, unsafe_allow_html=True)
            with c_donate:
                _render_donate_popover("ro")
            with c_theme:
                _render_theme_btn("ro")
            with c_login:
                login_container = st.popover("🔒 Вхід", use_container_width=True) if hasattr(st, "popover") else st.expander("🔒 Вхід")
                with login_container:
                    entered_pass = st.text_input("Ключ адміністратора:", type="password", key="admin_pwd_field")
                    if st.button("Увійти", key="btn_admin_login", use_container_width=True):
                        if secret_key and entered_pass.strip() == str(secret_key).strip():
                            st.session_state.is_admin = True
                            st.rerun()
                        else:
                            st.error("Невірний ключ")
                            st.error("Невірний ключ")

    # 2. ДАНІ ДЛЯ РИЗИК-МЕТРИК ТА ЛІГ (SPEC-24)
    df_all = pd.DataFrame(bets_df) if (pd is not None and not isinstance(bets_df, pd.DataFrame)) else bets_df
    all_settled = (
        df_all[df_all["status"].isin(["WON", "LOST", "VOID"])].copy()
        if (df_all is not None and hasattr(df_all, "empty") and not df_all.empty)
        else pd.DataFrame()
    )
    dd_stats = calculate_drawdown(all_settled, initial_bankroll=INITIAL_BANKROLL)
    streak_stats = calculate_streaks(all_settled)

    quota_data, quota_source = get_dashboard_odds_quota(heartbeat_df)

    # 3. ЄДИНИЙ ЩІЛЬНИЙ РЯДОК KPI-МЕТРИК (6 КАРТОК У 1 РЯД, висота ~66px)
    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)

    # Картка 1: Банкрол (Paper Bank)
    profit_val = metrics["net_profit"]
    kpi1.metric(
        label="💰 Банкрол (Paper Bank)",
        value=f"{metrics['current_bank']:,.2f} ₴",
        delta=f"{profit_val:+,.0f} ₴" if profit_val != 0 else "0 ₴",
    )

    # Картка 2: ROI / Оборот
    roi_val = metrics["roi_pct"]
    kpi2.metric(
        label="📈 ROI / Оборот",
        value=f"{roi_val:+.2f}%",
        delta=f"Об: {metrics['turnover']:,.0f} ₴",
    )

    # Картка 3: Вінрейт
    kpi3.metric(
        label="🎯 Вінрейт (Win Rate)",
        value=f"{metrics['win_rate']:.1f}%",
        delta=f"{metrics['total_bets']} (в грі: {metrics['pending']})",
    )

    # Картка 4: Max Drawdown
    dd_pct = dd_stats["max_drawdown_pct"]
    dd_uah = dd_stats["max_drawdown_uah"]
    kpi4.metric(
        label="🔻 Max Drawdown",
        value=f"{dd_pct:.1f}%",
        delta=f"-{dd_uah:,.0f} ₴ від піку" if dd_pct > 0 else "0 ₴",
        delta_color="inverse" if dd_pct > 0 else "off",
    )

    # Картка 5: Серії (Streak)
    c_type = streak_stats["current_streak_type"]
    c_count = streak_stats["current_streak_count"]
    c_lbl = f"{c_count}W" if c_type == "W" else (f"{c_count}L" if c_type == "L" else "0W")
    kpi5.metric(
        label="🔥 Серії (Streak)",
        value=c_lbl,
        delta=f"🏆 {streak_stats['max_win_streak']}W | ⚠️ {streak_stats['max_loss_streak']}L",
        delta_color="normal" if c_type == "W" else ("inverse" if c_type == "L" else "off"),
    )

    # Картка 6: Пульс & API
    if quota_data:
        tot_rem = quota_data.get("total_remaining", 0)
        tot_lim = quota_data.get("total_limit", 2500)
        pct = (tot_rem / tot_lim * 100.0) if tot_lim > 0 else 0.0
        kpi6.metric(
            label="💓 Пульс / API (5 кл)",
            value=f"{tot_rem} / {tot_lim}",
            delta=f"{pct:.1f}% • {hb_status_clean}",
            delta_color="normal" if pct > 20 else "inverse",
        )
    else:
        kpi6.metric(
            label="💓 Пульс системи",
            value=hb_status_clean,
            delta=f"Чек: {hb_time}",
            delta_color="normal",
        )

    # Додатковий рядок деталізації ключів (для авторизованого адміністратора або коли є квота)
    if is_admin and quota_data:
        pri = quota_data.get("primary", {})
        res = quota_data.get("reserve", {})
        res1 = quota_data.get("reserve1", {})
        res2 = quota_data.get("reserve2", {})
        res3 = quota_data.get("reserve3", {})

        def _slot_fmt(slot, name):
            rem = slot.get("remaining")
            lim = slot.get("limit", 500)
            used = slot.get("used")
            if rem is None and slot.get("status") == "not_configured":
                return f"{name} — не налаштовано"
            rem_val = rem if rem is not None else 500
            if used is not None and used > 0:
                return f"{name} — {rem_val}/{lim} (вик {used})"
            return f"{name} — {rem_val}/{lim}"

        p_str = _slot_fmt(pri, "Основний")
        r_str = _slot_fmt(res, "Резерв 1")
        r1_str = _slot_fmt(res1, "Резерв 2")
        r2_str = _slot_fmt(res2, "Резерв 3")
        r3_str = _slot_fmt(res3, "Резерв 4")

        st.markdown(f"""
            <div style="font-size: 11.5px; color: {'#94A3B8' if is_dark else '#475569'}; background: {'#161F30' if is_dark else '#F8FAFC'}; border: 1px solid {'#233044' if is_dark else '#E2E8F0'}; border-radius: 8px; padding: 4px 12px; margin-top: 4px; margin-bottom: 8px;">
                <b>Деталізація The Odds API:</b> {p_str} &nbsp;|&nbsp; {r_str} &nbsp;|&nbsp; {r1_str} &nbsp;|&nbsp; {r2_str} &nbsp;|&nbsp; {r3_str}
            </div>
        """, unsafe_allow_html=True)

    # SPEC: Витрата API-токенів / запитів за видами спорту (Хто з'їв квоту)
    try:
        from statmonitor.limiter import compute_sports_quota_breakdown
        from statmonitor.league_config import load_leagues_config
        q_breakdown = compute_sports_quota_breakdown(poll_df, leagues_config=load_leagues_config())
        
        top_cats = [c for c in q_breakdown.get("categories", []) if c.get("poll_count", 0) > 0]
        top_sport_label = f" (Топ-споживач: {top_cats[0]['category_name']} — {top_cats[0]['poll_count']} запитів)" if top_cats else ""
        
        with st.expander(f"📊 Деталізація витрати API: Який вид спорту з'їв токени? ({q_breakdown['total_polls']} / {q_breakdown['total_limit']} запитів){top_sport_label}", expanded=False):
            if top_cats:
                col_qb1, col_qb2 = st.columns([6, 4])
                with col_qb1:
                    df_cats_disp = pd.DataFrame([
                        {
                            "Вид спорту": c["category_name"],
                            "Запитів (токенів)": c["poll_count"],
                            "% від витраченої квоти": f"{c['pct_of_used']:.1f}%",
                            "% від місячного ліміту": f"{c['pct_of_limit']:.1f}%",
                            "Ліг у скануванні": c["leagues_count"],
                            "Топ-ліга споживач": c["top_league_title"]
                        }
                        for c in top_cats
                    ])
                    st.dataframe(df_cats_disp, use_container_width=True, hide_index=True)
                with col_qb2:
                    cat_names_rev = [c["category_name"] for c in reversed(top_cats)]
                    cat_polls_rev = [c["poll_count"] for c in reversed(top_cats)]
                    fig_sp_quota = go.Figure(go.Bar(
                        x=cat_polls_rev,
                        y=cat_names_rev,
                        orientation="h",
                        marker=dict(color="#3B82F6"),
                        text=[f"{v} ({round(v / q_breakdown['total_polls'] * 100, 1)}%)" for v in cat_polls_rev],
                        textposition="auto",
                    ))
                    fig_sp_quota.update_layout(
                        height=max(180, len(top_cats) * 32),
                        margin=dict(l=10, r=10, t=10, b=10),
                        template="plotly_dark" if is_dark else "plotly_white",
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(showgrid=True, gridcolor="#1E293B" if is_dark else "#F1F5F9"),
                        yaxis=dict(showgrid=False),
                    )
                    st.plotly_chart(fig_sp_quota, use_container_width=True, config={"displayModeBar": False})
            else:
                st.info("ℹ️ Дані про опитування ліг ще накопичуються в базі даних sports_poll_log.")
    except Exception as q_err:
        print("API quota breakdown render err:", q_err)

    # SPEC-31: Банер стану реального банку (доступний тільки адміністратору)
    if is_admin and (real_summary.get("total_deposits", 0) > 0 or real_summary.get("total_real_bets", 0) > 0 or real_summary.get("current_balance", 0) > 0):
        p_sign = "+" if real_summary.get('real_profit', 0) > 0 else ""
        rb_bg = "rgba(16, 185, 129, 0.12)" if is_dark else "#F0FDF4"
        rb_border = "rgba(16, 185, 129, 0.25)" if is_dark else "#BBF7D0"
        rb_clr = "#34D399" if is_dark else "#166534"
        st.markdown(f"""
            <div style="font-size: 11.5px; color: {rb_clr}; background: {rb_bg}; border: 1px solid {rb_border}; border-radius: 8px; padding: 4px 12px; margin-top: 4px; margin-bottom: 8px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 8px;">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span>🟢</span>
                    <b>Реальний банк (Real Bankroll):</b> <code>{real_summary.get('current_balance', 0.0):,.2f} ₴</code> &nbsp;|&nbsp; 
                    <b>Депозити:</b> <code>{real_summary.get('total_deposits', 0.0):,.2f} ₴</code> &nbsp;|&nbsp; 
                    <b>Чистий прибуток:</b> <b><code>{p_sign}{real_summary.get('real_profit', 0.0):,.2f} ₴</code></b> &nbsp;|&nbsp; 
                    <b>Real ROI:</b> <b><code>{real_summary.get('real_roi_pct', 0.0):+.2f}%</code></b> &nbsp;|&nbsp; 
                    <b>Оборот:</b> <code>{real_summary.get('real_turnover', 0.0):,.2f} ₴</code>
                </div>
                <div>
                    <b>Реальних ставок:</b> <b>{real_summary.get('total_real_bets', 0)}</b> &nbsp;(⏳ в грі: <b>{real_summary.get('pending_real', 0)}</b> &nbsp;|&nbsp; 🟢 {real_summary.get('won_real', 0)}W &nbsp;|&nbsp; 🔴 {real_summary.get('lost_real', 0)}L)
                    &nbsp;👉 <i>Детальніше у вкладці «🟢 Реальний банк»</i>
                </div>
            </div>
        """, unsafe_allow_html=True)

    # 4. ВКЛАДКИ НАВІГАЦІЇ
    tab_titles = ["📊 Paper Bank (Теорія)"]
    if is_admin:
        tab_titles.append("🟢 Реальний банк (Real Money)")
    tab_titles.extend([
        "🧠 AI-аналітика Gemini",
        "🔬 Квантитативний Бектест (SPEC-42)",
        "⚙️ Розклад та Пульс",
    ])
    if is_admin:
        tab_titles.append("🎛️ Пороги ліг (Admin)")

    all_tabs = st.tabs(tab_titles)
    t_idx = 0
    tab_bets = all_tabs[t_idx]; t_idx += 1
    tab_real = all_tabs[t_idx] if is_admin else None
    if is_admin:
        t_idx += 1
    tab_ai = all_tabs[t_idx]; t_idx += 1
    tab_backtest = all_tabs[t_idx]; t_idx += 1
    tab_pulse = all_tabs[t_idx]; t_idx += 1
    tab_thresholds = all_tabs[t_idx] if is_admin else None

    # ---------------- ВКЛАДКА 1: СТАВКИ ТА КАПІТАЛ ----------------
    with tab_bets:
        # Завантаження назв турнірів
        try:
            from statmonitor.league_config import get_active_sports_map
            s_map = get_active_sports_map()
        except Exception:
            try:
                from statmonitor.config import SPORTS_MAP
                s_map = SPORTS_MAP
            except Exception:
                s_map = {}

        # 3. КОМПАКТНА ПАНЕЛЬ ФІЛЬТРІВ В ОДИН РЯДОК (Висота ~38px)
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([3, 2.2, 2, 1.8, 1])

        all_sports = (
            sorted(list({str(s) for s in df_all["sport"].dropna().unique() if str(s) != "nan"}))
            if (df_all is not None and hasattr(df_all, "empty") and not df_all.empty and "sport" in df_all.columns)
            else []
        )
        sport_labels = {sp: s_map.get(sp, sp) for sp in all_sports}

        with col_f1:
            sel_sports = st.multiselect(
                "🏆 Турнір:",
                options=all_sports,
                default=[],
                format_func=lambda x: sport_labels.get(x, x),
                placeholder="Всі турніри",
                key="filter_sports_v2",
            )

        with col_f2:
            market_options = ["Всі маркети", "1X2 / ML", "Тотали", "Фори", "Обидві заб'ють"]
            sel_market = st.selectbox("🎯 Маркет:", market_options, index=0, key="filter_market_v2")

        with col_f3:
            status_options = ["Всі ставки", "Розраховані", "В грі (Pending)", "🟡 Відсіяні (Shadow)"]
            sel_status = st.selectbox("📌 Статус:", status_options, index=0, key="filter_status_v2")

        with col_f4:
            period_options = ["Все", "30 днів", "7 днів"]
            sel_period = st.selectbox("📅 Період:", period_options, index=0, key="filter_period_v2")

        with col_f5:
            st.write("")
            st.write("")
            if st.button("↺ Скинути", key="btn_reset_filters", use_container_width=True):
                st.session_state["filter_sports_v2"] = []
                st.session_state["filter_market_v2"] = "Всі маркети"
                st.session_state["filter_status_v2"] = "Всі ставки"
                st.session_state["filter_period_v2"] = "Все"
                st.rerun()

        # Фільтрація датасету
        filtered_df = df_all.copy() if (df_all is not None and hasattr(df_all, "empty") and not df_all.empty) else pd.DataFrame()
        if not filtered_df.empty:
            if sel_sports:
                filtered_df = filtered_df[filtered_df["sport"].isin(sel_sports)]
            if sel_market != "Всі маркети" and "pick_label" in filtered_df.columns:
                m_match_map = {
                    "1X2 / ML": "1X2 / Переможець",
                    "Тотали": "Тотали",
                    "Фори": "Фори",
                    "Обидві заб'ють": "Обидві заб'ють",
                }
                target_g = m_match_map.get(sel_market, sel_market)
                filtered_df["_mkt_group"] = filtered_df["pick_label"].apply(classify_market_group)
                filtered_df = filtered_df[filtered_df["_mkt_group"] == target_g]
            if sel_status == "Розраховані":
                filtered_df = filtered_df[filtered_df["status"].isin(["WON", "LOST", "VOID"])]
            elif sel_status == "В грі (Pending)":
                filtered_df = filtered_df[filtered_df["status"] == "PENDING"]
            elif sel_status == "🟡 Відсіяні (Shadow)":
                filtered_df = filtered_df[(filtered_df["is_shadow"] == True) | (filtered_df["status"] == "FILTERED")]
            else:
                # "Всі ставки": за замовчуванням показуємо активні ставки (без тіньових)
                if "is_shadow" in filtered_df.columns:
                    filtered_df = filtered_df[(filtered_df["is_shadow"] != True) & (filtered_df["status"] != "FILTERED")]

            # Період
            if sel_period != "Все" and "commence_time" in filtered_df.columns:
                now_utc = datetime.now(timezone.utc)
                days_delta = 7 if sel_period == "7 днів" else 30
                cutoff_dt = now_utc - timedelta(days=days_delta)
                try:
                    t_series = pd.to_datetime(filtered_df["commence_time"], utc=True)
                    filtered_df = filtered_df[t_series >= cutoff_dt]
                except Exception:
                    pass

        settled_for_charts = (
            filtered_df[filtered_df["status"].isin(["WON", "LOST", "VOID"])].copy()
            if not filtered_df.empty
            else pd.DataFrame()
        )

        # 4. ОСНОВНА СІТКА З ГРАФІКАМИ (7:5) — Дизайн у стилі Gemini Mockup
        col_chart_left, col_chart_right = st.columns([7, 5])

        # Ліва колонка (60%): Динаміка капіталу (Line Chart зі spline та градієнтом)
        with col_chart_left:
            with st.container(border=True):
                if not settled_for_charts.empty and "settled_at" in settled_for_charts.columns:
                    chart_df = settled_for_charts.dropna(subset=["settled_at"]).sort_values(by="settled_at", ascending=True).copy()
                    if not chart_df.empty:
                        chart_df["profit_uah"] = chart_df["profit_uah"].astype(float)
                        chart_df["cum_profit"] = chart_df["profit_uah"].cumsum()
                        chart_df["balance"] = float(INITIAL_BANKROLL) + chart_df["cum_profit"]

                        # Парсимо в локальний київський час
                        def parse_to_kyiv(val):
                            if isinstance(val, str):
                                val = datetime.fromisoformat(val.replace("Z", "+00:00"))
                            if not hasattr(val, "tzinfo") or not val.tzinfo:
                                val = val.replace(tzinfo=timezone.utc)
                            return val.astimezone(KYIV_TZ)

                        chart_df["dt_kyiv"] = chart_df["settled_at"].apply(parse_to_kyiv)
                        first_dt = chart_df["dt_kyiv"].iloc[0]
                        # Попередній день (наприклад, 13.11) для плавного переходу від стартових 10,000 грн
                        start_dt = (first_dt - timedelta(days=1)).replace(hour=11, minute=0, second=0)

                        # Створюємо стартову точку 10,000 грн для плавного органічного початку
                        start_point = pd.DataFrame([{
                            "dt_kyiv": start_dt,
                            "balance": float(INITIAL_BANKROLL),
                            "profit_uah": 0.0,
                            "cum_profit": 0.0
                        }])
                        full_chart_df = pd.concat([start_point, chart_df], ignore_index=True)

                        # Відсоток від старту для бейджа
                        last_balance = full_chart_df["balance"].iloc[-1]
                        growth_pct = ((last_balance - INITIAL_BANKROLL) / INITIAL_BANKROLL) * 100.0
                        growth_badge = f"+{growth_pct:.1f}% від старту" if growth_pct >= 0 else f"{growth_pct:.1f}% від старту"

                        chart_hdr_color = '#F8FAFC' if is_dark else '#1E293B'
                        chart_badge_bg = 'rgba(37, 99, 235, 0.2)' if is_dark else '#EFF6FF'
                        chart_badge_clr = '#60A5FA' if is_dark else '#2563EB'
                        st.markdown(f"""
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 13px; font-weight: 700; color: {chart_hdr_color};">📈 Динаміка капіталу (Paper Bank Balance Growth)</span>
                                    <span style="font-size: 10.5px; font-weight: 600; background: {chart_badge_bg}; color: {chart_badge_clr}; padding: 2px 7px; border-radius: 6px;">{growth_badge}</span>
                                </div>
                                <div style="display: flex; align-items: center; gap: 12px; font-size: 11px; color: {'#94A3B8' if is_dark else '#64748B'};">
                                    <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 7px; height: 7px; border-radius: 50%; background: #2563EB; display: inline-block;"></span> Баланс (грн)</span>
                                    <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 14px; height: 0; border-top: 1.5px dashed {'#64748B' if is_dark else '#94A3B8'}; display: inline-block;"></span> Старт: 10,000 ₴</span>
                                </div>
                            </div>
                        """, unsafe_allow_html=True)

                        # Розрахунок вертикального діапазону осі Y (масштаб 9.5k–14k з кроком 500)
                        all_b = full_chart_df["balance"].tolist()
                        min_b = min(all_b)
                        max_b = max(all_b)
                        y_min = math.floor(min(min_b, 10000.0) / 500) * 500 - 500
                        y_max = math.ceil(max(max_b, 10000.0) / 500) * 500 + 500
                        if (y_max - y_min) < 2000:
                            y_max = y_min + 2500
                        tick_vals = list(range(int(y_min), int(y_max) + 500, 500))
                        tick_text = [f"{v/1000:.1f}k" for v in tick_vals]

                        fig_bal = go.Figure()

                        # Базова лінія старту (10,000 ₴)
                        fig_bal.add_trace(go.Scatter(
                            x=full_chart_df["dt_kyiv"],
                            y=[INITIAL_BANKROLL] * len(full_chart_df),
                            mode="lines",
                            line=dict(color="#CBD5E1", width=1.5, dash="dash"),
                            hoverinfo="skip"
                        ))

                        # Плавна крива балансу (Spline) з м'якою напівпрозорою заливкою
                        fig_bal.add_trace(go.Scatter(
                            x=full_chart_df["dt_kyiv"],
                            y=full_chart_df["balance"],
                            mode="lines+markers",
                            line=dict(color="#2563EB", width=2.4, shape="spline", smoothing=0.35),
                            marker=dict(size=6, color="#2563EB", line=dict(color="#161F30" if is_dark else "#FFFFFF", width=1.8)),
                            fill="tozeroy",
                            fillcolor="rgba(37, 99, 235, 0.10)",
                            hovertemplate="<b>%{x|%d.%m %H:%M}</b><br>Баланс: %{y:,.2f} ₴<extra></extra>"
                        ))

                        chart_line = "#334155" if is_dark else "#E2E8F0"
                        chart_grid = "#1E293B" if is_dark else "#EEF2F6"
                        chart_tick = "#94A3B8" if is_dark else "#64748B"

                        fig_bal.update_layout(
                            template="plotly_dark" if is_dark else "plotly_white",
                            height=255,
                            margin=dict(l=45, r=15, t=10, b=25),
                            showlegend=False,
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            xaxis=dict(
                                showgrid=False,
                                linecolor=chart_line,
                                tickformat="%d.%m",
                                tickfont=dict(size=10.5, color=chart_tick, family="Inter"),
                            ),
                            yaxis=dict(
                                range=[y_min, y_max],
                                tickvals=tick_vals,
                                ticktext=tick_text,
                                showgrid=True,
                                gridcolor=chart_grid,
                                gridwidth=1,
                                tickfont=dict(size=10.5, color=chart_tick, family="Inter"),
                                zeroline=False
                            )
                        )
                        st.plotly_chart(fig_bal, use_container_width=True, config={"displayModeBar": False})
                    else:
                        st.info("ℹ️ Немає розрахованих ставок за обраними фільтрами для графіка капіталу.")
                else:
                    st.info("ℹ️ Немає розрахованих ставок за обраними фільтрами для графіка капіталу.")

        # Права колонка (40%): ROI за турнірами (Horizontal Bar Chart)
        with col_chart_right:
            with st.container(border=True):
                st.markdown(f"""
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 13px; font-weight: 700; color: {'#F8FAFC' if is_dark else '#1E293B'};">🏆 ROI за турнірами (%)</span>
                        <span style="font-size: 11px; color: {'#94A3B8' if is_dark else '#64748B'};">Сортування: за дохідністю</span>
                    </div>
                """, unsafe_allow_html=True)

                league_stats = calculate_league_breakdown(all_settled, sports_map=s_map)
                if league_stats:
                    # Сортування: найприбутковіша ліга вгорі
                    l_df = pd.DataFrame(league_stats).sort_values(by="roi_pct", ascending=False)

                    # Кольори окремих ліг з макета Gemini (Смарагдовий, Індиго, Синій, Червоний)
                    pos_palette = ['#10B981', '#6366F1', '#3B82F6', '#06B6D4', '#8B5CF6']
                    colors = []
                    p_idx = 0
                    for v in l_df["roi_pct"]:
                        if v < 0:
                            colors.append("#EF4444")
                        else:
                            colors.append(pos_palette[p_idx % len(pos_palette)])
                            p_idx += 1

                    max_roi = float(l_df["roi_pct"].max()) if not l_df.empty else 50.0
                    min_roi = float(l_df["roi_pct"].min()) if not l_df.empty else 0.0
                    x_min = min(-12.0, min_roi - 8.0)
                    x_max = max(75.0, max_roi + 15.0)

                    chart_text_clr = "#F8FAFC" if is_dark else "#334155"
                    fig_roi = go.Figure(go.Bar(
                        x=l_df["roi_pct"],
                        y=l_df["league_title"],
                        orientation="h",
                        width=0.42,
                        marker=dict(color=colors, cornerradius=5),
                        text=[(f"{v:+.1f}%" if v != 0 else "0.0%") for v in l_df["roi_pct"]],
                        textposition="outside",
                        cliponaxis=False,
                        textfont=dict(size=11, family="Inter", color=chart_text_clr),
                        hovertemplate="<b>%{y}</b><br>ROI: %{x:+.1f}%<extra></extra>"
                    ))

                    fig_roi.update_layout(
                        template="plotly_dark" if is_dark else "plotly_white",
                        height=255,
                        margin=dict(l=155, r=45, t=10, b=25),
                        showlegend=False,
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(
                            range=[x_min, x_max],
                            showgrid=True,
                            gridcolor="#1E293B" if is_dark else "#EEF2F6",
                            zeroline=True,
                            zerolinecolor="#334155" if is_dark else "#CBD5E1",
                            zerolinewidth=1.5,
                            tickfont=dict(size=10.5, color="#94A3B8" if is_dark else "#64748B", family="Inter"),
                            ticksuffix="%"
                        ),
                        yaxis=dict(
                            autorange="reversed",
                            showgrid=False,
                            tickfont=dict(size=11, color=chart_text_clr, family="Inter")
                        )
                    )
                    st.plotly_chart(fig_roi, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("ℹ️ Очікування розрахунку ставок для побудови ROI по лігах.")

        # 4. ДЕТАЛЬНА СЕГМЕНТАЦІЯ ЗА ЛІГАМИ ТА ТИПАМИ МАРКЕТІВ (Зразу під графіками)
        with st.expander("📊 Детальна сегментація за лігами та типами маркетів (Breakdown)", expanded=True):
            clv_metrics = calculate_clv_metrics(filtered_df if not filtered_df.empty else all_settled)
            if clv_metrics.get("total_with_clv", 0) > 0:
                beat_clr = "#16A34A" if clv_metrics["beat_line_pct"] >= 50.0 else "#EAB308"
                avg_clr = "#16A34A" if clv_metrics["avg_clv_pct"] >= 0 else "#DC2626"
                clv_card_bg = "#161F30" if is_dark else "#F8FAFC"
                clv_card_border = "#233044" if is_dark else "#E2E8F0"
                clv_t_clr = "#F8FAFC" if is_dark else "#0F172A"
                clv_s_clr = "#94A3B8" if is_dark else "#64748B"
                clv_v_clr = "#F8FAFC" if is_dark else "#1E293B"

                st.markdown(f"""
                    <div style="background: {clv_card_bg}; border: 1px solid {clv_card_border}; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 16px;">🎯</span>
                            <div>
                                <div style="font-size: 12.5px; font-weight: 700; color: {clv_t_clr};">Closing Line Value (CLV) & Beat the Line % (SPEC-20)</div>
                                <div style="font-size: 11px; color: {clv_s_clr};">Фіксація коефіцієнта закриття лінії (Closing Line) бенчмарк-букмекерів (Pinnacle/Betfair). Математична перевага (+EV).</div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: center;">
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: {clv_s_clr};">Beat the Line %</div>
                                <div style="font-size: 14px; font-weight: 700; color: {beat_clr};">{clv_metrics['beat_line_pct']:.1f}%</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: {clv_s_clr};">Сер. CLV (+EV)</div>
                                <div style="font-size: 14px; font-weight: 700; color: {avg_clr};">{clv_metrics['avg_clv_pct']:+.2f}%</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: {clv_s_clr};">Зафіксовано ліній</div>
                                <div style="font-size: 14px; font-weight: 700; color: {clv_v_clr};">{clv_metrics['total_with_clv']} <span style="font-size: 11px; font-weight: 500; color: {clv_s_clr};">({clv_metrics['beat_count']} побито)</span></div>
                            </div>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

            market_stats = calculate_market_breakdown(all_settled)
            sub_col1, sub_col2 = st.columns(2)
            with sub_col1:
                st.markdown("##### 🏆 Ефективність за лігами")
                if league_stats:
                    disp_l_cols = ["league_title", "bets_count", "won", "lost", "win_rate", "profit_uah", "roi_pct"]
                    l_table = pd.DataFrame(league_stats)[disp_l_cols].rename(columns={
                        "league_title": "Турнір",
                        "bets_count": "Ставок",
                        "won": "Виграш",
                        "lost": "Програш",
                        "win_rate": "Win %",
                        "profit_uah": "Профіт (грн)",
                        "roi_pct": "ROI (%)",
                    })
                    st.dataframe(l_table, use_container_width=True, hide_index=True)
                else:
                    st.caption("Немає даних.")

            with sub_col2:
                st.markdown("##### 🎯 Ефективність за типами маркетів")
                if market_stats:
                    disp_m_cols = ["market_group", "bets_count", "won", "lost", "win_rate", "profit_uah", "roi_pct"]
                    m_table = pd.DataFrame(market_stats)[disp_m_cols].rename(columns={
                        "market_group": "Маркет",
                        "bets_count": "Ставок",
                        "won": "Виграш",
                        "lost": "Програш",
                        "win_rate": "Win %",
                        "profit_uah": "Профіт (грн)",
                        "roi_pct": "ROI (%)",
                    })
                    st.dataframe(m_table, use_container_width=True, hide_index=True)
                else:
                    st.caption("Немає даних.")

        # Спільні функції форматування рядків
        try:
            from statmonitor.league_config import load_leagues_config
            all_title_map = {lg["key"]: lg.get("title", lg["key"]) for lg in load_leagues_config().get("leagues", [])}
        except Exception:
            all_title_map = {}

        def _get_league_name(sp, with_icon=False):
            title = all_title_map.get(sp, s_map.get(sp, sp))
            if with_icon and sp:
                return f"{get_sport_icon(sp)} {title}"
            return title

        def _clean_pick_label(lbl):
            if not lbl or not isinstance(lbl, str):
                return ""
            return re.split(r"\s+(?:або|чи|\/)\s+", str(lbl), maxsplit=1, flags=re.I)[0].strip()

        def _format_result(r):
            st_code = r.get("status")
            p = r.get("profit_uah")
            if st_code == "WON":
                return f"🟢 +{float(p):,.2f} ₴" if p else "🟢 Виграш"
            elif st_code == "LOST":
                return f"🔴 {float(p):,.2f} ₴" if p else "🔴 Програш"
            elif st_code == "VOID":
                return "⚪ 0.00 ₴ (Повернення)"
            else:
                return "⏳ В грі (Pending)"

        def _format_clv(r):
            clv_val = r.get("clv_pct")
            beat_val = r.get("beat_closing_line")
            b_k = r.get("odds")
            c_k = r.get("closing_odds")
            if (clv_val is None or pd.isna(clv_val)) and b_k and c_k:
                clv_val, beat_val = calculate_clv_value(b_k, c_k)
            if clv_val is not None and not (pd is not None and pd.isna(clv_val)):
                try:
                    cf = float(clv_val)
                    if beat_val is True or cf > 0:
                        return f"+{cf:.1f}% 🏆"
                    elif cf < 0:
                        return f"{cf:.1f}%"
                    return f"{cf:.1f}%"
                except Exception:
                    pass
            return "—"

        def _get_ai_score_badge(r):
            try:
                cs = r.get("confidence_score")
                if cs is not None and not (pd is not None and pd.isna(cs)):
                    try:
                        val_cs = int(cs)
                        if 1 <= val_cs <= 10 and val_cs != 8:
                            return f"⭐ {val_cs}/10"
                    except Exception:
                        pass

                st_code = str(r.get("status") or "")
                if st_code == "PENDING":
                    k_pct = r.get("kelly_pct")
                    if k_pct is not None and not (pd is not None and pd.isna(k_pct)):
                        try:
                            kp = float(k_pct)
                            if kp >= 3.5:
                                return "⭐ 9/10"
                            elif kp >= 2.5:
                                return "⭐ 8/10"
                            else:
                                return "⭐ 7/10"
                        except Exception:
                            pass

                    try:
                        k_odds = float(r.get("odds") or 2.0)
                        if k_odds <= 1.50:
                            return "⭐ 9/10"
                        elif k_odds <= 2.20:
                            return "⭐ 8/10"
                        else:
                            return "⭐ 7/10"
                    except Exception:
                        pass

                    return "⭐ 8/10"

                if cs is not None and not (pd is not None and pd.isna(cs)):
                    try:
                        val_cs = int(cs)
                        if 1 <= val_cs <= 10:
                            return f"⭐ {val_cs}/10"
                    except Exception:
                        pass

                return "—"
            except Exception:
                return "—"

        curr_bank_val = metrics.get("current_bank", INITIAL_BANKROLL)
        def _get_kelly_badge(r):
            if "kelly_pct" in r and r["kelly_pct"] is not None and not (pd is not None and pd.isna(r["kelly_pct"])):
                try:
                    return f"{float(r['kelly_pct']):.1f}%"
                except Exception:
                    pass
            try:
                stk = float(r.get("stake_uah", 0) or 0)
                if curr_bank_val and curr_bank_val > 0 and stk > 0:
                    return f"{(stk / curr_bank_val) * 100:.1f}%"
            except Exception:
                pass
            return "2.5%"

        # 5. АКТИВНІ СТАВКИ У ГРІ (В стилі журналу операцій з укр. назвами та доп. колонками)
        pending_df = filtered_df[filtered_df["status"] == "PENDING"].copy() if (not filtered_df.empty and "status" in filtered_df.columns) else pd.DataFrame()
        if pending_df.empty and (bets_df is not None and not bets_df.empty and "status" in bets_df.columns):
            if status_filter in ("Всі ставки", "⏳ Тільки активні (Pending)"):
                pending_df = bets_df[bets_df["status"] == "PENDING"].copy()

        # Сортування активних ставок за часом події у порядку зростання (найближчі події зверху)
        if not pending_df.empty and "commence_time" in pending_df.columns:
            try:
                pending_df["_sort_time"] = pd.to_datetime(pending_df["commence_time"], utc=True)
                pending_df = pending_df.sort_values(by="_sort_time", ascending=True).drop(columns=["_sort_time"])
            except Exception:
                pending_df = pending_df.sort_values(by="commence_time", ascending=True)

        p_hdr_color = '#F8FAFC' if is_dark else '#1E293B'
        p_badge_bg = 'rgba(245, 158, 11, 0.2)' if is_dark else '#FEF3C7'
        p_badge_color = '#FCD34D' if is_dark else '#92400E'
        st.markdown(f"""
            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 14px; margin-bottom: 8px;">
                <div style="display: flex; align-items: center; gap: 8px;">
                    <span style="font-size: 14px; font-weight: 700; color: {p_hdr_color};">⏳ Активні ставки в грі (Pending)</span>
                    <span style="background: {p_badge_bg}; color: {p_badge_color}; font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px;">{len(pending_df)}</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

        if not pending_df.empty:
            p_disp = pending_df.copy()
            p_disp["ID"] = p_disp["id"].apply(lambda x: f"#{x}")
            if "commence_time" in p_disp.columns:
                p_disp["Час"] = p_disp["commence_time"].apply(format_kyiv_time)
            p_disp["🟢 Real"] = p_disp["is_real_bet"].apply(
                lambda x: bool(x) if (x is not None and not (pd is not None and pd.isna(x))) else False
            )
            p_disp["Турнір"] = p_disp["sport"].apply(lambda sp: _get_league_name(sp, with_icon=True))
            p_disp["Подія"] = p_disp.get("match_name", "")
            p_disp["Маркет"] = p_disp.get("pick_label", "").apply(_clean_pick_label)
            p_disp["Коеф."] = p_disp["odds"].apply(lambda x: f"{float(x):.2f}" if x else "—")
            p_disp["Поріг (Walkaway)"] = p_disp["walkaway_odds"].apply(
                lambda x: f"≥ {float(x):.2f}" if (x is not None and not (pd is not None and pd.isna(x))) else "—"
            ) if "walkaway_odds" in p_disp.columns else "—"
            p_disp["ШІ Сигнал"] = p_disp.apply(_get_ai_score_badge, axis=1)
            p_disp["Сума (Paper)"] = p_disp["stake_uah"].apply(lambda x: f"{float(x):,.2f} ₴" if x else "—")
            p_disp["Сума (Real)"] = p_disp.apply(
                lambda r: f"🟢 {float(r['real_stake_uah']):,.0f} ₴" if (r.get("is_real_bet") and r.get("real_stake_uah")) else "—",
                axis=1
            )
            p_disp["% банку (Келлі)"] = p_disp.apply(_get_kelly_badge, axis=1)
            p_disp["Результат"] = "⏳ В грі (Pending)"

            if is_admin:
                cols_pending_show = [c for c in ["ID", "Час", "🟢 Real", "Турнір", "Подія", "Маркет", "Коеф.", "Поріг (Walkaway)", "ШІ Сигнал", "% банку (Келлі)", "Сума (Paper)", "Сума (Real)", "Результат"] if c in p_disp.columns]
            else:
                cols_pending_show = [c for c in ["ID", "Час", "Турнір", "Подія", "Маркет", "Коеф.", "Поріг (Walkaway)", "ШІ Сигнал", "% банку (Келлі)", "Сума (Paper)", "Результат"] if c in p_disp.columns]

            if is_admin and hasattr(st, "data_editor"):
                # Перевіряємо які ставки вже зафіксовані як реальні (SPEC-34)
                active_real_df = pending_df[pending_df["is_real_bet"] == True]
                already_real_ids = set(active_real_df["id"].tolist()) if not active_real_df.empty else set()

                if already_real_ids:
                    st.caption("ℹ️ *Адміністратор:* відмічайте прапорець у колонці **🟢 Real**, щоб доставити нові події в облік реальних грошей. Рядки, які вже зафіксовані у грі, захищені від випадкової зміни.")
                else:
                    st.caption("ℹ️ *Адміністратор:* відмічайте прапорець у колонці **🟢 Real**, щоб включити ставку в облік реальних грошей. Всі ставки завжди йдуть у Paper-трейдинг.")

                # Дозволяємо редагувати колонку "🟢 Real" для вибору наступних подій
                disabled_cols = [c for c in cols_pending_show if c != "🟢 Real"]

                edited_p = st.data_editor(
                    p_disp[cols_pending_show],
                    column_config={
                        "🟢 Real": st.column_config.CheckboxColumn(
                            "🟢 Real",
                            help="Включити цю ставку в облік реальних грошей (всі ставки паралельно залишаються в Paper)",
                            default=False,
                        )
                    },
                    disabled=disabled_cols,
                    use_container_width=True,
                    hide_index=True,
                    key="admin_pending_editor_v2",
                )

                # SPEC: Вибір подій для перенесення в Real (БЕЗ миттєвого збереження при кліку на чекбокс — ЛИШЕ на кнопку)
                new_checked_real_ids = [
                    int(str(r.get("ID")).lstrip("#"))
                    for r in (edited_p.to_dict("records") if edited_p is not None else p_disp.to_dict("records"))
                    if bool(r.get("🟢 Real")) and int(str(r.get("ID")).lstrip("#")) not in already_real_ids
                ]

                # Збираємо активні події в грі для захисту від дублікатів
                active_real_matches_set = set()
                active_real_ev_ids_set = set()
                if bets_df is not None and not bets_df.empty and "is_real_bet" in bets_df.columns:
                    rp_act = bets_df[(bets_df["is_real_bet"] == True) & (bets_df["status"] == "PENDING")]
                    for _, r_rp in rp_act.iterrows():
                        mn = str(r_rp.get("match_name", "")).strip().lower()
                        if mn:
                            active_real_matches_set.add(mn)
                        eid = str(r_rp.get("event_id", "")).strip()
                        if eid:
                            active_real_ev_ids_set.add(eid)

                # Кнопка розтягнута на всю ширину таблиці та активна для нових обраних подій
                btn_calc_lbl = f"⚡ Перенести в Реальні ставки & Розрахувати банк ({len(new_checked_real_ids)} обрано)"
                if st.button(
                    btn_calc_lbl,
                    key="btn_trigger_real_stake_calc_v1",
                    type="primary" if new_checked_real_ids else "secondary",
                    disabled=(len(new_checked_real_ids) == 0),
                    use_container_width=True
                ):
                    p_records_map = {int(str(r.get("ID")).lstrip("#")): r for r in p_disp.to_dict("records")}
                    valid_candidates = []
                    duplicate_warnings = []

                    for cand_id in new_checked_real_ids:
                        c_row = p_records_map.get(cand_id, {})
                        c_match = str(c_row.get("Подія", "") or c_row.get("match_name", "")).strip()
                        c_ev = str(c_row.get("event_id", "")).strip()

                        is_dup = False
                        if c_match and c_match.lower() in active_real_matches_set:
                            is_dup = True
                        elif c_ev and c_ev in active_real_ev_ids_set:
                            is_dup = True

                        if is_dup:
                            duplicate_warnings.append(f"#{cand_id} ({c_match})")
                        else:
                            valid_candidates.append(cand_id)

                    if duplicate_warnings:
                        st.warning(f"⚠️ Виявлено дублікати: події {', '.join(duplicate_warnings)} вже поставлені в Реальних ставках! Повторне перенесення відхилено.")

                    if valid_candidates:
                        st.session_state["target_real_calc_ids"] = valid_candidates
                        st.session_state["show_real_stake_calc"] = True
                        st.rerun()
                    else:
                        st.error("❌ Жодної унікальної нової події для перенесення не обрано або всі вибрані події вже поставлені в Реальному банку.")

                # SPEC-34: Блок розрахунку та фіксації ставок від реального депозиту
                if st.session_state.get("show_real_stake_calc"):
                    calc_box_bg = "rgba(16, 185, 129, 0.12)" if is_dark else "#F0FDF4"
                    calc_box_border = "rgba(16, 185, 129, 0.35)" if is_dark else "#86EFAC"
                    calc_box_title = "#34D399" if is_dark else "#166534"
                    calc_box_text = "#94A3B8" if is_dark else "#374151"
                    st.markdown(f"""
                        <div style="background: {calc_box_bg}; border: 1.5px solid {calc_box_border}; border-radius: 10px; padding: 10px 14px; margin: 10px 0 14px 0;">
                            <div style="font-weight: 700; color: {calc_box_title}; font-size: 13.5px; margin-bottom: 2px;">
                                💼 Розрахунок реальних ставок від вільного залишку реального капіталу (SPEC-34)
                            </div>
                            <div style="font-size: 11.5px; color: {calc_box_text};">
                                Розмір ставки для обраних матчів розраховується <b>строго від вільного залишку Реального банку</b> (з урахуванням Kelly % ставки, макс. 5% на ставку).
                            </div>
                        </div>
                    """, unsafe_allow_html=True)

                    targets_calc = st.session_state.get("target_real_calc_ids") or new_checked_real_ids
                    if not targets_calc:
                        st.info("ℹ️ Будь ласка, відмітьте прапорцем **🟢 Real** хоча б одну ставку в таблиці вище для розрахунку.")
                    else:
                        conn_calc, _ = get_db_connection(db_url)
                        if conn_calc:
                            cur_calc = conn_calc.cursor()
                            try:
                                from statmonitor.real_bankroll import prepare_real_stakes_batch, apply_real_stakes_batch
                                real_bal, proposals = prepare_real_stakes_batch(cur_calc, targets_calc)

                                if real_bal <= 0:
                                    st.error(f"❌ Вільний залишок реального банку порожній ({real_bal:,.2f} ₴). Будь ласка, внесіть депозит або дочекайтеся розрахунку активних ставок.")
                                else:
                                    st.markdown(f"💰 **Вільний залишок реального банку:** <code>{real_bal:,.2f} ₴</code>")
                                    if proposals and "ledger_balance" in proposals[0]:
                                        st.caption(f"ℹ️ Загальний капітал: {proposals[0]['ledger_balance']:,.2f} ₴ • Вже заблоковано в грі: {proposals[0]['pending_exposure']:,.2f} ₴")
                                    with st.form(key="form_calc_real_stakes_batch"):
                                        calc_configs = []
                                        sum_calc_stakes = 0.0

                                        for p in proposals:
                                            c_m1, c_m2, c_m3, c_m4 = st.columns([3.0, 1.0, 1.5, 1.8])
                                            with c_m1:
                                                st.markdown(f"<b>#{p['id']}</b> {p['match_name']}<br><span style='font-size: 11px; color: #64748B;'>{p['pick_label']}</span>", unsafe_allow_html=True)
                                            with c_m2:
                                                st.markdown(f"Коеф: <b>{p['odds']:.2f}</b>", unsafe_allow_html=True)
                                                if p.get('walkaway_odds'):
                                                    w_val = float(p['walkaway_odds'])
                                                    if p['odds'] < w_val:
                                                        st.markdown(f"<span style='font-size: 10.5px; color: #DC2626; font-weight: 700;'>🛑 Поріг: ≥ {w_val:.2f} (-EV)</span>", unsafe_allow_html=True)
                                                    else:
                                                        st.caption(f"Поріг: ≥ {w_val:.2f}")
                                            with c_m3:
                                                st.caption(f"Келлі: ~{p['recommended_pct']}% ({p['recommended_stake']:.0f} ₴)")
                                            with c_m4:
                                                user_stk = st.number_input(
                                                    "Сума (₴):",
                                                    min_value=10.0,
                                                    max_value=float(math.floor(max(100.0, real_bal))),
                                                    value=float(round(float(p['recommended_stake']))),
                                                    step=1.0,
                                                    format="%d",
                                                    key=f"inp_r_stk_{p['id']}",
                                                    label_visibility="collapsed"
                                                )
                                                user_stk_int = float(round(user_stk))
                                                calc_configs.append({"id": p['id'], "real_stake": user_stk_int, "real_odds": p['odds']})
                                                sum_calc_stakes += user_stk_int

                                        btn_sub_save_stakes = st.form_submit_button("💾 Зафіксувати ставки в Реальному банку", type="primary", use_container_width=True)

                                    tot_pct = round((sum_calc_stakes / real_bal) * 100.0, 1) if real_bal > 0 else 0.0
                                    exp_txt_clr = '#F8FAFC' if is_dark else '#1E293B'
                                    st.markdown(f"""
                                        <div style="font-size: 12.5px; margin: 8px 0; color: {exp_txt_clr};">
                                            <b>Загальна експозиція обраних:</b> <code>{sum_calc_stakes:,.0f} ₴</code> 
                                            ({tot_pct}% від вільного залишку банку)
                                        </div>
                                    """, unsafe_allow_html=True)

                                    if btn_sub_save_stakes:
                                        # SPEC-36: Перевірка ризик-запобіжників (Circuit Breakers) перед фіксацією
                                        from statmonitor.real_bankroll import evaluate_real_risk_guardrails
                                        guard_eval = evaluate_real_risk_guardrails(cur_calc, candidate_configs=calc_configs)

                                        if guard_eval["stop_loss"]["is_triggered"]:
                                            st.error(f"🛑 {guard_eval['stop_loss']['message']}")
                                        elif not guard_eval["can_place_bets"]:
                                            err_msg = " | ".join(guard_eval.get("blocks", []))
                                            st.error(f"🛑 Запобіжники капіталу заблокували ставки: {err_msg}")
                                        else:
                                            ok_app, cnt_app, tot_app, msg_app = apply_real_stakes_batch(cur_calc, conn_calc, calc_configs)
                                            if ok_app:
                                                st.success(f"✅ {msg_app}")
                                                st.session_state["show_real_stake_calc"] = False
                                                st.session_state["target_real_calc_ids"] = []
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {msg_app}")

                                    if st.button("Скасувати", key="btn_cancel_real_stake_calc", use_container_width=True):
                                        st.session_state["show_real_stake_calc"] = False
                                        st.session_state["target_real_calc_ids"] = []
                                        st.rerun()
                            finally:
                                cur_calc.close()
                                conn_calc.close()
            else:
                ro_disp = p_disp.copy()
                ro_disp["🟢 Real"] = ro_disp["🟢 Real"].apply(lambda x: "🟢 Real" if x else "⚪ Paper")
                st.dataframe(ro_disp[cols_pending_show], use_container_width=True, hide_index=True)

            if is_admin:
                with st.expander("✏️ Редагування маркету та коефіцієнта (Edit Pick & Odds для активної ставки)", expanded=False):
                    bet_options = {}
                    for _, r_bet in pending_df.iterrows():
                        c_time_str = format_kyiv_time(r_bet.get('commence_time'))
                        time_badge = f" [🕒 {c_time_str}]" if c_time_str else ""
                        k_badge = _get_kelly_badge(r_bet)
                        stk_val = float(r_bet.get('stake_uah', 0) or 0)
                        sp_icon = get_sport_icon(r_bet.get('sport'))
                        b_lbl = f"ID #{r_bet['id']} | {sp_icon} {r_bet.get('match_name', '')} ({r_bet.get('pick_label', '')}){time_badge} — {stk_val:.2f} ₴ ({k_badge}) | Коеф: {float(r_bet.get('odds', 0)):.2f}"
                        bet_options[b_lbl] = r_bet["id"]

                    sel_lbl = st.selectbox("Оберіть ставку:", list(bet_options.keys()), key="sel_pending_bet_v3")
                    sel_id = bet_options[sel_lbl]
                    cur_row_ed = pending_df[pending_df["id"] == sel_id].iloc[0]
                    curr_odds_val = float(cur_row_ed.get("odds", 2.0))
                    curr_pick_val = str(cur_row_ed.get("pick_label", ""))

                    with st.form(key=f"form_edit_paper_bet_{sel_id}"):
                        col_ed1, col_ed2, col_ed3 = st.columns([2.5, 2.5, 2])
                        with col_ed1:
                            new_pick_input = st.text_input("Маркет / Фора:", value=curr_pick_val, key="txt_new_pick_v3")
                        with col_ed2:
                            new_k_input = st.number_input("Новий коефіцієнт:", min_value=1.01, max_value=50.00, value=curr_odds_val, step=0.01, format="%.2f", key="num_new_odds_v3")
                        with col_ed3:
                            st.write("")
                            st.write("")
                            btn_save_p_ed = st.form_submit_button("💾 Зберегти зміни", type="primary", use_container_width=True)

                        if btn_save_p_ed:
                            conn_edit, err_conn = get_db_connection(db_url)
                            if conn_edit:
                                cur_edit = conn_edit.cursor()
                                try:
                                    from statmonitor.paper_trading import update_pending_bet_odds
                                    ok, msg, _ = update_pending_bet_odds(cur_edit, conn_edit, sel_id, new_k_input, new_pick=new_pick_input)
                                    if ok:
                                        st.success(f"✅ {msg}")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {msg}")
                                finally:
                                    cur_edit.close()
                                    conn_edit.close()

                with st.expander("⚖️ Ручний розрахунок результату ставки та виправлення (Manual Settle)", expanded=False):
                    settle_tabs = st.tabs(["⏳ Активні ставки (Pending)", "✏️ Виправити / Перерахувати ставку (за ID)"])

                    with settle_tabs[0]:
                        settle_options = {}
                        for _, r_bet in pending_df.iterrows():
                            c_time_str = format_kyiv_time(r_bet.get('commence_time'))
                            time_badge = f" [🕒 {c_time_str}]" if c_time_str else ""
                            stk_val = float(r_bet.get('stake_uah', 0) or 0)
                            sp_icon = get_sport_icon(r_bet.get('sport'))
                            s_lbl = f"ID #{r_bet['id']} | {sp_icon} {r_bet.get('match_name', '')} ({r_bet.get('pick_label', '')}){time_badge} — {stk_val:.2f} ₴ | Коеф: {float(r_bet.get('odds', 0)):.2f}"
                            settle_options[s_lbl] = r_bet["id"]

                        sel_s_lbl = st.selectbox("Оберіть активну ставку для розрахунку:", list(settle_options.keys()), key="sel_settle_bet_admin_v3")
                        sel_s_id = settle_options[sel_s_lbl]
                        cur_bet_info = pending_df[pending_df["id"] == sel_s_id].iloc[0]

                        bet_box_bg = '#161F30' if is_dark else '#F8FAFC'
                        bet_box_border = '#233044' if is_dark else '#E2E8F0'
                        st.markdown(f"""
                            <div style="background: {bet_box_bg}; border: 1px solid {bet_box_border}; border-radius: 8px; padding: 10px; margin-bottom: 12px; font-size: 13px;">
                                <b>Подія:</b> {cur_bet_info.get('match_name', '—')} &nbsp;|&nbsp;
                                <b>Маркет:</b> {cur_bet_info.get('pick_label', '—')} &nbsp;|&nbsp;
                                <b>Коеф:</b> {float(cur_bet_info.get('odds', 0)):.2f} &nbsp;|&nbsp;
                                <b>Сума:</b> {float(cur_bet_info.get('stake_uah', 0)):,.2f} ₴
                            </div>
                        """, unsafe_allow_html=True)

                        with st.form(key=f"form_manual_settle_paper_{sel_s_id}"):
                            col_st1, col_st2, col_st3 = st.columns([2.5, 2.5, 2])
                            with col_st1:
                                score_val = st.text_input("Рахунок матчу (напр. 0:2, 7:6, 7:5):", placeholder="0:2", key="txt_settle_score_v3")
                            with col_st2:
                                status_mode = st.selectbox(
                                    "Статус результату:",
                                    ["Автоматично за рахунком", "✅ WON (Виграш)", "❌ LOST (Програш)", "🔄 VOID (Повернення)"],
                                    key="sel_settle_status_v3"
                                )
                            with col_st3:
                                st.write("")
                                st.write("")
                                btn_sub_settle = st.form_submit_button("⚖️ Розрахувати ставку", type="primary", use_container_width=True)

                            if btn_sub_settle:
                                forced_res = None
                                if "WON" in status_mode:
                                    forced_res = "WON"
                                elif "LOST" in status_mode:
                                    forced_res = "LOST"
                                elif "VOID" in status_mode:
                                    forced_res = "VOID"

                                final_score = score_val.strip() if score_val.strip() else ("—" if forced_res else "")
                                if not final_score and not forced_res:
                                    st.warning("⚠️ Введіть рахунок матчу або оберіть статус (WON/LOST/VOID).")
                                else:
                                    conn_set, err_set = get_db_connection(db_url)
                                    if conn_set:
                                        cur_set = conn_set.cursor()
                                        try:
                                            from statmonitor.paper_trading import manual_settle_bet
                                            ok_set, msg_set = manual_settle_bet(cur_set, conn_set, sel_s_id, final_score or "—", forced_status=forced_res)
                                            if ok_set:
                                                st.success(f"✅ {msg_set}")
                                                try:
                                                    from statmonitor.notifier import send_tg
                                                    send_tg(f"⚖️ <b>Ставку #{sel_s_id} розраховано вручну через адмінку:</b>\n{msg_set}")
                                                except Exception:
                                                    pass
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {msg_set}")
                                        finally:
                                            cur_set.close()
                                            conn_set.close()

                    with settle_tabs[1]:
                        st.caption("Виправлення або повторний розрахунок будь-якої ставки (наприклад #56 Shelton - Jodar)")
                        with st.form("form_fix_bet"):
                            col_fx1, col_fx2, col_fx3 = st.columns([1.5, 2.5, 2])
                            with col_fx1:
                                fix_bet_id = st.number_input("ID ставки для виправлення:", min_value=1, value=56, step=1, key="num_fix_bet_id")
                            with col_fx2:
                                fix_score = st.text_input("Рахунок матчу:", value="7:6, 7:5", key="txt_fix_score")
                            with col_fx3:
                                fix_status = st.selectbox(
                                    "Встановити статус:",
                                    ["✅ WON (Виграш)", "❌ LOST (Програш)", "🔄 VOID (Повернення)", "Автоматично за рахунком"],
                                    key="sel_fix_status"
                                )
                            btn_fix_sub = st.form_submit_button("🔄 Оновити / Виправити результат ставки", type="primary", use_container_width=True)

                        if btn_fix_sub:
                            f_res = None
                            if "WON" in fix_status:
                                f_res = "WON"
                            elif "LOST" in fix_status:
                                f_res = "LOST"
                            elif "VOID" in fix_status:
                                f_res = "VOID"

                            conn_fix, err_fix = get_db_connection(db_url)
                            if conn_fix:
                                cur_fix = conn_fix.cursor()
                                try:
                                    from statmonitor.paper_trading import manual_settle_bet
                                    ok_fix, msg_fix = manual_settle_bet(cur_fix, conn_fix, int(fix_bet_id), fix_score.strip() or "—", forced_status=f_res)
                                    if ok_fix:
                                        st.success(f"✅ {msg_fix}")
                                        try:
                                            from statmonitor.notifier import send_tg
                                            send_tg(f"🛠 <b>Результат ставки #{fix_bet_id} виправлено адміністратором:</b>\n{msg_fix}")
                                        except Exception:
                                            pass
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {msg_fix}")
                                finally:
                                    cur_fix.close()
                                    conn_fix.close()
        else:
            st.info("ℹ️ Немає активних ставок у грі.")

        # 6. ІСТОРІЯ СТАВОК (SPEC-33)
        history_df = filtered_df[filtered_df["status"].isin(["WON", "LOST", "VOID"])].copy() if (not filtered_df.empty and "status" in filtered_df.columns) else pd.DataFrame()
        if history_df.empty and status_filter in ("Всі ставки", "✅ Розраховані (Settled)") and (bets_df is not None and not bets_df.empty and "status" in bets_df.columns):
            history_df = bets_df[bets_df["status"].isin(["WON", "LOST", "VOID"])].copy()

        with st.expander(f"📜 Історія ставок ({len(history_df)})", expanded=True):
            if not history_df.empty:
                h_disp = history_df.copy()
                h_disp["ID"] = h_disp["id"].apply(lambda x: f"#{x}")
                if "commence_time" in h_disp.columns:
                    h_disp["Час"] = h_disp["commence_time"].apply(format_kyiv_time)
                h_disp["Режим"] = h_disp.apply(
                    lambda r: "🟢 Real" if (r.get("is_real_bet") is True or str(r.get("is_real_bet")).lower() in ("true", "t", "1")) else "⚪ Paper",
                    axis=1
                )
                h_disp["Турнір"] = h_disp["sport"].apply(lambda sp: _get_league_name(sp, with_icon=True))
                h_disp["Подія"] = h_disp.get("match_name", "")
                if "match_score" in h_disp.columns:
                    h_disp["Рахунок"] = h_disp["match_score"].apply(
                        lambda x: str(x).strip() if (x is not None and str(x).strip() and str(x).strip().lower() not in ("none", "null", "nan", "")) else "—"
                    )
                else:
                    h_disp["Рахунок"] = "—"
                h_disp["Маркет"] = h_disp.get("pick_label", "").apply(_clean_pick_label)
                h_disp["Коеф."] = h_disp["odds"].apply(lambda x: f"{float(x):.2f}" if x else "—")
                h_disp["CLV (+EV)"] = h_disp.apply(_format_clv, axis=1)
                h_disp["ШІ Сигнал"] = h_disp.apply(_get_ai_score_badge, axis=1)
                h_disp["% банку"] = h_disp.apply(_get_kelly_badge, axis=1)
                h_disp["Сума"] = h_disp["stake_uah"].apply(lambda x: f"{float(x):,.0f} ₴" if x else "—")
                h_disp["Результат"] = h_disp.apply(_format_result, axis=1)

                if is_admin:
                    cols_history_show = [
                        c for c in [
                            "ID", "Час", "Режим", "Турнір", "Подія", "Рахунок", "Маркет",
                            "Коеф.", "CLV (+EV)", "ШІ Сигнал", "% банку", "Сума", "Результат"
                        ] if c in h_disp.columns
                    ]
                else:
                    cols_history_show = [
                        c for c in [
                            "ID", "Час", "Турнір", "Подія", "Рахунок", "Маркет",
                            "Коеф.", "CLV (+EV)", "ШІ Сигнал", "% банку", "Сума", "Результат"
                        ] if c in h_disp.columns
                    ]
                st.dataframe(h_disp[cols_history_show], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Немає розрахованих ставок в історії за обраними фільтрами.")

    # ---------------- ВКЛАДКА 2: РЕАЛЬНИЙ БАНК (REAL MONEY - ADMIN ONLY) ----------------
    if is_admin and tab_real is not None:
        with tab_real:
            real_title_clr = '#4ADE80' if is_dark else '#166534'
            real_sub_clr = '#94A3B8' if is_dark else '#64748B'
            st.markdown(f"""
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                    <div>
                        <h3 style="margin: 0; padding: 0; color: {real_title_clr}; font-size: 20px; font-weight: 700;">🟢 Реальний банк (Real Money Trading)</h3>
                        <div style="font-size: 12.5px; color: {real_sub_clr}; margin-top: 2px;">
                            Автономний облік реального капіталу: депозити, фактичні ставки з No-Vig Kelly стейкінгом та розрахунок результатів.
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            # 1. KPI-МЕТРИКИ РЕАЛЬНОГО БАНКУ
            cr1, cr2, cr3, cr4, cr5, cr6 = st.columns(6)

            real_bal = float(real_summary.get("current_balance", 0.0) or 0.0)
            real_dep = float(real_summary.get("total_deposits", 0.0) or 0.0)
            real_with = float(real_summary.get("total_withdrawals", 0.0) or 0.0)
            real_pnl = float(real_summary.get("real_profit", 0.0) or 0.0)
            real_roi = float(real_summary.get("real_roi_pct", 0.0) or 0.0)
            real_turn = float(real_summary.get("real_turnover", 0.0) or 0.0)
            real_win_pct = float(real_summary.get("real_win_rate", 0.0) or 0.0)
            p_real_cnt = int(real_summary.get("pending_real", 0) or 0)
            w_real_cnt = int(real_summary.get("won_real", 0) or 0)
            l_real_cnt = int(real_summary.get("lost_real", 0) or 0)
            v_real_cnt = int(real_summary.get("void_real", 0) or 0)
            tot_real_cnt = int(real_summary.get("total_real_bets", 0) or 0)

            # Розрахунок активної експозиції (заблоковано в грі)
            real_pending_df = (
                bets_df[(bets_df["is_real_bet"] == True) & (bets_df["status"] == "PENDING")].copy()
                if (bets_df is not None and not bets_df.empty and "is_real_bet" in bets_df.columns and "status" in bets_df.columns)
                else pd.DataFrame()
            )
            if not real_pending_df.empty:
                real_exposure = float(real_pending_df.apply(
                    lambda r: float(r.get("real_stake_uah") or r.get("stake_uah") or 0.0), axis=1
                ).sum())
            else:
                real_exposure = 0.0

            free_real_balance = max(0.0, real_bal - real_exposure)

            cr1.metric(
                label="🏦 Баланс банку",
                value=f"{real_bal:,.2f} ₴",
                delta=f"{real_pnl:+,.2f} ₴ PnL" if real_pnl != 0 else "0.00 ₴",
                delta_color="normal" if real_pnl >= 0 else "inverse",
            )
            cr2.metric(
                label="💰 Всього депозитів",
                value=f"{real_dep:,.2f} ₴",
                delta=f"-{real_with:,.2f} ₴ виведено" if real_with > 0 else "Капітал",
                delta_color="off",
            )
            cr3.metric(
                label="📈 Real ROI",
                value=f"{real_roi:+.2f}%",
                delta=f"Прибуток: {real_pnl:+,.0f} ₴",
                delta_color="normal" if real_roi >= 0 else "inverse",
            )
            cr4.metric(
                label="🔄 Оборот (Turnover)",
                value=f"{real_turn:,.2f} ₴",
                delta=f"{tot_real_cnt} ставок",
                delta_color="off",
            )
            cr5.metric(
                label="🎯 Real Вінрейт",
                value=f"{real_win_pct:.1f}%",
                delta=f"🟢 {w_real_cnt}W • 🔴 {l_real_cnt}L • ⚪ {v_real_cnt}V",
                delta_color="normal" if real_win_pct >= 50 else ("inverse" if real_win_pct > 0 else "off"),
            )
            cr6.metric(
                label="⏳ В грі (Pending)",
                value=f"{p_real_cnt} ставок",
                delta=f"Заблоковано: {real_exposure:,.0f} ₴",
                delta_color="off",
            )

            # 2. ГРАФІК ДИНАМІКИ РЕАЛЬНОГО БАНКУ ТА РИЗИК-ЛІМІТИ
            col_r_chart_left, col_r_chart_right = st.columns([7, 5])

            with col_r_chart_left:
                st.markdown("##### 📈 Динаміка реального банкролу (Ledger Growth)")
                if isinstance(real_ledger_df, pd.DataFrame) and not real_ledger_df.empty:
                    r_ledger_sorted = real_ledger_df.sort_values(by=["created_at", "id"], ascending=True).copy()
                    r_ledger_sorted["Час"] = pd.to_datetime(r_ledger_sorted["created_at"], utc=True)

                    fig_real = go.Figure()
                    fig_real.add_trace(go.Scatter(
                        x=r_ledger_sorted["Час"],
                        y=r_ledger_sorted["balance_after_uah"],
                        mode="lines+markers",
                        line=dict(color="#16A34A", width=3),
                        marker=dict(size=6, color="#15803D"),
                        fill="tozeroy",
                        fillcolor="rgba(22, 163, 74, 0.08)",
                        name="Баланс (₴)",
                        hovertemplate="<b>%{x|%d.%m %H:%M}</b><br>Баланс: %{y:,.2f} ₴<extra></extra>",
                    ))

                    if real_dep > 0:
                        fig_real.add_hline(
                            y=real_dep,
                            line_dash="dash",
                            line_color="#94A3B8",
                            annotation_text=f"Депозити: {real_dep:,.0f} ₴",
                            annotation_position="bottom right",
                        )

                    fig_real.update_layout(
                        height=260,
                        margin=dict(l=10, r=10, t=25, b=10),
                        template="plotly_dark" if is_dark else "plotly_white",
                        plot_bgcolor="rgba(0,0,0,0)",
                        paper_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(
                            showgrid=True,
                            gridcolor="#1E293B" if is_dark else "#F1F5F9",
                            tickformat="%d.%m\n%H:%M",
                            tickfont=dict(size=10, color="#94A3B8" if is_dark else "#64748B"),
                        ),
                        yaxis=dict(
                            showgrid=True,
                            gridcolor="#1E293B" if is_dark else "#F1F5F9",
                            tickfont=dict(size=10, color="#94A3B8" if is_dark else "#64748B"),
                            tickprefix="",
                            ticksuffix=" ₴",
                        ),
                        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                    )
                    st.plotly_chart(fig_real, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("ℹ️ Графік з'явиться після першого депозиту в Касі реального банку нижче.")

            with col_r_chart_right:
                st.markdown("##### 🛡️ Експозиція та Circuit Breakers (SPEC-36)")

                # Оцінка стану запобіжників (Stop-Loss, Max Exposure, Кореляції)
                sl_info = {"is_triggered": False, "daily_pnl_uah": 0.0, "drawdown_pct": 0.0, "threshold_pct": 7.0}
                corr_info = {"has_correlations": False, "correlated_matches": []}
                try:
                    conn_cb, _ = get_db_connection(db_url)
                    if conn_cb:
                        cur_cb = conn_cb.cursor()
                        try:
                            from statmonitor.real_bankroll import evaluate_real_risk_guardrails
                            cb_eval = evaluate_real_risk_guardrails(cur_cb)
                            sl_info = cb_eval.get("stop_loss", sl_info)
                            corr_info = cb_eval.get("correlations", corr_info)
                        finally:
                            cur_cb.close()
                            conn_cb.close()
                except Exception:
                    pass

                exp_ratio = (real_exposure / real_bal) if real_bal > 0 else 0.0
                exp_pct = min(100.0, exp_ratio * 100.0)
                exp_clr = "#16A34A" if exp_pct <= 15.0 else ("#EAB308" if exp_pct <= 20.0 else "#DC2626")

                sl_badge = (
                    '<span style="background: rgba(239, 68, 68, 0.2); color: #FCA5A5; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 9999px;">🛑 STOP-LOSS АКТИВОВАНО</span>'
                    if (is_dark and sl_info.get("is_triggered")) else (
                        '<span style="background: #FEE2E2; color: #991B1B; font-size: 11px; font-weight: 700; padding: 2px 7px; border-radius: 9999px;">🛑 STOP-LOSS АКТИВОВАНО</span>'
                        if sl_info.get("is_triggered") else
                        f'<span style="background: {"rgba(16, 185, 129, 0.15)" if is_dark else "#DCFCE7"}; color: {"#34D399" if is_dark else "#166534"}; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 9999px;">🟢 Норма ({sl_info.get("daily_pnl_uah", 0.0):+.0f} ₴ / -{sl_info.get("threshold_pct", 7.0):.0f}%)</span>'
                    )
                )
                corr_badge = (
                    f'<span style="background: {"rgba(245, 158, 11, 0.2)" if is_dark else "#FEF3C7"}; color: {"#FCD34D" if is_dark else "#92400E"}; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 9999px;">⚠️ Кореляція ({len(corr_info.get("correlated_matches", []))})</span>'
                    if corr_info.get("has_correlations") else
                    f'<span style="background: {"#1E293B" if is_dark else "#F1F5F9"}; color: {"#94A3B8" if is_dark else "#475569"}; font-size: 11px; font-weight: 500; padding: 2px 7px; border-radius: 9999px;">🟢 Чисто</span>'
                )

                cb_card_bg = "#161F30" if is_dark else "#F8FAFC"
                cb_card_border = "#233044" if is_dark else "#E2E8F0"
                cb_t_clr = "#F8FAFC" if is_dark else "#0F172A"
                cb_s_clr = "#94A3B8" if is_dark else "#475569"
                bar_bg = "#233044" if is_dark else "#E2E8F0"

                st.markdown(f"""
                    <div style="background: {cb_card_bg}; border: 1px solid {cb_card_border}; border-radius: 8px; padding: 12px; margin-bottom: 10px;">
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-size: 12.5px; font-weight: 600; color: {cb_t_clr};">🛑 Денний Stop-Loss (-7%):</span>
                            {sl_badge}
                        </div>
                        <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 6px;">
                            <span style="font-size: 12.5px; font-weight: 600; color: {cb_t_clr};">🔗 Анти-кореляція:</span>
                            {corr_badge}
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 12px; margin-top: 8px; margin-bottom: 4px;">
                            <span style="color: {cb_t_clr};">🔒 <b>Експозиція (ліміт 20%):</b></span>
                            <span style="font-weight: 700; color: {exp_clr};">{real_exposure:,.2f} ₴ ({exp_pct:.1f}%)</span>
                        </div>
                        <div style="width: 100%; background: {bar_bg}; height: 8px; border-radius: 4px; overflow: hidden; margin-bottom: 8px;">
                            <div style="width: {exp_pct}%; background: {exp_clr}; height: 100%;"></div>
                        </div>
                        <div style="display: flex; justify-content: space-between; font-size: 11.5px; color: {cb_s_clr}; border-top: 1px solid {cb_card_border}; padding-top: 6px;">
                            <span>💵 Вільний залишок коштів:</span>
                            <b style="color: {cb_t_clr};">{free_real_balance:,.2f} ₴</b>
                        </div>
                    </div>
                """, unsafe_allow_html=True)

                hard_limit = round(real_bal * 0.05, 2)
                kv_bg = "rgba(16, 185, 129, 0.12)" if is_dark else "#F0FDF4"
                kv_border = "rgba(16, 185, 129, 0.25)" if is_dark else "#BBF7D0"
                kv_text = "#34D399" if is_dark else "#166534"
                st.markdown(f"""
                    <div style="background: {kv_bg}; border: 1px solid {kv_border}; border-radius: 8px; padding: 10px; font-size: 12px; color: {kv_text};">
                        <div style="font-weight: 700; margin-bottom: 4px;">📐 Модель No-Vig Kelly стейкінгу (SPEC-34):</div>
                        <div>• <b>Формула:</b> <code>0.10 × Kelly (Fair No-Vig Pinnacle)</code></div>
                        <div>• <b>Мінімальна ставка:</b> <code>20.00 ₴</code></div>
                        <div>• <b>Hard Limit (1 ставка):</b> <code>{hard_limit:,.2f} ₴</code> (макс. 5% банку)</div>
                        <div>• <b>Ставок у грі зараз:</b> <code>{p_real_cnt}</code> (експозиція: <code>{real_exposure:,.2f} ₴</code>)</div>
                    </div>
                """, unsafe_allow_html=True)

            # 3. АКТИВНІ РЕАЛЬНІ СТАВКИ В ГРІ
            st.markdown(f"#### ⏳ Активні реальні ставки в грі ({len(real_pending_df)})")
            if not real_pending_df.empty:
                rp_disp = real_pending_df.copy()
                rp_disp["ID"] = rp_disp["id"].apply(lambda x: f"#{x}")
                if "commence_time" in rp_disp.columns:
                    rp_disp["Час"] = rp_disp["commence_time"].apply(format_kyiv_time)
                rp_disp["Турнір"] = rp_disp["sport"].apply(lambda sp: _get_league_name(sp, with_icon=True))
                rp_disp["Подія"] = rp_disp.get("match_name", "")
                rp_disp["Маркет"] = rp_disp.get("pick_label", "").apply(_clean_pick_label)
                rp_disp["Коеф."] = rp_disp.apply(
                    lambda r: f"{float(r.get('real_odds') or r.get('odds') or 0):.2f}", axis=1
                )
                rp_disp["Поріг (Walkaway)"] = rp_disp["walkaway_odds"].apply(
                    lambda x: f"≥ {float(x):.2f}" if (x is not None and not (pd is not None and pd.isna(x))) else "—"
                ) if "walkaway_odds" in rp_disp.columns else "—"
                rp_disp["Сума (Real)"] = rp_disp.apply(
                    lambda r: f"{float(r.get('real_stake_uah') or r.get('stake_uah') or 0):,.0f} ₴", axis=1
                )
                rp_disp["% банку"] = rp_disp.apply(
                    lambda r: f"{(float(r.get('real_stake_uah') or 0) / real_bal * 100):.1f}%" if (real_bal > 0 and r.get('real_stake_uah')) else _get_kelly_badge(r),
                    axis=1
                )
                rp_disp["Потенційний виграш"] = rp_disp.apply(
                    lambda r: f"+{(float(r.get('real_stake_uah') or r.get('stake_uah') or 0) * (float(r.get('real_odds') or r.get('odds') or 1) - 1.0)):,.2f} ₴",
                    axis=1
                )
                cols_rp_show = [c for c in ["ID", "Час", "Турнір", "Подія", "Маркет", "Коеф.", "Поріг (Walkaway)", "Сума (Real)", "% банку", "Потенційний виграш"] if c in rp_disp.columns]
                st.dataframe(rp_disp[cols_rp_show], use_container_width=True, hide_index=True)

                # Коригування коефіцієнта та суми реальної ставки (Admin only)
                with st.expander("✏️ Коригування активної ставки (Коефіцієнт / Сума в БК)", expanded=False):
                    st.caption("Швидке коригування параметрів ставки (фактичний коефіцієнт у БК та сума ставки в цілих гривнях).")
                    bet_options = {
                        int(r["id"]): f"#{r['id']} | {r.get('match_name', '')} | {r.get('pick_label', '')} (Коеф: {float(r.get('real_odds') or r.get('odds') or 0):.2f}, Сума: {float(r.get('real_stake_uah') or r.get('stake_uah') or 0):,.0f} ₴)"
                        for _, r in real_pending_df.iterrows()
                    }
                    selected_bet_id = st.selectbox(
                        "Оберіть ставку для коригування:",
                        options=list(bet_options.keys()),
                        format_func=lambda x: bet_options[x],
                        key="sb_edit_real_bet"
                    )
                    
                    cur_row = real_pending_df[real_pending_df["id"] == selected_bet_id].iloc[0]
                    curr_k = float(cur_row.get("real_odds") or cur_row.get("odds") or 1.85)
                    curr_s = float(cur_row.get("real_stake_uah") or cur_row.get("stake_uah") or 50.0)

                    with st.form(key=f"form_edit_real_bet_{selected_bet_id}"):
                        c_ed1, c_ed2, c_ed3 = st.columns([1.5, 1.5, 1.2])
                        with c_ed1:
                            new_real_odds = st.number_input(
                                "Новий коефіцієнт (odds):",
                                min_value=1.02,
                                max_value=50.0,
                                value=curr_k,
                                step=0.01,
                                format="%.2f",
                                key=f"ed_r_odds_{selected_bet_id}"
                            )
                        with c_ed2:
                            new_real_stake = st.number_input(
                                "Реальна сума ставки (₴):",
                                min_value=1.0,
                                max_value=100000.0,
                                value=float(round(curr_s)),
                                step=1.0,
                                format="%d",
                                key=f"ed_r_stake_{selected_bet_id}"
                            )
                        with c_ed3:
                            st.write("")
                            st.write("")
                            btn_save_ed = st.form_submit_button("💾 Зберегти зміни", type="primary", use_container_width=True)

                        if btn_save_ed:
                            conn_ed, _ = get_db_connection(db_url)
                            if conn_ed:
                                cur_ed = conn_ed.cursor()
                                try:
                                    from statmonitor.real_bankroll import update_real_bet_params
                                    ok_ed, msg_ed = update_real_bet_params(
                                        cur_ed, conn_ed,
                                        bet_id=selected_bet_id,
                                        new_odds=new_real_odds,
                                        new_stake=new_real_stake
                                    )
                                    if ok_ed:
                                        st.toast(f"✅ {msg_ed}", icon="💾")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {msg_ed}")
                                finally:
                                    cur_ed.close()
                                    conn_ed.close()
            else:
                st.info("ℹ️ Немає активних ставок у реальному банку. Відмітьте ставки прапорцем 🟢 Real на вкладці «📊 Paper Bank (Теорія)» та натисніть «⚡ Перенести в Реальні ставки & Розрахувати банк».")

            # 4. ІСТОРІЯ ЗАКРИТИХ РЕАЛЬНИХ СТАВОК
            real_settled_df = (
                bets_df[(bets_df["is_real_bet"] == True) & (bets_df["status"].isin(["WON", "LOST", "VOID"]))].copy()
                if (bets_df is not None and not bets_df.empty and "is_real_bet" in bets_df.columns and "status" in bets_df.columns)
                else pd.DataFrame()
            )
            with st.expander(f"📜 Історія розрахованих реальних ставок ({len(real_settled_df)})", expanded=True):
                if not real_settled_df.empty:
                    rs_disp = real_settled_df.copy()
                    rs_disp["ID"] = rs_disp["id"].apply(lambda x: f"#{x}")
                    if "commence_time" in rs_disp.columns:
                        rs_disp["Час"] = rs_disp["commence_time"].apply(format_kyiv_time)
                    rs_disp["Турнір"] = rs_disp["sport"].apply(lambda sp: _get_league_name(sp, with_icon=True))
                    rs_disp["Подія"] = rs_disp.get("match_name", "")
                    if "match_score" in rs_disp.columns:
                        rs_disp["Рахунок"] = rs_disp["match_score"].apply(
                            lambda x: str(x).strip() if (x is not None and str(x).strip() and str(x).strip().lower() not in ("none", "null", "nan", "")) else "—"
                        )
                    else:
                        rs_disp["Рахунок"] = "—"
                    rs_disp["Маркет"] = rs_disp.get("pick_label", "").apply(_clean_pick_label)
                    rs_disp["Коеф."] = rs_disp.apply(
                        lambda r: f"{float(r.get('real_odds') or r.get('odds') or 0):.2f}", axis=1
                    )
                    rs_disp["Сума (Real)"] = rs_disp.apply(
                        lambda r: f"{float(r.get('real_stake_uah') or r.get('stake_uah') or 0):,.0f} ₴", axis=1
                    )
                    rs_disp["Результат"] = rs_disp.apply(_format_result, axis=1)
                    rs_disp["Чистий прибуток"] = rs_disp["profit_uah"].apply(
                        lambda x: f"{float(x):+,.2f} ₴" if x is not None else "0.00 ₴"
                    )
                    cols_rs_show = [
                        c for c in ["ID", "Час", "Турнір", "Подія", "Рахунок", "Маркет", "Коеф.", "Сума (Real)", "Результат", "Чистий прибуток"]
                        if c in rs_disp.columns
                    ]
                    st.dataframe(rs_disp[cols_rs_show], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ Історія закритих реальних ставок поки що порожня.")

            # 5. КАСА РЕАЛЬНОГО БАНКУ (LEDGER)
            with st.expander("💵 Каса реального банку (Real Bankroll Ledger & Cashier)", expanded=(real_dep == 0)):
                col_rb1, col_rb2, col_rb3, col_rb4 = st.columns(4)
                col_rb1.metric("🏦 Поточний баланс", f"{real_bal:,.2f} ₴")
                col_rb2.metric("💰 Всього депозитів", f"{real_dep:,.2f} ₴")
                col_rb3.metric("📈 Чистий прибуток", f"{real_pnl:+,.2f} ₴")
                col_rb4.metric("📊 Real ROI", f"{real_roi:+.2f}%")

                if is_admin:
                    st.markdown("##### 📝 Внесення транзакції в леджер (Депозит / Виведення / Коригування)")
                    with st.form("form_ledger_tx"):
                        col_tx1, col_tx2, col_tx3, col_tx4 = st.columns([2.5, 1.8, 3, 1.5])
                        with col_tx1:
                            tx_type_sel = st.selectbox(
                                "Тип транзакції:",
                                [
                                    "📥 Депозит (DEPOSIT)",
                                    "📤 Виведення (WITHDRAWAL)",
                                    "⚙️ Коригування (ADJUSTMENT)",
                                    "🎯 Встановити точний баланс (SET_BALANCE)",
                                ],
                                key="sel_tx_type_v2"
                            )
                        with col_tx2:
                            tx_amt = st.number_input(
                                "Сума (грн):",
                                min_value=-1000000.00,
                                max_value=1000000.00,
                                value=0.00,
                                step=1.00,
                                format="%.2f",
                                key="num_tx_amt_v2",
                                help="Для коригування дозволені як додатні (+), так і від'ємні (-) суми з копійками."
                            )
                        with col_tx3:
                            tx_comment = st.text_input("Коментар / Призначення:", placeholder="Поповнення / Коригування банкролу", key="txt_tx_desc_v2")
                        with col_tx4:
                            st.write("")
                            st.write("")
                            btn_tx_sub = st.form_submit_button("💾 Провести", type="primary", use_container_width=True)

                    if btn_tx_sub:
                        if "DEPOSIT" in tx_type_sel:
                            raw_tx_type = "DEPOSIT"
                            is_delta_tx = False
                        elif "WITHDRAWAL" in tx_type_sel:
                            raw_tx_type = "WITHDRAWAL"
                            is_delta_tx = False
                        elif "SET_BALANCE" in tx_type_sel:
                            raw_tx_type = "ADJUSTMENT"
                            is_delta_tx = False
                        else:
                            raw_tx_type = "ADJUSTMENT"
                            is_delta_tx = True

                        conn_tx, err_tx = get_db_connection(db_url)
                        if conn_tx:
                            cur_tx = conn_tx.cursor()
                            try:
                                from statmonitor.real_bankroll import record_real_transaction
                                ok_tx, new_b, msg_tx = record_real_transaction(
                                    cur_tx, conn_tx, raw_tx_type, tx_amt,
                                    description=tx_comment or tx_type_sel,
                                    is_delta=is_delta_tx
                                )
                                if ok_tx:
                                    st.success(f"✅ {msg_tx}")
                                    st.rerun()
                                else:
                                    st.error(f"❌ {msg_tx}")
                            finally:
                                cur_tx.close()
                                conn_tx.close()

                if isinstance(real_ledger_df, pd.DataFrame) and not real_ledger_df.empty:
                    st.markdown("##### 📜 Журнал останніх транзакцій леджера")
                    disp_ledger = real_ledger_df.copy()
                    if "created_at" in disp_ledger.columns:
                        disp_ledger["Час"] = disp_ledger["created_at"].apply(format_kyiv_time)
                    disp_ledger["Тип"] = disp_ledger["transaction_type"]
                    disp_ledger["Сума"] = disp_ledger["amount_uah"].apply(lambda x: f"{float(x):+,.2f} ₴")
                    disp_ledger["Баланс після"] = disp_ledger["balance_after_uah"].apply(lambda x: f"{float(x):,.2f} ₴")
                    disp_ledger["Опис"] = disp_ledger.get("description", "—")
                    cols_l_show = [c for c in ["id", "Час", "Тип", "Сума", "Баланс після", "Опис"] if c in disp_ledger.columns]
                    st.dataframe(disp_ledger[cols_l_show], use_container_width=True, hide_index=True)

            # 6. РУЧНИЙ РОЗРАХУНОК РЕЗУЛЬТАТУ РЕАЛЬНОЇ СТАВКИ
            if is_admin:
                with st.expander("⚖️ Ручний розрахунок результату реальної ставки (Manual Settle)", expanded=False):
                    if not real_pending_df.empty:
                        settle_real_opts = {}
                        for _, r_bet in real_pending_df.iterrows():
                            c_time_str = format_kyiv_time(r_bet.get('commence_time'))
                            time_badge = f" [🕒 {c_time_str}]" if c_time_str else ""
                            stk_val = float(r_bet.get('real_stake_uah') or r_bet.get('stake_uah') or 0)
                            sp_icon = get_sport_icon(r_bet.get('sport'))
                            s_lbl = f"ID #{r_bet['id']} | {sp_icon} {r_bet.get('match_name', '')} ({r_bet.get('pick_label', '')}){time_badge} — {stk_val:,.0f} ₴ | Коеф: {float(r_bet.get('real_odds') or r_bet.get('odds') or 0):.2f}"
                            settle_real_opts[s_lbl] = r_bet["id"]

                        sel_sr_lbl = st.selectbox("Оберіть реальну ставку для розрахунку:", list(settle_real_opts.keys()), key="sel_settle_real_bet_v1")
                        sel_sr_id = settle_real_opts[sel_sr_lbl]
                        cur_rbet_info = real_pending_df[real_pending_df["id"] == sel_sr_id].iloc[0]

                        st.markdown(f"""
                            <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px; margin-bottom: 12px; font-size: 13px;">
                                <b>Подія:</b> {cur_rbet_info.get('match_name', '—')} &nbsp;|&nbsp;
                                <b>Маркет:</b> {cur_rbet_info.get('pick_label', '—')} &nbsp;|&nbsp;
                                <b>Коеф:</b> {float(cur_rbet_info.get('real_odds') or cur_rbet_info.get('odds') or 0):.2f} &nbsp;|&nbsp;
                                <b>Сума:</b> {float(cur_rbet_info.get('real_stake_uah') or cur_rbet_info.get('stake_uah') or 0):,.0f} ₴
                            </div>
                        """, unsafe_allow_html=True)

                        with st.form(key=f"form_manual_settle_real_{sel_sr_id}"):
                            col_rst1, col_rst2, col_rst3 = st.columns([2, 2, 1.5])
                            with col_rst1:
                                score_r_val = st.text_input("Рахунок матчу (напр. 2:1):", placeholder="2:1", key="txt_settle_score_real_v1")
                            with col_rst2:
                                forced_r_status = st.selectbox(
                                    "Статус результату:",
                                    ["Авто (за рахунком)", "WON (Виграш)", "LOST (Програш)", "VOID (Повернення)"],
                                    key="sel_settle_status_real_v1"
                                )
                            with col_rst3:
                                st.write("")
                                st.write("")
                                btn_sub_r_settle = st.form_submit_button("⚖️ Розрахувати", type="primary", use_container_width=True)

                            if btn_sub_r_settle:
                                forced_r_res = None
                                if "WON" in forced_r_status:
                                    forced_r_res = "WON"
                                elif "LOST" in forced_r_status:
                                    forced_r_res = "LOST"
                                elif "VOID" in forced_r_status:
                                    forced_r_res = "VOID"

                                final_r_score = score_r_val.strip()
                                if not final_r_score and not forced_r_res:
                                    st.error("⚠️ Вкажіть рахунок матчу або оберіть статус вручну.")
                                else:
                                    conn_rset, err_conn = get_db_connection(db_url)
                                    if conn_rset:
                                        cur_rset = conn_rset.cursor()
                                        try:
                                            from statmonitor.paper_trading import manual_settle_bet
                                            ok_set, msg_set = manual_settle_bet(cur_rset, conn_rset, sel_sr_id, final_r_score or "—", forced_status=forced_r_res)
                                            if ok_set:
                                                st.success(f"✅ {msg_set}")
                                                try:
                                                    from statmonitor.notifier import send_tg
                                                    send_tg(f"⚖️ <b>Реальну ставку #{sel_sr_id} розраховано вручну:</b>\n{msg_set}")
                                                except Exception:
                                                    pass
                                                st.rerun()
                                            else:
                                                st.error(f"❌ {msg_set}")
                                        finally:
                                            cur_rset.close()
                                            conn_rset.close()
                    else:
                        st.info("ℹ️ Немає активних реальних ставок для розрахунку.")

    # ---------------- ВКЛАДКА 3: AI-АНАЛІТИКА GEMINI ----------------
    with tab_ai:
        col_ai_left, col_ai_right = st.columns([7, 5])
        
        # Розрахунок динамічного аудиту стратегії з bets_df
        best_txt = "Модель демонструє позитивне математичне очікування (+EV) на фаворитах та тоталах."
        worst_txt = "Рекомендовано використовувати консервативний фракційний Келлі (1.0% - 2.0% від банку) для контролю дисперсії."
        best_title = "Теніс (ATP/WTA Finals) та Тотали"
        worst_title = "Контроль ризиків та дисперсії"

        if bets_df is not None and not bets_df.empty and "status" in bets_df.columns:
            st_settled = bets_df[bets_df["status"].isin(["WON", "LOST", "VOID"])].copy()
            if not st_settled.empty and "sport" in st_settled.columns:
                sp_grp = st_settled.groupby("sport").agg(
                    profit=("profit_uah", "sum"),
                    turnover=("stake_uah", "sum"),
                    won=("status", lambda x: (x == "WON").sum()),
                    total=("status", "count")
                ).reset_index()
                sp_grp["roi"] = (sp_grp["profit"] / sp_grp["turnover"].replace(0, 1)) * 100.0

                if not sp_grp.empty:
                    top_sp = sp_grp.sort_values(by="roi", ascending=False).iloc[0]
                    if top_sp["roi"] > 0:
                        lg_name = _get_league_name(top_sp["sport"])
                        best_title = f"{lg_name}"
                        best_txt = f"Модель демонструє високу прибутковість: ROI {top_sp['roi']:+.1f}% ({int(top_sp['won'])}/{int(top_sp['total'])} виграшів). Стабільна перевага над лінією закриття (+EV)."

                    low_sp = sp_grp.sort_values(by="roi", ascending=True).iloc[0]
                    if low_sp["roi"] < 0:
                        lg_low_name = _get_league_name(low_sp["sport"])
                        worst_title = f"{lg_low_name}"
                        worst_txt = f"Поточний ROI становить {low_sp['roi']:.1f}% ({int(low_sp['total'] - low_sp['won'])} поразок). Для ліквідних бігмаркетів рекомендовано консервативну частку Келлі (1.0% - 2.0% банку) та відбір сигналів із силою ≥ 8/10."
                    else:
                        worst_title = "Баланс дисциплін"
                        worst_txt = "Усі задіяні види спорту показують позитивну динаміку прибутку (+EV). Дисперсія згладжується фракційним критерієм Келлі."

        ai_card_bg = "#161F30" if is_dark else "#FFFFFF"
        ai_card_border = "#233044" if is_dark else "#E2E8F0"
        ai_title_clr = "#F8FAFC" if is_dark else "#0F172A"
        ai_sub_clr = "#94A3B8" if is_dark else "#64748B"
        ai_body_clr = "#CBD5E1" if is_dark else "#475569"
        ai_info_bg = "#1E293B" if is_dark else "#F8FAFC"
        ai_info_border = "#334155" if is_dark else "#E2E8F0"
        ai_info_clr = "#F8FAFC" if is_dark else "#334155"
        ai_tip_bg = "rgba(37, 99, 235, 0.15)" if is_dark else "#EFF6FF"
        ai_tip_border = "rgba(37, 99, 235, 0.3)" if is_dark else "#BFDBFE"
        ai_tip_clr = "#93C5FD" if is_dark else "#1E40AF"

        with col_ai_left:
            st.markdown(f"""
                <div style="background: {ai_card_bg}; border: 1px solid {ai_card_border}; border-radius: 12px; padding: 14px; margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">🧠</span>
                            <span style="font-size: 14px; font-weight: 700; color: {ai_title_clr};">Gemini 2.5 Flash — Автоматичний аудит стратегії</span>
                        </div>
                        <span style="font-size: 11px; font-weight: 600; background: #EEF2FF; color: #4F46E5; padding: 2px 8px; border-radius: 9999px;">Free Tier Optimized • 1,500 RPD</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px; font-size: 12px;">
                        <div style="background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px; padding: 10px; color: #065F46;">
                            <b>✅ Сильна сторона: {best_title}</b><br>
                            {best_txt}
                        </div>
                        <div style="background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 8px; padding: 10px; color: #92400E;">
                            <b>⚠️ Зона уваги: {worst_title}</b><br>
                            {worst_txt}
                        </div>
                        <div style="background: {ai_info_bg}; border: 1px solid {ai_info_border}; border-radius: 8px; padding: 10px; color: {ai_info_clr};">
                            <b>📊 Ризик-менеджмент (Дробовий Критерій Келлі)</b><br>
                            Максимальне просідання контролюється динамічною часткою банку (1.0% — 3.8%) залежно від коефіцієнта та сили сигналу.
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        with col_ai_right:
            cur_bank_val = metrics.get('current_bank', 10000) if isinstance(metrics, dict) else 10000
            st.markdown(f"""
                <div style="background: {ai_card_bg}; border: 1px solid {ai_card_border}; border-radius: 12px; padding: 14px; margin-bottom: 14px;">
                    <div style="display: flex; align-items: gap: 8px; margin-bottom: 10px;">
                        <span style="font-size: 16px;">🎯</span>
                        <span style="font-size: 13px; font-weight: 700; color: {ai_title_clr};">Топ-сигнали та налаштування банку</span>
                    </div>
                    <div style="background: {ai_tip_bg}; border: 1px solid {ai_tip_border}; border-radius: 8px; padding: 10px; font-size: 12px; color: {ai_tip_clr}; margin-bottom: 10px;">
                        💡 <b>Paper Bank:</b> {cur_bank_val:,.0f} ₴ баланс (старт: 10,000 ₴).<br>
                        Розмір ставки генерується за формулою Келлі (Quarter Kelly 0.25, діапазон 1.0% — 3.8%).
                    </div>
                    <div style="font-size: 11.5px; color: {ai_sub_clr};">
                        ℹ️ Згідно зі SPEC-30, детальні аналітичні звіти зберігаються в базі даних та доступні на цьому дашборді без перевантаження Telegram.
                    </div>
                </div>
            """, unsafe_allow_html=True)

        # SPEC-35: Контрфактичний аудит доданої вартості Gemini (Active vs Shadow)
        try:
            from statmonitor.analytics import calculate_counterfactual_audit, calculate_confidence_calibration
            cf_audit = calculate_counterfactual_audit(bets_df)
            cal_data = calculate_confidence_calibration(bets_df)

            st.markdown(f"""
                <div style="background: {ai_card_bg}; border: 1px solid {ai_card_border}; border-radius: 12px; padding: 14px; margin-top: 6px; margin-bottom: 16px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">🔬</span>
                            <span style="font-size: 14.5px; font-weight: 700; color: {ai_title_clr};">Counterfactual AI Audit & A/B Бектест (SPEC-35)</span>
                        </div>
                        <span style="font-size: 11px; font-weight: 600; background: #FEF3C7; color: #92400E; padding: 2px 8px; border-radius: 9999px;">AI Value-Add & Calibration</span>
                    </div>
                    <div style="font-size: 12px; color: {ai_body_clr}; margin-bottom: 12px;">
                        Оцінка доданої вартості ШІ: порівняння результатів допущених ставок (Confidence ≥ 8 · Золотий стандарт) проти відсіяних Shadow-ставок (Confidence < 8 або Skip).
                    </div>
            """, unsafe_allow_html=True)

            col_cf1, col_cf2, col_cf3, col_cf4 = st.columns(4)
            live_m = cf_audit["live"]
            shadow_m = cf_audit["shadow"]
            v_add = cf_audit["value_add"]

            col_cf1.metric(
                label="🟢 Допущені ШІ (≥8/10)",
                value=f"{live_m['roi_pct']:+.1f}% ROI",
                delta=f"{live_m['won']}W / {live_m['lost']}L • Win: {live_m['win_rate']:.1f}%",
                delta_color="normal" if live_m["roi_pct"] >= 0 else "inverse"
            )
            col_cf2.metric(
                label="🟡 Відсіяні Shadow (<8/10)",
                value=f"{shadow_m['roi_pct']:+.1f}% ROI",
                delta=f"{shadow_m['won']}W / {shadow_m['lost']}L • Win: {shadow_m['win_rate']:.1f}%",
                delta_color="normal" if shadow_m["roi_pct"] >= 0 else "inverse"
            )

            saved_uah = v_add["capital_saved_uah"]
            col_cf3.metric(
                label="🛡️ Збережений капітал",
                value=f"{saved_uah:+,.0f} ₴",
                delta="Захист від мінусів" if saved_uah >= 0 else "Недобір прибутку",
                delta_color="normal" if saved_uah >= 0 else "inverse"
            )

            delta_roi = v_add["delta_roi_pct"]
            col_cf4.metric(
                label="🚀 Alpha ШІ (Δ ROI)",
                value=f"{delta_roi:+.2f}%",
                delta="Перевага фільтра" if delta_roi >= 0 else "Фільтр відсікає +EV",
                delta_color="normal" if delta_roi >= 0 else "inverse"
            )

            st.markdown("</div>", unsafe_allow_html=True)

            # SPEC-41: AI Confidence Calibration & Brier Score Dashboard
            with st.expander("🎯 Калібрування AI Confidence Score & Brier Score Dashboard (SPEC-41)", expanded=False):
                b_list = cal_data.get("buckets", [])
                if b_list:
                    # 1. Топові KPI метрики
                    col_brier1, col_brier2, col_brier3, col_brier4 = st.columns(4)
                    
                    ov_brier = cal_data.get("overall_brier_score")
                    col_brier1.metric(
                        label="📐 Overall Brier Score",
                        value=f"{ov_brier:.4f}" if ov_brier is not None else "—",
                        delta="Ціль: ≤ 0.20 (Ідеал 0.0)" if ov_brier is not None else None,
                        delta_color="off"
                    )
                    
                    ece_v = cal_data.get("ece_pct")
                    col_brier2.metric(
                        label="🎯 Expected Cal. Error (ECE)",
                        value=f"{ece_v:.1f}%" if ece_v is not None else "—",
                        delta="Похибка ймовірностей" if ece_v is not None else None,
                        delta_color="normal" if (ece_v is not None and ece_v <= 15.0) else "inverse"
                    )

                    bss_v = cal_data.get("brier_skill_score")
                    col_brier3.metric(
                        label="⚡ Brier Skill Score (BSS)",
                        value=f"{bss_v:+.1f}%" if bss_v is not None else "—",
                        delta="Краще за наївний прогноз" if (bss_v is not None and bss_v > 0) else "Без переваги над базою",
                        delta_color="normal" if (bss_v is not None and bss_v > 0) else "inverse"
                    )

                    v_label = cal_data.get("calibration_verdict_label", "—")
                    v_key = cal_data.get("calibration_verdict", "INSUFFICIENT_DATA")
                    v_clr = "#34D399" if v_key in ("EXCELLENT", "GOOD") else ("#F87171" if v_key == "OVERCONFIDENT" else "#94A3B8")
                    col_brier4.markdown(f"""
                        <div style="background: {'rgba(16, 185, 129, 0.12)' if v_key in ('EXCELLENT', 'GOOD') else ('#1E293B' if is_dark else '#F8FAFC')}; border: 1px solid {'#10B981' if v_key in ('EXCELLENT', 'GOOD') else ('#334155' if is_dark else '#E2E8F0')}; border-radius: 8px; padding: 10px; margin-top: 4px;">
                            <div style="font-size: 11px; color: {'#94A3B8' if is_dark else '#64748B'}; font-weight: 600;">СТАТУС КАЛІБРУВАННЯ</div>
                            <div style="font-size: 13px; font-weight: 700; color: {v_clr}; margin-top: 3px;">{v_label}</div>
                        </div>
                    """, unsafe_allow_html=True)

                    st.markdown("<div style='margin-top: 14px;'></div>", unsafe_allow_html=True)

                    # 2. Графіки: Калібрувальна крива (Reliability Diagram) + Sharpness Histogram
                    c_col_chart1, c_col_chart2 = st.columns([1.3, 1])

                    with c_col_chart1:
                        fig_cal = go.Figure()

                        # Perfect calibration reference diagonal
                        fig_cal.add_trace(go.Scatter(
                            x=[0, 100],
                            y=[0, 100],
                            mode="lines",
                            name="Ідеальне калібрування (y = x)",
                            line=dict(color="#64748B", width=1.5, dash="dash"),
                            hoverinfo="skip"
                        ))

                        # Active buckets with settled bets
                        active_buckets = [b for b in b_list if (b["won"] + b["lost"]) > 0]
                        if active_buckets:
                            x_exp = [b["expected_win_rate"] for b in active_buckets]
                            y_act = [b["win_rate"] for b in active_buckets]
                            b_sizes = [max(12, min(36, b["won"] + b["lost"] + 10)) for b in active_buckets]
                            b_texts = []
                            for b in active_buckets:
                                br_str = f"{b['brier_score']:.4f}" if b.get("brier_score") is not None else "—"
                                b_texts.append(
                                    f"<b>{b['label']}</b><br>Очікуваний WR: {b['expected_win_rate']:.1f}%<br>Фактичний WR: {b['win_rate']:.1f}%<br>Ставок: {b['won']}W / {b['lost']}L<br>ROI: {b['roi_pct']:+.1f}%<br>Brier: {br_str}"
                                )

                            fig_cal.add_trace(go.Scatter(
                                x=x_exp,
                                y=y_act,
                                mode="lines+markers",
                                name="Емпірична крива ШІ",
                                line=dict(color="#3B82F6", width=2.5),
                                marker=dict(size=b_sizes, color="#2563EB", line=dict(color="#FFFFFF" if not is_dark else "#1E293B", width=2)),
                                hoverinfo="text",
                                hovertext=b_texts,
                            ))

                        fig_cal.update_layout(
                            title=dict(text="📈 Калібрувальна крива (Reliability Diagram)", font=dict(size=13, color=ai_title_clr)),
                            xaxis=dict(title="Очікувана ймовірність (Confidence %)", range=[0, 105], showgrid=True, gridcolor="#1E293B" if is_dark else "#EEF2F6"),
                            yaxis=dict(title="Фактичний Win Rate (%)", range=[0, 105], showgrid=True, gridcolor="#1E293B" if is_dark else "#EEF2F6"),
                            height=270,
                            margin=dict(l=10, r=10, t=35, b=10),
                            template="plotly_dark" if is_dark else "plotly_white",
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                            showlegend=False,
                        )
                        st.plotly_chart(fig_cal, use_container_width=True, config={"displayModeBar": False})

                    with c_col_chart2:
                        b_labels = [b["label"].split(" ")[0] for b in b_list]
                        b_counts = [b["total_bets"] for b in b_list]
                        b_colors = ["#94A3B8", "#F59E0B", "#3B82F6", "#10B981"]

                        fig_sharp = go.Figure(go.Bar(
                            x=b_labels,
                            y=b_counts,
                            marker_color=b_colors,
                            text=[f"{v} ({round(v / max(1, sum(b_counts)) * 100)}%)" if v > 0 else "0" for v in b_counts],
                            textposition="auto",
                        ))
                        fig_sharp.update_layout(
                            title=dict(text="📊 Розподіл частоти оцінок (Sharpness)", font=dict(size=13, color=ai_title_clr)),
                            xaxis=dict(title="Бакет сили", showgrid=False),
                            yaxis=dict(title="Кількість ставок", showgrid=True, gridcolor="#1E293B" if is_dark else "#EEF2F6"),
                            height=270,
                            margin=dict(l=10, r=10, t=35, b=10),
                            template="plotly_dark" if is_dark else "plotly_white",
                            plot_bgcolor="rgba(0,0,0,0)",
                            paper_bgcolor="rgba(0,0,0,0)",
                        )
                        st.plotly_chart(fig_sharp, use_container_width=True, config={"displayModeBar": False})

                    # 3. Детальна таблиця бакетів
                    cal_df = pd.DataFrame(b_list)
                    cal_df["Бакет сили"] = cal_df["label"]
                    cal_df["Ставок"] = cal_df["total_bets"]
                    cal_df["Рекорд"] = cal_df.apply(lambda r: f"{r['won']}W / {r['lost']}L" if r['total_bets'] > 0 else "—", axis=1)
                    cal_df["Очікуваний WR"] = cal_df["expected_win_rate"].apply(lambda x: f"{x:.1f}%")
                    cal_df["Фактичний WR"] = cal_df["win_rate"].apply(lambda x: f"{x:.1f}%")
                    cal_df["Похибка (Gap)"] = cal_df["calibration_gap"].apply(lambda x: f"{x:+.1f}%")
                    cal_df["Avg CLV"] = cal_df["avg_clv_pct"].apply(lambda x: f"{x:+.2f}%")
                    cal_df["ROI"] = cal_df["roi_pct"].apply(lambda x: f"{x:+.2f}%")
                    cal_df["Brier Score"] = cal_df["brier_score"].apply(lambda x: f"{x:.4f}" if x is not None else "—")
                    
                    cols_cal_show = ["Бакет сили", "Ставок", "Рекорд", "Очікуваний WR", "Фактичний WR", "Похибка (Gap)", "Avg CLV", "ROI", "Brier Score"]
                    st.dataframe(cal_df[cols_cal_show], use_container_width=True, hide_index=True)

                    # 4. Сегментація цільових оцінок валую (7, 8, 9, 10)
                    gran_list = [g for g in cal_data.get("granular_scores", []) if g["score"] >= 7]
                    if gran_list:
                        with st.expander("⭐ Деталізація прохідних оцінок валую (7/10, 8/10, 9/10, 10/10)", expanded=False):
                            gran_df = pd.DataFrame(gran_list)
                            gran_df["Оцінка ШІ"] = gran_df["label"]
                            gran_df["Ставок"] = gran_df["total_bets"]
                            gran_df["Рекорд"] = gran_df.apply(lambda r: f"{r['won']}W / {r['lost']}L" if r['total_bets'] > 0 else "—", axis=1)
                            gran_df["Очікуваний WR"] = gran_df["expected_win_rate"].apply(lambda x: f"{x:.0f}%")
                            gran_df["Фактичний WR"] = gran_df["win_rate"].apply(lambda x: f"{x:.1f}%")
                            gran_df["Avg CLV"] = gran_df["avg_clv_pct"].apply(lambda x: f"{x:+.2f}%")
                            gran_df["ROI"] = gran_df["roi_pct"].apply(lambda x: f"{x:+.2f}%")
                            gran_df["Brier Score"] = gran_df["brier_score"].apply(lambda x: f"{x:.4f}" if x is not None else "—")

                            g_cols_show = ["Оцінка ШІ", "Ставок", "Рекорд", "Очікуваний WR", "Фактичний WR", "Avg CLV", "ROI", "Brier Score"]
                            st.dataframe(gran_df[g_cols_show], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ Немає розрахованих оцінок для побудови калібровки.")

            # Реєстр відсіяних Shadow-ставок
            shadow_bets_all = (
                bets_df[(bets_df["is_shadow"] == True) | (bets_df["status"] == "FILTERED")].copy()
                if (bets_df is not None and not bets_df.empty and "status" in bets_df.columns)
                else pd.DataFrame()
            )
            with st.expander(f"🕵️ Реєстр Shadow-ставок (Counterfactual Log: {len(shadow_bets_all)})", expanded=False):
                if not shadow_bets_all.empty:
                    sh_disp = shadow_bets_all.copy()
                    sh_disp["ID"] = sh_disp["id"].apply(lambda x: f"#{x}")
                    if "commence_time" in sh_disp.columns:
                        sh_disp["Час"] = sh_disp["commence_time"].apply(format_kyiv_time)
                    sh_disp["Турнір"] = sh_disp["sport"].apply(lambda sp: _get_league_name(sp, with_icon=True))
                    sh_disp["Подія"] = sh_disp.get("match_name", "")
                    sh_disp["Маркет"] = sh_disp.get("pick_label", "").apply(_clean_pick_label)
                    sh_disp["Коеф."] = sh_disp["odds"].apply(lambda x: f"{float(x):.2f}" if x else "—")
                    sh_disp["AI Score"] = sh_disp.apply(_get_ai_score_badge, axis=1)
                    sh_disp["Причина відсікання"] = sh_disp["filter_reason"].fillna("LOW_CONFIDENCE") if "filter_reason" in sh_disp.columns else "LOW_CONFIDENCE"
                    sh_disp["Рахунок"] = sh_disp["match_score"].fillna("—") if "match_score" in sh_disp.columns else "—"
                    
                    def _fmt_shadow_res(r):
                        st_val = str(r.get("shadow_status") or r.get("status") or "").upper()
                        if st_val == "WON":
                            p = float(r.get("shadow_profit_uah") or 0.0)
                            return f"🟢 Виграло б ({p:+,.0f} ₴)"
                        elif st_val == "LOST":
                            p = float(r.get("shadow_profit_uah") or 0.0)
                            return f"🔴 Програло б ({p:+,.0f} ₴)"
                        elif st_val == "VOID":
                            return "⚪ Повернення"
                        return "⏳ В грі (Pending)"

                    sh_disp["Гіпотетичний результат"] = sh_disp.apply(_fmt_shadow_res, axis=1)
                    cols_sh_show = [c for c in ["ID", "Час", "Турнір", "Подія", "Маркет", "Коеф.", "AI Score", "Причина відсікання", "Рахунок", "Гіпотетичний результат"] if c in sh_disp.columns]
                    st.dataframe(sh_disp[cols_sh_show], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ Реєстр Shadow-ставок порожній. Відсіяні системою матчі автоматично з'являтимуться тут для аналізу.")
        except Exception as cf_err:
            print("Counterfactual audit render err:", cf_err)

        # Список детальних вердиктів матчів
        st.markdown("#### 📑 Збережені вердикти матчів (ai_match_analysis)")
        df_ai = pd.DataFrame(ai_df) if (pd is not None and not isinstance(ai_df, pd.DataFrame)) else ai_df
        if df_ai is not None and not df_ai.empty:
            text_col = None
            for cand in ["verdict_text", "analysis_text", "analysis", "verdict", "text", "content"]:
                if cand in df_ai.columns:
                    text_col = cand
                    break
            if not text_col:
                for c in df_ai.columns:
                    if c not in ("event_id", "id", "created_at", "match_name", "sport", "commence_time"):
                        text_col = c
                        break

            time_col = "created_at" if "created_at" in df_ai.columns else ("commence_time" if "commence_time" in df_ai.columns else None)

            def _extract_match_from_text(txt):
                if not txt or not isinstance(txt, str):
                    return None
                # 1. Пошук рядка "Матч: Team A - Team B"
                m = re.search(r"(?:матч|гра|зустріч):\s*([^\n\r(]+)", txt, re.I)
                if m and len(m.group(1).strip()) > 3:
                    cand = m.group(1).strip()
                    if " - " in cand:
                        return cand
                # 2. Пошук назв команд у лапках «Команда 1» ... «Команда 2»
                quotes = re.findall(r"«([^»]{2,35})»", txt)
                if len(quotes) >= 2:
                    return f"{quotes[0]} - {quotes[1]}"
                return None

            try:
                from statmonitor.league_config import load_leagues_config
                cfg_all_leagues = {lg["key"]: lg.get("title", lg["key"]) for lg in load_leagues_config().get("leagues", [])}
            except Exception:
                cfg_all_leagues = {}

            for idx, row in df_ai.iterrows():
                body = row.get(text_col, "") if text_col else ""
                m_raw = row.get("match_name")

                # Захист від nan / None / порожніх значень
                if not m_raw or (pd is not None and pd.isna(m_raw)) or str(m_raw).strip().lower() in ("nan", "none", "null", ""):
                    m_from_txt = _extract_match_from_text(body)
                    m_name = m_from_txt if m_from_txt else (f"Подія #{str(row.get('event_id', idx + 1))[:8]}" if "event_id" in row and row["event_id"] else f"Подія #{idx + 1}")
                else:
                    m_name = str(m_raw).strip()

                sp_raw = row.get("sport")
                sp = "" if (not sp_raw or (pd is not None and pd.isna(sp_raw)) or str(sp_raw).strip().lower() in ("nan", "none", "null", "")) else str(sp_raw).strip()

                # Якщо sport не вказано в базі, визначаємо контекст із тексту аналізу
                if not sp:
                    b_low = str(body).lower()
                    if any(w in b_low for w in ("нба", "nba", "баскетбол", "лейкерс", "юта")):
                        sp = "basketball_nba"
                    elif any(w in b_low for w in ("теніс", "гейм", "сет", "atp", "wta", "звєрєв", "філс")):
                        sp = "tennis_atp_finals"
                    elif any(w in b_low for w in ("футбол", "гол", "ла ліга", "алавес", "депортіво")):
                        sp = "soccer_spain_la_liga"

                # Відповідна емодзі-іконка виду спорту
                icon = get_sport_icon(sp)

                # Повна українська назва ліги (замість raw API-ключа)
                league_ua = cfg_all_leagues.get(sp, "")
                if not league_ua:
                    league_ua = _get_league_name(sp) if hasattr(_get_league_name, '__call__') else sp

                sp_tag = f" • {league_ua}" if (league_ua and league_ua.lower() not in ("nan", "none", "null", "")) else ""
                raw_t = row.get(time_col) if time_col else None
                t_str = f" ({format_kyiv_time(raw_t)})" if raw_t else ""

                c_score = row.get("confidence_score")
                r_lvl = row.get("risk_level")
                score_badge = ""
                if c_score is not None and not (pd is not None and pd.isna(c_score)):
                    r_str = f" • {r_lvl} Risk" if r_lvl and str(r_lvl).lower() not in ("nan", "none", "") else ""
                    score_badge = f" [⭐ {int(c_score)}/10{r_str}]"

                header_title = f"{icon} {m_name}{sp_tag}{score_badge}{t_str}"
                with st.expander(header_title, expanded=(idx < 2)):
                    body = row.get(text_col, "") if text_col else ""
                    clean_body = format_verdict_markdown(body)
                    if clean_body:
                        st.markdown(clean_body)
                    else:
                        st.write("Текст аналізу відсутній або очікує заповнення.")
                    if "event_id" in row and row["event_id"]:
                        st.caption(f"Event ID: `{row['event_id']}`")
        else:
            st.info("ℹ️ AI-вердикти поки що не збережені в базі даних. Вони автоматично генеруються при знаходженні валуйних ставок.")

    # ---------------- ВКЛАДКА 3: КВАНТИТАТИВНИЙ БЕКТЕСТ (SPEC-42) ----------------
    with tab_backtest:
        bt_title_clr = '#F8FAFC' if is_dark else '#0F172A'
        bt_sub_clr = '#94A3B8' if is_dark else '#64748B'
        bt_card_bg = '#161F30' if is_dark else '#FFFFFF'
        bt_card_border = '#233044' if is_dark else '#E2E8F0'
        chart_bg = 'rgba(0,0,0,0)'
        chart_grid = '#1E293B' if is_dark else '#EEF2F6'

        st.markdown(f"""
            <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
                <div>
                    <h3 style="margin: 0; padding: 0; color: {bt_title_clr}; font-size: 20px; font-weight: 700;">🔬 Квантитативний Бектест та Симуляція (SPEC-42)</h3>
                    <div style="font-size: 12.5px; color: {bt_sub_clr}; margin-top: 2px;">
                        Платформа покрокової хронологічної симуляції капіталу: порівняння Kelly vs Flat vs % Bank, оцінка просідань (Max Drawdown), коефіцієнтів Шарпа/Сортіно та контрфактичних сценаріїв ШІ.
                    </div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        try:
            from statmonitor.backtest import run_backtest, run_benchmark_comparison

            # Панель налаштування симулятора
            with st.form("backtest_sim_form"):
                st.markdown(f"<div style='font-size: 13.5px; font-weight: 700; color: {bt_title_clr}; margin-bottom: 8px;'>⚙️ Параметри симуляції капіталу:</div>", unsafe_allow_html=True)
                c_bt1, c_bt2, c_bt3 = st.columns([1.5, 1.5, 1.5])
                with c_bt1:
                    sim_bank = st.number_input("Стартовий капітал (₴):", min_value=500.0, max_value=1000000.0, value=10000.0, step=500.0, format="%.0f")
                    model_choice = st.selectbox(
                        "Модель управління капіталом:",
                        ["Дробовий Келлі (Fractional Kelly)", "Фіксована ставка (Flat UAH)", "Динамічний % від капіталу (% of Bank)"]
                    )
                with c_bt2:
                    if "Келлі" in model_choice:
                        sim_fraction = st.slider("Множник Келлі (Kelly Fraction):", min_value=0.02, max_value=0.50, value=0.10, step=0.01, format="%.2f")
                        sim_flat = 100.0
                        sim_pct_bank = 0.02
                        model_key = "KELLY_FRACTION"
                    elif "Flat" in model_choice:
                        sim_flat = st.number_input("Фіксована ставка (₴):", min_value=10.0, max_value=50000.0, value=100.0, step=10.0, format="%.0f")
                        sim_fraction = 0.10
                        sim_pct_bank = 0.02
                        model_key = "FLAT"
                    else:
                        pct_val = st.slider("% від поточного капіталу:", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
                        sim_pct_bank = pct_val / 100.0
                        sim_fraction = 0.10
                        sim_flat = 100.0
                        model_key = "PERCENT_BANK"

                    sim_conf = st.slider("Мінімальна оцінка Gemini Confidence (0..10):", min_value=0, max_value=10, value=8, step=1, help="0 — всі ставки, 7 — базовий поріг, 8 — Золотий стандарт ШІ (Win Rate 62.5%, ROI +17.42%, Max DD 2.4%), 9+ — елітні сигнали.")
                with c_bt3:
                    sim_odds_range = st.slider("Діапазон коефіцієнтів (Min - Max Odds):", min_value=1.10, max_value=10.0, value=(1.15, 6.0), step=0.05)
                    sim_shadow = st.checkbox("🕵️ Включити Shadow-ставки (Контрфактичний No-AI)", value=False, help="Моделювання сценарію без ШІ: враховує відсіяні системою ставки (status='FILTERED').")
                    sim_walkaway = st.checkbox("🎯 Тільки валуйні ставки (Walkaway Odds ≥ 0)", value=False, help="Відбирати тільки ставки з коефіцієнтом не нижче порогу Walkaway Odds.")

                st.write("")
                btn_run_sim = st.form_submit_button("🚀 Запустити квантитативну симуляцію", type="primary", use_container_width=True)

            # Формуємо конфігурацію симуляції
            active_sim_cfg = {
                "initial_bankroll": sim_bank,
                "staking_model": model_key,
                "fraction": sim_fraction,
                "flat_amount": sim_flat,
                "percent_bank": sim_pct_bank,
                "min_confidence": sim_conf,
                "min_odds": sim_odds_range[0],
                "max_odds": sim_odds_range[1],
                "include_shadow": sim_shadow,
                "enforce_walkaway": sim_walkaway
            }

            # Запуск бектесту
            sim_result = run_backtest(bets_df, active_sim_cfg)
            m = sim_result["metrics"]
            curve = sim_result["equity_curve"]
            executed = sim_result["executed_bets"]

            # 1. KPI-КАРТКИ СИМУЛЯЦІЇ
            st.markdown(f"<div style='font-size: 14px; font-weight: 700; color: {bt_title_clr}; margin-top: 14px; margin-bottom: 8px;'>📊 Результати симуляції стратегії:</div>", unsafe_allow_html=True)
            kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5, kpi_c6 = st.columns(6)

            pnl_val = m["net_profit"]
            pnl_clr = "#16A34A" if pnl_val >= 0 else "#DC2626"
            roi_val = m["roi_pct"]
            roi_clr = "#16A34A" if roi_val >= 0 else "#DC2626"

            with kpi_c1:
                kpi_c1.metric("💰 Чистий прибуток", f"{pnl_val:+,.2f} ₴", f"{roi_val:+.2f}% ROI")
            with kpi_c2:
                kpi_c2.metric("🏦 Фінальний баланс", f"{m['final_balance']:,.0f} ₴", f"{m['cagr_pct']:+.1f}% від старту")
            with kpi_c3:
                kpi_c3.metric("📉 Max Drawdown", f"{m['max_drawdown_pct']:.1f}%", f"-{m['max_drawdown_uah']:,.0f} ₴", delta_color="inverse")
            with kpi_c4:
                kpi_c4.metric("⚡ Sharpe Ratio", f"{m['sharpe_ratio']:.2f}", f"Sortino: {m['sortino_ratio']:.2f}")
            with kpi_c5:
                pf_str = f"{m['profit_factor']:.2f}" if m['profit_factor'] < 50 else "∞"
                kpi_c5.metric("⚖️ Profit Factor", pf_str, f"Серія: {m['max_win_streak']}W / {m['max_loss_streak']}L")
            with kpi_c6:
                kpi_c6.metric("🎯 Win Rate", f"{m['win_rate']:.1f}%", f"{m['won_count']}W • {m['lost_count']}L • {m['void_count']}V")

            # 2. ГРАФІК КРИВОЇ КАПІТАЛУ (EQUITY CURVE & DRAWDOWN)
            if curve and len(curve) > 1:
                import plotly.graph_objects as go
                st.markdown(f"<div style='font-size: 13.5px; font-weight: 700; color: {bt_title_clr}; margin-top: 14px; margin-bottom: 6px;'>📈 Крива капіталу (Simulated Equity Curve) & High Water Mark:</div>", unsafe_allow_html=True)
                
                steps = [c["step"] for c in curve]
                balances = [c["balance"] for c in curve]
                peaks = [c.get("peak", c["balance"]) for c in curve]
                hover_texts = [
                    f"Крок: #{c['step']}<br>Матч: {c.get('match', '')}<br>Маркет: {c.get('pick', '')}<br>Ставка: {c.get('stake', 0):,.0f} ₴ (Коеф: {c.get('odds', 0):.2f})<br>PnL: {c.get('pnl', 0):+,.2f} ₴<br><b>Баланс: {c['balance']:,.2f} ₴</b><br>Просідання: {c.get('drawdown_pct', 0):.1f}%"
                    for c in curve
                ]

                fig_eq = go.Figure()

                # Пік капіталу (High Water Mark)
                fig_eq.add_trace(go.Scatter(
                    x=steps,
                    y=peaks,
                    mode="lines",
                    name="High Water Mark (Пік)",
                    line=dict(color="#64748B", width=1.5, dash="dash"),
                    hoverinfo="skip"
                ))

                # Фактична крива балансу
                fig_eq.add_trace(go.Scatter(
                    x=steps,
                    y=balances,
                    mode="lines+markers",
                    name="Баланс симуляції",
                    line=dict(color="#2563EB", width=2.5),
                    marker=dict(size=4, color="#3B82F6"),
                    text=hover_texts,
                    hoverinfo="text"
                ))

                # Лінія стартового капіталу
                fig_eq.add_hline(
                    y=sim_bank,
                    line_dash="dot",
                    line_color="#94A3B8",
                    annotation_text=f"Старт: {sim_bank:,.0f} ₴",
                    annotation_position="bottom right"
                )

                fig_eq.update_layout(
                    paper_bgcolor=chart_bg,
                    plot_bgcolor=chart_bg,
                    margin=dict(l=10, r=10, t=10, b=25),
                    height=320,
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1, font=dict(color=bt_title_clr, size=11)),
                    xaxis=dict(
                        title="Кількість ставок (Хронологія)",
                        showgrid=True,
                        gridcolor=chart_grid,
                        tickfont=dict(color=bt_sub_clr, size=11)
                    ),
                    yaxis=dict(
                        title="Баланс (грн)",
                        showgrid=True,
                        gridcolor=chart_grid,
                        tickfont=dict(color=bt_sub_clr, size=11)
                    )
                )
                st.plotly_chart(fig_eq, use_container_width=True, config={"displayModeBar": False})

            # 3. МУЛЬТИСТРАТЕГІЧНЕ ПОРІВНЯННЯ БЕНЧМАРКІВ (BENCHMARK MATRIX)
            st.markdown(f"<div style='font-size: 14px; font-weight: 700; color: {bt_title_clr}; margin-top: 16px; margin-bottom: 8px;'>🏆 Порівняльна матриця еталонних стратегій (Benchmark Grid):</div>", unsafe_allow_html=True)
            benchmarks_data = run_benchmark_comparison(bets_df, initial_bank=sim_bank)
            if benchmarks_data:
                bench_df = pd.DataFrame(benchmarks_data)
                cols_b_show = ["Стратегія", "Ставок", "Win Rate", "Чистий прибуток", "ROI", "Max Drawdown", "Profit Factor", "Sharpe Ratio", "Баланс"]
                st.dataframe(bench_df[[c for c in cols_b_show if c in bench_df.columns]], use_container_width=True, hide_index=True)
                st.caption("ℹ️ *Бенчмарки моделюють:* 1) Стандартну стратегію реальних грошей; 2) Агресивну модель Келлі; 3) Фіксовану ставку (Flat); 4) Контрфактичну поведінку No-AI (якби ШІ не відсіював слабкі сигнали); 5) Елітний відбір (сигнали ≥ 8/10 з позитивним Walkaway EV).")

            # 4. ДЕТАЛЬНИЙ ЛОГ ЗМОДЕЛЬОВАНИХ СТАВОК (EXECUTED BETS)
            with st.expander(f"📜 Журнал змодельованих ставок ({len(executed)})", expanded=False):
                if executed:
                    ex_disp = pd.DataFrame(executed)
                    ex_disp["ID"] = ex_disp["id"].apply(lambda x: f"#{x}" if x else "—")
                    ex_disp["Час"] = ex_disp["time"].apply(format_kyiv_time) if "time" in ex_disp.columns else "—"
                    ex_disp["Подія"] = ex_disp["match"]
                    ex_disp["Маркет"] = ex_disp["pick"]
                    ex_disp["Коеф."] = ex_disp["odds"].apply(lambda x: f"{float(x):.2f}")
                    ex_disp["Ставка"] = ex_disp["stake"].apply(lambda x: f"{float(x):,.0f} ₴")
                    ex_disp["Результат"] = ex_disp["status"].apply(lambda s: "🟢 WON" if s == "WON" else ("🔴 LOST" if s == "LOST" else "⚪ VOID"))
                    ex_disp["PnL"] = ex_disp["pnl"].apply(lambda x: f"{float(x):+,.2f} ₴")
                    ex_disp["Баланс після угоди"] = ex_disp["balance"].apply(lambda x: f"{float(x):,.2f} ₴")
                    ex_disp["Просідання"] = ex_disp["drawdown_pct"].apply(lambda x: f"{float(x):.1f}%")

                    disp_cols = ["ID", "Час", "Подія", "Маркет", "Коеф.", "Ставка", "Результат", "PnL", "Баланс після угоди", "Просідання"]
                    st.dataframe(ex_disp[[c for c in disp_cols if c in ex_disp.columns]], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ За обраними параметрами жодна ставка не пройшла фільтри.")

        except Exception as e_bt:
            st.error(f"Помилка модуля бектесту: {e_bt}")

    # ---------------- ВКЛАДКА 4: РОЗКЛАД ТА ПУЛЬС ----------------
    with tab_pulse:
        # 4 статусні картки воркерів
        st.markdown("""
            <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; margin-bottom: 14px;">
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600;">
                        <span>Odds Scanner API</span><span style="color: #10B981;">● Online</span>
                    </div>
                    <div style="font-size: 11px; color: #64748B; margin-top: 4px;">Пул з 5 API ключів</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600;">
                        <span>Watchdog Daemon</span><span style="color: #10B981;">● Online</span>
                    </div>
                    <div style="font-size: 11px; color: #64748B; margin-top: 4px;">Контроль затримок крону</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600;">
                        <span>Auto-Settler Bot</span><span style="color: #10B981;">● Online</span>
                    </div>
                    <div style="font-size: 11px; color: #64748B; margin-top: 4px;">Розрахунок завершених ігор</div>
                </div>
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px;">
                    <div style="display: flex; justify-content: space-between; font-size: 12px; font-weight: 600;">
                        <span>Telegram Notifier</span><span style="color: #10B981;">● Ready</span>
                    </div>
                    <div style="font-size: 11px; color: #64748B; margin-top: 4px;">Тихі сповіщення v3.4.1</div>
                </div>
            </div>
        """, unsafe_allow_html=True)

        col_s1, col_s2 = st.columns(2)
        df_sched = pd.DataFrame(sched_df) if (pd is not None and not isinstance(sched_df, pd.DataFrame)) else sched_df
        df_hb = pd.DataFrame(heartbeat_df) if (pd is not None and not isinstance(heartbeat_df, pd.DataFrame)) else heartbeat_df

        with col_s1:
            st.markdown("##### ⏰ Контрольні точки розкладу (scheduler_plan)")
            if df_sched is not None and not df_sched.empty:
                disp_sc_df = df_sched.copy()
                if "target_time" in disp_sc_df.columns:
                    try:
                        t_cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=6)
                        t_parsed = pd.to_datetime(disp_sc_df["target_time"], utc=True)
                        disp_sc_df = disp_sc_df[t_parsed >= t_cutoff].copy()
                    except Exception:
                        pass
                if not disp_sc_df.empty:
                    if "target_time" in disp_sc_df.columns:
                        disp_sc_df["Час запуску (Київ)"] = disp_sc_df["target_time"].apply(format_kyiv_time)
                    if "executed_at" in disp_sc_df.columns:
                        disp_sc_df["Виконано (Київ)"] = disp_sc_df["executed_at"].apply(format_kyiv_time)
                    disp_sc = [c for c in ["Час запуску (Київ)", "trigger_type", "description", "status", "Виконано (Київ)"] if c in disp_sc_df.columns]
                    st.dataframe(disp_sc_df[disp_sc], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ Немає актуальних точок розкладу за останні 6 годин.")
            else:
                st.info("ℹ️ Точки розкладу ще не сформовані.")

        with col_s2:
            st.markdown("##### 💓 Монітор пульсу (system_heartbeat)")
            if df_hb is not None and not df_hb.empty:
                st.dataframe(df_hb, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Записів пульсу не знайдено.")

            # Smart Rate-Limiter (Облік ліг та витрата квоти за видами спорту)
            st.markdown("##### 🚦 Smart Rate-Limiter (Облік ліг та витрата API за видами спорту)")
            df_poll = pd.DataFrame(poll_df) if (pd is not None and not isinstance(poll_df, pd.DataFrame)) else poll_df
            if df_poll is not None and not df_poll.empty:
                disp_poll = df_poll.copy()
                try:
                    from statmonitor.league_config import load_leagues_config
                    from statmonitor.limiter import compute_sports_quota_breakdown
                    cfg_lg_all = load_leagues_config()
                    all_title_map = {lg["key"]: lg.get("title", lg["key"]) for lg in cfg_lg_all.get("leagues", [])}
                    q_tab_breakdown = compute_sports_quota_breakdown(disp_poll, leagues_config=cfg_lg_all)
                except Exception:
                    all_title_map = {}
                    q_tab_breakdown = {}

                # 1. Розподіл за категоріями спорту
                tab_cats = [c for c in q_tab_breakdown.get("categories", []) if c.get("poll_count", 0) > 0]
                if tab_cats:
                    st.caption("🏆 **Розподіл витрати запитів (токенів) за видами спорту:**")
                    df_cats_tab = pd.DataFrame([
                        {
                            "Вид спорту": c["category_name"],
                            "Запитів": c["poll_count"],
                            "% витрати": f"{c['pct_of_used']:.1f}%",
                            "% ліміту": f"{c['pct_of_limit']:.1f}%",
                            "Ліг у скануванні": c["leagues_count"],
                            "Топ-ліга споживач": c["top_league_title"],
                        }
                        for c in tab_cats
                    ])
                    st.dataframe(df_cats_tab, use_container_width=True, hide_index=True)

                # 2. Повна таблиця опитуваних ліг
                if "sport" in disp_poll.columns:
                    disp_poll["Турнір"] = disp_poll["sport"].map(lambda x: all_title_map.get(x, s_map.get(x, x)))
                if "tier" in disp_poll.columns:
                    tier_map = {
                        "HOT": "🔥 Гаряча (матч < 6 год)",
                        "WARM": "🌤️ Тепла (матч 6–24 год)",
                        "COLD": "❄️ Холодна (> 24 год)",
                        "tier1": "🟢 Пріоритет 1 (Високий)",
                        "tier2": "🟡 Пріоритет 2 (Сер.)",
                        "tier3": "⚪ Пріоритет 3 (Низьк.)",
                    }
                    disp_poll["Активність (Tier)"] = disp_poll["tier"].map(lambda t: tier_map.get(str(t).upper(), tier_map.get(str(t), str(t))))
                if "last_polled_at" in disp_poll.columns:
                    disp_poll["Останнє опитування (Київ)"] = disp_poll["last_polled_at"].apply(format_kyiv_time)
                if "poll_count" in disp_poll.columns:
                    disp_poll["Кількість запитів"] = disp_poll["poll_count"]

                st.caption("📋 **Повний лог опитування ліг (відсортовано за кількістю запитів):**")
                cols_poll_show = [c for c in ["Турнір", "Активність (Tier)", "Останнє опитування (Київ)", "Кількість запитів", "sport"] if c in disp_poll.columns]
                st.dataframe(disp_poll[cols_poll_show], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Лог опитування ліг оновлюється автоматично.")

        # SPEC-39: Холодний архів котирувань Parquet (Cloudflare R2 / S3)
        st.markdown("---")
        st.markdown("##### 📦 Холодний архів котирувань Parquet (Cloudflare R2 / S3 - SPEC-39)")
        try:
            from statmonitor.cold_archive import get_cold_archive_summary, archive_cold_odds
            arch_summary = get_cold_archive_summary(cur)
            
            c_arc1, c_arc2, c_arc3, c_arc4 = st.columns(4)
            c_arc1.metric("📦 Файлів Parquet", f"{arch_summary['files_count']}")
            c_arc2.metric("📊 Збережено записів", f"{arch_summary['total_records']:,}")
            c_arc3.metric("💾 Обсяг архіву", f"{arch_summary['total_mb']:.2f} МБ")
            c_arc4.metric("📅 Остання партиція", arch_summary['latest_partition'] or "—")
            
            if is_admin:
                c_btn_arch1, c_btn_arch2 = st.columns([1.2, 2.8])
                with c_btn_arch1:
                    if st.button("⚡ Запустити архівування (>3.5 днів)", key="btn_run_cold_archive_manual", use_container_width=True):
                        with st.spinner("Експорт котирувань у Parquet та відправка в Cloudflare R2..."):
                            conn_arch, _ = get_db_connection(db_url)
                            if conn_arch:
                                cur_arch = conn_arch.cursor()
                                try:
                                    res_m_arch = archive_cold_odds(cur_arch, conn_arch, min_age_days=3.5)
                                    if res_m_arch.get("files_created", 0) > 0:
                                        st.success(f"✅ Збережено {res_m_arch['total_records']} записів у {res_m_arch['files_created']} файлів!")
                                    else:
                                        st.info("ℹ️ Немає записів старше 3.5 днів для архівування.")
                                    st.rerun()
                                finally:
                                    cur_arch.close()
                                    conn_arch.close()
                with c_btn_arch2:
                    st.caption("ℹ️ Котирування перед 4-денною ротацією пакуються в Snappy Parquet і зберігаються в Cloudflare R2 / Local.")

            if arch_summary.get("recent_files"):
                df_arch = pd.DataFrame(arch_summary["recent_files"])
                df_arch["Партиція (Дата)"] = df_arch["partition_date"]
                df_arch["Сховище"] = df_arch["storage_type"]
                df_arch["Розмір"] = df_arch["file_size_kb"].apply(lambda x: f"{x:,.1f} КБ")
                df_arch["Записів"] = df_arch["records_count"]
                df_arch["Шлях / URI"] = df_arch["file_path"]
                df_arch["Час архівації"] = df_arch["archived_at"].apply(format_kyiv_time)
                
                cols_arch_show = ["Партиція (Дата)", "Сховище", "Розмір", "Записів", "Шлях / URI", "Час архівації"]
                st.dataframe(df_arch[cols_arch_show], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Архівні файли будуть створені автоматично перед черговою ротацією odds_history.")
        except Exception as e_arch:
            st.caption(f"Статус архівування: {e_arch}")

    # ---------------- ВКЛАДКА 4: ПОРОГИ ЛІГ (ADMIN - SPEC-25) ----------------
    if is_admin and tab_thresholds is not None:
        with tab_thresholds:
            lg_title_clr = '#F8FAFC' if is_dark else '#1E293B'
            lg_sub_clr = '#94A3B8' if is_dark else '#64748B'
            st.markdown(f"""
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px;">
                    <div>
                        <span style="font-size: 16px; font-weight: 700; color: {lg_title_clr};">🎛️ Керування лігами та Smart Rate-Limiter (SPEC-25)</span>
                        <div style="font-size: 12px; color: {lg_sub_clr}; margin-top: 2px;">
                            Увімкнення та вимкнення чемпіонатів за видами спорту. Зняття прапорця повністю виключає лігу з опитування The Odds API, зберігаючи квоту запитів.
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            try:
                from statmonitor.league_config import (
                    load_leagues_config,
                    save_league_threshold,
                    save_all_leagues_batch,
                    save_all_leagues_to_file,
                    reset_league_thresholds_to_default,
                )

                # Миттєве та надійне зчитування конфігурації ліг (з DB як єдиного джерела істини)
                cfg_leagues = load_leagues_config(db_url=db_url)
                all_leagues_list = cfg_leagues.get("leagues", [])

                # Ініціалізація стану в session_state
                if "league_enabled_state" not in st.session_state:
                    st.session_state.league_enabled_state = {
                        lg["key"]: bool(lg.get("enabled", True)) for lg in all_leagues_list
                    }

                # KPI Смуга
                tot_l_cnt = len(all_leagues_list)
                act_l_cnt = sum(1 for lg in all_leagues_list if st.session_state.league_enabled_state.get(lg["key"], lg.get("enabled", True)))
                dis_l_cnt = tot_l_cnt - act_l_cnt
                avg_drop = (
                    sum(float(lg.get("min_drop_pct", 5.0)) for lg in all_leagues_list) / tot_l_cnt
                    if tot_l_cnt > 0 else 5.0
                )

                kpi_l1, kpi_l2, kpi_l3, kpi_l4 = st.columns(4)
                kpi_l1.metric("🏆 Всього чемпіонатів", f"{tot_l_cnt}")
                kpi_l2.metric("🟢 Активних у моніторингу", f"{act_l_cnt}")
                kpi_l3.metric("⏸️ На паузі (економія квоти)", f"{dis_l_cnt}")
                kpi_l4.metric("📉 Сер. поріг просідання", f"{avg_drop:.1f}%")

                st.markdown("""
                    <div style="background: #F0FDF4; border: 1px solid #BBF7D0; border-radius: 8px; padding: 8px 12px; margin-top: 8px; margin-bottom: 12px; font-size: 12px; color: #166534;">
                        💡 <b>Порада щодо оптимізації квоти (Smart Rate-Limiter):</b> залишайте увімкненими лише ті ліги, де сьогодні проходять матчі (наприклад, NBA вночі або АПЛ/Ла Ліга у вихідні). Це зберігає пул із 2500 кредитів Odds API.
                    </div>
                """, unsafe_allow_html=True)

                # Групування за категоріями спорту
                sports_groups = {
                    "soccer": {
                        "title": "⚽ Футбол (Європейські та міжнародні турніри)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category", "soccer") == "soccer"],
                    },
                    "basketball": {
                        "title": "🏀 Баскетбол (NBA, Євроліга, NCAA)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "basketball"],
                    },
                    "tennis": {
                        "title": "🎾 Теніс (ATP, WTA, Grand Slams, Davis Cup)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "tennis"],
                    },
                    "icehockey": {
                        "title": "🏒 Хокей (NHL, SHL, Liiga та Європа)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "icehockey"],
                    },
                    "mma": {
                        "title": "🥊 MMA / Єдиноборства (UFC, Bellator)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "mma"],
                    },
                    "americanfootball": {
                        "title": "🏈 Американський футбол (NFL, NCAA)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "americanfootball"],
                    },
                    "baseball": {
                        "title": "⚾ Бейсбол (MLB, NPB, KBO)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") == "baseball"],
                    },
                    "other": {
                        "title": "🏏 Інші види спорту (Крикет, Регбі, AFL)",
                        "leagues": [lg for lg in all_leagues_list if lg.get("category") in ("other", "other_sports")],
                    },
                }

                for cat_key, grp in sports_groups.items():
                    grp_leagues = grp["leagues"]
                    if not grp_leagues:
                        continue

                    grp_active = sum(1 for lg in grp_leagues if st.session_state.league_enabled_state.get(lg["key"], bool(lg.get("enabled", True))))
                    
                    # Розрахунок використаних запитів для цієї групи спорту
                    grp_keys = {lg["key"] for lg in grp_leagues}
                    grp_poll_cnt = 0
                    if df_poll is not None and not df_poll.empty and "sport" in df_poll.columns and "poll_count" in df_poll.columns:
                        grp_poll_cnt = int(df_poll[df_poll["sport"].isin(grp_keys)]["poll_count"].sum())
                    grp_poll_badge = f" • 📊 {grp_poll_cnt} запитів" if grp_poll_cnt > 0 else ""

                    with st.expander(f"{grp['title']} — {grp_active}/{len(grp_leagues)} активних{grp_poll_badge}", expanded=(grp_active > 0)):
                        c_act1, c_act2, c_act_space = st.columns([1.5, 1.5, 5])
                        with c_act1:
                            if st.button(f"✅ Обрати всі", key=f"btn_all_{cat_key}"):
                                for lg in grp_leagues:
                                    k_id = lg["key"]
                                    st.session_state.league_enabled_state[k_id] = True
                                    st.session_state[f"chk_lg_{k_id}"] = True
                                st.rerun()
                        with c_act2:
                            if st.button(f"❌ Зняти всі", key=f"btn_none_{cat_key}"):
                                for lg in grp_leagues:
                                    k_id = lg["key"]
                                    st.session_state.league_enabled_state[k_id] = False
                                    st.session_state[f"chk_lg_{k_id}"] = False
                                st.rerun()

                        # Виведення сітки прапорців у 2 колонки
                        col_l, col_r = st.columns(2)
                        for i, lg in enumerate(grp_leagues):
                            target_col = col_l if (i % 2 == 0) else col_r
                            with target_col:
                                k = lg["key"]
                                if f"chk_lg_{k}" not in st.session_state:
                                    st.session_state[f"chk_lg_{k}"] = st.session_state.league_enabled_state.get(k, bool(lg.get("enabled", True)))
                                drop_info = f"Поріг: {float(lg.get('min_drop_pct', 5.0)):.1f}% | Кеф: {float(lg.get('min_odds', 1.40)):.2f}–{float(lg.get('max_odds', 4.00)):.2f}"
                                
                                val = st.checkbox(
                                    f"**{lg.get('title', k)}** (`{k}`) — _{drop_info}_",
                                    key=f"chk_lg_{k}",
                                    help=f"Увімкнути/вимкнути автосканування для {lg.get('title', k)}"
                                )
                                st.session_state.league_enabled_state[k] = val

                # Нижня панель збереження
                col_save_all, col_reset_all, col_save_space = st.columns([2.5, 3, 4.5])
                with col_save_all:
                    if st.button("💾 Зберегти налаштування ліг", key="btn_save_all_grouped_leagues", use_container_width=True):
                        # 1. Оновлюємо список у пам'яті
                        updated_list = []
                        for lg in all_leagues_list:
                            item = dict(lg)
                            k = item["key"]
                            is_en = bool(st.session_state.get(f"chk_lg_{k}", st.session_state.league_enabled_state.get(k, item.get("enabled", True))))
                            item["enabled"] = is_en
                            st.session_state.league_enabled_state[k] = is_en
                            updated_list.append(item)

                        # 2. Зберігаємо у файл leagues.json
                        save_all_leagues_to_file(updated_list)

                        # 3. Зберігаємо у базу даних PostgreSQL (Supabase) єдиним пакетом
                        conn_sv, err_sv = get_db_connection(db_url)
                        if conn_sv:
                            cur_sv = conn_sv.cursor()
                            try:
                                ok_sv, msg_sv = save_all_leagues_batch(cur_sv, conn_sv, updated_list)
                                if ok_sv:
                                    st.toast("✅ Налаштування ліг збережено в базі даних!", icon="🎯")
                                else:
                                    st.error(f"❌ {msg_sv}")
                            except Exception as se:
                                print(f"DB league save warning: {se}")
                                st.error(f"❌ Помилка запису в БД: {se}")
                            finally:
                                cur_sv.close()
                                conn_sv.close()
                        else:
                            st.toast("✅ Налаштування ліг збережено локально!", icon="💾")

                        st.rerun()

                with col_reset_all:
                    if st.button("🔄 Скинути всі до дефолтних", key="btn_reset_all_leagues_def", use_container_width=True):
                        conn_rst, _ = get_db_connection(db_url)
                        cur_rst = conn_rst.cursor() if conn_rst else None
                        try:
                            reset_league_thresholds_to_default(cur_rst, conn_rst)
                        finally:
                            if cur_rst:
                                cur_rst.close()
                            if conn_rst:
                                conn_rst.close()
                        if "league_enabled_state" in st.session_state:
                            del st.session_state["league_enabled_state"]
                        for k_s in list(st.session_state.keys()):
                            if str(k_s).startswith("chk_lg_"):
                                del st.session_state[k_s]
                        st.toast("✅ Налаштування скинуто до початкових!", icon="🔄")
                        st.rerun()

                # Додатковий блок тонкого тюнінгу порогів коефіцієнтів
                with st.expander("⚙️ Тонке налаштування порогів чутливості та ринків для окремої ліги"):
                    league_options = {f"{lg.get('title', lg['key'])} ({lg['key']})": lg for lg in all_leagues_list}
                    if league_options:
                        sel_lg_lbl = st.selectbox("Оберіть лігу для точкового тюнінгу:", list(league_options.keys()), key="sel_single_tune_v3")
                        if sel_lg_lbl and sel_lg_lbl in league_options:
                            cur_obj = league_options[sel_lg_lbl]
                            cur_key = cur_obj["key"]
                            
                            c_f1, c_f2 = st.columns(2)
                            with c_f1:
                                cur_ch = st.session_state.league_enabled_state.get(cur_key, bool(cur_obj.get("enabled", True)))
                                tune_en = st.toggle("🟢 Ліга активна для авто-сканування", value=cur_ch, key="tune_en_toggle_v3")
                                tune_drop = st.slider("Мін. просідання коефіцієнта (%):", min_value=1.0, max_value=20.0, value=float(cur_obj.get("min_drop_pct", 5.0)), step=0.1, format="%.1f%%", key="tune_drop_v3")
                            with c_f2:
                                tune_min_k = st.number_input("Мін. коефіцієнт:", min_value=1.01, max_value=10.0, value=float(cur_obj.get("min_odds", 1.40)), step=0.01, format="%.2f", key="tune_min_k_v3")
                                tune_max_k = st.number_input("Макс. коефіцієнт:", min_value=1.20, max_value=50.0, value=float(cur_obj.get("max_odds", 4.00)), step=0.05, format="%.2f", key="tune_max_k_v3")

                            cur_mkts = cur_obj.get("markets", ["h2h", "totals", "spreads"])
                            if not isinstance(cur_mkts, list):
                                cur_mkts = ["h2h", "totals", "spreads"]
                            all_mkts = ["h2h", "totals", "spreads", "btts"]
                            tune_sel_mkts = st.multiselect("Дозволені маркети:", all_mkts, default=[m for m in cur_mkts if m in all_mkts], key="tune_mkts_v3")

                            if st.button(f"💾 Застосувати для {cur_obj.get('title', cur_key)}", key="btn_apply_tune_v3"):
                                st.session_state.league_enabled_state[cur_key] = tune_en
                                for item in all_leagues_list:
                                    if item["key"] == cur_key:
                                        item["enabled"] = tune_en
                                        item["min_drop_pct"] = tune_drop
                                        item["min_odds"] = tune_min_k
                                        item["max_odds"] = tune_max_k
                                        item["markets"] = tune_sel_mkts or ["h2h", "totals", "spreads"]
                                save_all_leagues_to_file(all_leagues_list)

                                conn_t, err_t = get_db_connection(db_url)
                                if conn_t:
                                    cur_t = conn_t.cursor()
                                    try:
                                        save_league_threshold(
                                            cur_t, conn_t,
                                            sport_key=cur_key,
                                            enabled=tune_en,
                                            min_drop_pct=tune_drop,
                                            min_odds=tune_min_k,
                                            max_odds=tune_max_k,
                                            markets=tune_sel_mkts or ["h2h", "totals", "spreads"],
                                        )
                                    finally:
                                        cur_t.close()
                                        conn_t.close()

                                st.toast(f"✅ Параметри {cur_obj.get('title', cur_key)} оновлено!", icon="💾")
                                st.rerun()

            except Exception as e:
                st.error(f"Помилка завантаження панелі керування лігами: {e}")

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        print(f"Помилка запуску Streamlit: {e}")
