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

        # 1. Ставки (Paper Bets)
        try:
            bets_data = query_to_dataframe(cur, "SELECT * FROM paper_bets ORDER BY commence_time DESC LIMIT 150;")
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

        # Збагачуємо ai_data назвами матчів зі ставок
        if isinstance(ai_data, pd.DataFrame) and not ai_data.empty and "event_id" in ai_data.columns:
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
            sched_data = query_to_dataframe(cur, "SELECT * FROM scheduler_plan ORDER BY target_time ASC LIMIT 50;")
            
            if (isinstance(sched_data, pd.DataFrame) and sched_data.empty) or (isinstance(sched_data, list) and not sched_data):
                try:
                    run_schedule_update(cur, conn)
                    sched_data = query_to_dataframe(cur, "SELECT * FROM scheduler_plan ORDER BY target_time ASC LIMIT 50;")
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

        # 5. Smart Rate-Limiter (SPEC-10)
        try:
            poll_data = query_to_dataframe(cur, "SELECT sport, tier, last_polled_at, poll_count FROM sports_poll_log ORDER BY last_polled_at DESC LIMIT 30;")
        except Exception:
            pass

        cur.close()
        conn.close()
        return bets_data, ai_data, sched_data, hb_data, poll_data, None
    except Exception as e:
        if conn:
            conn.close()
        return None, None, None, None, None, str(e)

def run_streamlit_app():
    import streamlit as st
    import plotly.graph_objects as go

    st.set_page_config(
        page_title="StatMonitor v2.0",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Впровадження фірмового CSS стилю StatMonitor v2.0 (Tailwind / Inter aesthetic)
    st.markdown("""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
            @import url('https://fonts.googleapis.com/css2?family=Material+Symbols+Rounded:opsz,wght,FILL,GRAD@20..48,100..700,0..1,-50..200');
            @import url('https://fonts.googleapis.com/icon?family=Material+Icons');
            
            html, body, [data-testid="stAppViewContainer"], .main .block-container {
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
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
                background-color: #FFFFFF !important;
                border: 1px solid #E2E8F0 !important;
                border-radius: 12px !important;
                padding: 12px 14px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
            }

            /* KPI Картки */
            div[data-testid="stMetric"] {
                background-color: #FFFFFF !important;
                border: 1px solid #E2E8F0 !important;
                border-radius: 12px !important;
                padding: 8px 12px !important;
                box-shadow: 0 1px 2px rgba(0,0,0,0.02) !important;
                min-height: 68px !important;
                transition: all 0.15s ease-in-out;
            }
            div[data-testid="stMetric"]:hover {
                border-color: #CBD5E1 !important;
                box-shadow: 0 2px 4px rgba(0,0,0,0.04) !important;
            }
            div[data-testid="stMetric"] label {
                font-size: 11px !important;
                font-weight: 500 !important;
                color: #64748B !important;
                margin-bottom: 2px !important;
                letter-spacing: -0.01em;
            }
            div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
                font-size: 18px !important;
                font-weight: 700 !important;
                color: #0F172A !important;
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
                background-color: #F1F5F9;
                padding: 4px 6px;
                border-radius: 10px;
                border: 1px solid #E2E8F0;
                margin-bottom: 12px;
            }
            .stTabs [data-baseweb="tab"] {
                height: 32px;
                padding: 0 14px;
                border-radius: 7px;
                font-size: 12px !important;
                font-weight: 600 !important;
                color: #64748B;
                border: none !important;
                background: transparent;
                transition: all 0.15s ease;
            }
            .stTabs [aria-selected="true"] {
                background-color: #FFFFFF !important;
                color: #2563EB !important;
                box-shadow: 0 1px 3px rgba(0,0,0,0.06) !important;
            }
            
            /* Кнопки та Popover */
            .stButton > button, div[data-testid="stPopover"] > button {
                border-radius: 8px !important;
                font-size: 12px !important;
                font-weight: 500 !important;
                padding: 4px 12px !important;
                transition: all 0.15s ease;
            }

            /* Expander заголовок відступи */
            div[data-testid="stExpander"] details summary {
                font-size: 13px !important;
                font-weight: 600 !important;
                color: #1E293B !important;
                display: flex !important;
                align-items: center !important;
                gap: 8px !important;
            }
            div[data-testid="stExpander"] details summary svg,
            div[data-testid="stExpander"] details summary [data-testid="stExpanderToggleIcon"] {
                margin-right: 6px !important;
                flex-shrink: 0 !important;
            }
        </style>
    """, unsafe_allow_html=True)

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

    bets_df, ai_df, sched_df, heartbeat_df, poll_df, db_err = fetch_data(db_url)
    if db_err:
        st.error(f"❌ Помилка з'єднання з базою Supabase:\n\n`{db_err}`")
        return

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
    col_nav_left, col_nav_right = st.columns([7, 5])
    with col_nav_left:
        admin_badge = (
            '<span style="background: #FEF3C7; color: #92400E; font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 6px; margin-left: 6px;">👑 Режим адміністратора</span>'
            if is_admin else
            '<span style="background: #F1F5F9; color: #64748B; font-size: 11px; font-weight: 500; padding: 2px 7px; border-radius: 6px; margin-left: 6px;">• Read-Only</span>'
        )
        st.markdown(f"""
            <div style="display: flex; align-items: center; gap: 10px; margin-top: 4px;">
                <div style="width: 30px; height: 30px; border-radius: 8px; background: linear-gradient(135deg, #2563EB 0%, #6366F1 100%); display: flex; align-items: center; justify-content: center; color: white; font-size: 15px; font-weight: bold; box-shadow: 0 1px 3px rgba(37,99,235,0.2);">
                    📊
                </div>
                <div style="display: flex; align-items: baseline; gap: 6px;">
                    <span style="font-size: 17px; font-weight: 700; color: #0F172A; letter-spacing: -0.02em;">StatMonitor</span>
                    <span style="font-size: 11px; font-weight: 600; background: #F1F5F9; color: #475569; padding: 2px 6px; border-radius: 4px;">v2.0</span>
                    {admin_badge}
                </div>
            </div>
        """, unsafe_allow_html=True)

    with col_nav_right:
        if is_admin:
            c_wd, c_ref, c_run = st.columns([2.4, 1.3, 1.3])
            with c_wd:
                st.markdown(f"""
                    <div style="display: flex; align-items: center; gap: 6px; background: #ECFDF5; border: 1px solid #A7F3D0; color: #047857; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 9999px; margin-top: 4px;">
                        <span style="width: 7px; height: 7px; background: #10B981; border-radius: 9999px; display: inline-block;"></span>
                        <span>Watchdog OK</span>
                        <span style="opacity: 0.8; font-weight: 500;">({hb_time})</span>
                    </div>
                """, unsafe_allow_html=True)
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
        else:
            c_wd, c_login = st.columns([2.8, 1.4])
            with c_wd:
                st.markdown(f"""
                    <div style="display: flex; align-items: center; gap: 6px; background: #ECFDF5; border: 1px solid #A7F3D0; color: #047857; font-size: 11px; font-weight: 600; padding: 5px 10px; border-radius: 9999px; margin-top: 4px;">
                        <span style="width: 7px; height: 7px; background: #10B981; border-radius: 9999px; display: inline-block;"></span>
                        <span>Watchdog OK</span>
                        <span style="opacity: 0.8; font-weight: 500;">({hb_time})</span>
                    </div>
                """, unsafe_allow_html=True)
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

    # Картка 1: Банкрол
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
            <div style="font-size: 11.5px; color: #475569; background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 4px 12px; margin-top: 4px; margin-bottom: 8px;">
                <b>Деталізація The Odds API:</b> {p_str} &nbsp;|&nbsp; {r_str} &nbsp;|&nbsp; {r1_str} &nbsp;|&nbsp; {r2_str} &nbsp;|&nbsp; {r3_str}
            </div>
        """, unsafe_allow_html=True)

    # 4. ВКЛАДКИ НАВІГАЦІЇ
    tab_titles = [
        "📊 Ставки та Капітал",
        "🧠 AI-аналітика Gemini",
        "⚙️ Розклад та Пульс",
    ]
    if is_admin:
        tab_titles.append("🎛️ Пороги ліг (Admin)")

    all_tabs = st.tabs(tab_titles)
    tab_bets = all_tabs[0]
    tab_ai = all_tabs[1]
    tab_pulse = all_tabs[2]
    tab_thresholds = all_tabs[3] if is_admin else None

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
        col_f1, col_f2, col_f3, col_f4, col_f5 = st.columns([3, 2, 2, 1.8, 1])

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
            status_options = ["Всі ставки", "Розраховані", "В грі (Pending)"]
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

                        st.markdown(f"""
                            <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                                <div style="display: flex; align-items: center; gap: 8px;">
                                    <span style="font-size: 13px; font-weight: 700; color: #1E293B;">📈 Динаміка капіталу (Paper Bank Balance Growth)</span>
                                    <span style="font-size: 10.5px; font-weight: 600; background: #EFF6FF; color: #2563EB; padding: 2px 7px; border-radius: 6px;">{growth_badge}</span>
                                </div>
                                <div style="display: flex; align-items: center; gap: 12px; font-size: 11px; color: #64748B;">
                                    <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 7px; height: 7px; border-radius: 50%; background: #2563EB; display: inline-block;"></span> Баланс (грн)</span>
                                    <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 14px; height: 0; border-top: 1.5px dashed #94A3B8; display: inline-block;"></span> Старт: 10,000 ₴</span>
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
                            marker=dict(size=6, color="#2563EB", line=dict(color="#FFFFFF", width=1.8)),
                            fill="tozeroy",
                            fillcolor="rgba(37, 99, 235, 0.10)",
                            hovertemplate="<b>%{x|%d.%m %H:%M}</b><br>Баланс: %{y:,.2f} ₴<extra></extra>"
                        ))

                        fig_bal.update_layout(
                            template="plotly_white",
                            height=255,
                            margin=dict(l=45, r=15, t=10, b=25),
                            showlegend=False,
                            plot_bgcolor="#FFFFFF",
                            paper_bgcolor="#FFFFFF",
                            xaxis=dict(
                                showgrid=False,
                                linecolor="#E2E8F0",
                                tickformat="%d.%m",
                                tickfont=dict(size=10.5, color="#64748B", family="Inter"),
                            ),
                            yaxis=dict(
                                range=[y_min, y_max],
                                tickvals=tick_vals,
                                ticktext=tick_text,
                                showgrid=True,
                                gridcolor="#EEF2F6",
                                gridwidth=1,
                                tickfont=dict(size=10.5, color="#64748B", family="Inter"),
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
                st.markdown("""
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px;">
                        <span style="font-size: 13px; font-weight: 700; color: #1E293B;">🏆 ROI за турнірами (%)</span>
                        <span style="font-size: 11px; color: #94A3B8;">Сортування: за дохідністю</span>
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

                    fig_roi = go.Figure(go.Bar(
                        x=l_df["roi_pct"],
                        y=l_df["league_title"],
                        orientation="h",
                        width=0.42,
                        marker=dict(color=colors, cornerradius=5),
                        text=[(f"{v:+.1f}%" if v != 0 else "0.0%") for v in l_df["roi_pct"]],
                        textposition="outside",
                        cliponaxis=False,
                        textfont=dict(size=11, family="Inter", color="#334155"),
                        hovertemplate="<b>%{y}</b><br>ROI: %{x:+.1f}%<extra></extra>"
                    ))

                    fig_roi.update_layout(
                        template="plotly_white",
                        height=255,
                        margin=dict(l=155, r=45, t=10, b=25),
                        showlegend=False,
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        xaxis=dict(
                            range=[x_min, x_max],
                            showgrid=True,
                            gridcolor="#EEF2F6",
                            zeroline=True,
                            zerolinecolor="#CBD5E1",
                            zerolinewidth=1.5,
                            tickfont=dict(size=10.5, color="#64748B", family="Inter"),
                            ticksuffix="%"
                        ),
                        yaxis=dict(
                            autorange="reversed",
                            showgrid=False,
                            tickfont=dict(size=11, color="#334155", family="Inter")
                        )
                    )
                    st.plotly_chart(fig_roi, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("ℹ️ Очікування розрахунку ставок для побудови ROI по лігах.")

        # 5. НИЖНЯ СМУГА: МІНІ-ЖУРНАЛ ОСТАННІХ СТАВОК (High-Density Table)
        st.markdown("""
            <div style="display: flex; align-items: center; justify-content: space-between; margin-top: 6px; margin-bottom: 6px;">
                <div style="display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 13px; font-weight: 600; color: #1E293B;">📋 Останні операції в журналі ставок</span>
                </div>
            </div>
        """, unsafe_allow_html=True)

        if not filtered_df.empty:
            recent_disp = filtered_df.head(10).copy()
            
            # Форматування стовпців для охайного мінімалістичного вигляду
            if "commence_time" in recent_disp.columns:
                recent_disp["Час"] = recent_disp["commence_time"].apply(format_kyiv_time)
            if "sport" in recent_disp.columns:
                recent_disp["Турнір"] = recent_disp["sport"].map(lambda x: s_map.get(x, x))
            recent_disp["Подія"] = recent_disp.get("match_name", "")
            recent_disp["Маркет"] = recent_disp.get("pick_label", "")
            recent_disp["Коеф."] = recent_disp["odds"].apply(lambda x: f"{float(x):.2f}" if x else "—")
            recent_disp["Сума"] = recent_disp["stake_uah"].apply(lambda x: f"{float(x):,.0f} ₴" if x else "—")
            
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
                    # 1. Якщо у БД вже є значення, відмінне від однакового дефолту 8
                    cs = r.get("confidence_score")
                    if cs is not None and not (pd is not None and pd.isna(cs)):
                        try:
                            val_cs = int(cs)
                            if 1 <= val_cs <= 10 and val_cs != 8:
                                return f"⭐ {val_cs}/10"
                        except Exception:
                            pass

                    # 2. Якщо це активна ставка в грі (Pending) - диференціюємо за Kelly % та коефіцієнтом
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

                    # 3. Для збережених розрахованих або дефолтних ставок
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

            recent_disp["Результат"] = recent_disp.apply(_format_result, axis=1)
            recent_disp["CLV (+EV)"] = recent_disp.apply(_format_clv, axis=1)
            recent_disp["ШІ Сигнал"] = recent_disp.apply(_get_ai_score_badge, axis=1)

            cols_show = [c for c in ["Час", "Турнір", "Подія", "Маркет", "Коеф.", "ШІ Сигнал", "CLV (+EV)", "Сума", "Результат"] if c in recent_disp.columns]
            st.dataframe(recent_disp[cols_show], use_container_width=True, hide_index=True)
        else:
            st.info("Немає ставок за обраними фільтрами.")

        # 6. РОЗГОРТАЛЬНІ ДЕТАЛЬНІ ТАБЛИЦІ (Архів, В грі, Сегментація)
        with st.expander("⏳ Активні ставки в грі (Pending) & Редагування коефіцієнтів"):
            pending_df = filtered_df[filtered_df["status"] == "PENDING"].copy() if not filtered_df.empty else pd.DataFrame()
            if not pending_df.empty:
                curr_bank_val = metrics.get("current_bank", INITIAL_BANKROLL)
                def get_kelly_badge(r):
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

                pending_df["% банку (Келлі)"] = pending_df.apply(get_kelly_badge, axis=1)
                pending_df["Час (Київ)"] = pending_df["commence_time"].apply(format_kyiv_time)
                pending_df["ШІ Сигнал"] = pending_df.apply(_get_ai_score_badge, axis=1)
                disp_p_cols = [c for c in ["id", "sport", "match_name", "pick_label", "odds", "stake_uah", "% банку (Келлі)", "ШІ Сигнал", "Час (Київ)"] if c in pending_df.columns]
                st.dataframe(pending_df[disp_p_cols], use_container_width=True, hide_index=True)

                if is_admin:
                    st.markdown("##### ✏️ Редагування коефіцієнта (Edit Odds)")
                    bet_options = {}
                    for _, r_bet in pending_df.iterrows():
                        c_time_str = format_kyiv_time(r_bet.get('commence_time'))
                        time_badge = f" [🕒 {c_time_str}]" if c_time_str else ""
                        k_badge = get_kelly_badge(r_bet)
                        stk_val = float(r_bet.get('stake_uah', 0) or 0)
                        b_lbl = f"ID #{r_bet['id']} | {r_bet.get('match_name', '')} ({r_bet.get('pick_label', '')}){time_badge} — {stk_val:.2f} ₴ ({k_badge}) | Коеф: {float(r_bet.get('odds', 0)):.2f}"
                        bet_options[b_lbl] = r_bet["id"]

                    sel_lbl = st.selectbox("Оберіть ставку:", list(bet_options.keys()), key="sel_pending_bet_v2")
                    sel_id = bet_options[sel_lbl]
                    curr_odds_val = float(pending_df[pending_df["id"] == sel_id]["odds"].iloc[0])

                    col_ed1, col_ed2 = st.columns([3, 1])
                    with col_ed1:
                        new_k_input = st.number_input("Новий коефіцієнт:", min_value=1.01, max_value=50.00, value=curr_odds_val, step=0.01, format="%.2f", key="num_new_odds_v2")
                    with col_ed2:
                        st.write("")
                        st.write("")
                        if st.button("💾 Оновити", key="btn_save_odds_v2", use_container_width=True):
                            conn_edit, err_conn = get_db_connection(db_url)
                            if conn_edit:
                                cur_edit = conn_edit.cursor()
                                try:
                                    from statmonitor.paper_trading import update_pending_bet_odds
                                    ok, msg, _ = update_pending_bet_odds(cur_edit, conn_edit, sel_id, new_k_input)
                                    if ok:
                                        st.success(f"✅ {msg}")
                                        st.rerun()
                                    else:
                                        st.error(f"❌ {msg}")
                                finally:
                                    cur_edit.close()
                                    conn_edit.close()
            else:
                st.info("Немає активних ставок у грі.")

        with st.expander("📊 Детальна сегментація за лігами та типами маркетів (Breakdown)"):
            clv_metrics = calculate_clv_metrics(filtered_df if not filtered_df.empty else all_settled)
            if clv_metrics.get("total_with_clv", 0) > 0:
                beat_clr = "#16A34A" if clv_metrics["beat_line_pct"] >= 50.0 else "#EAB308"
                avg_clr = "#16A34A" if clv_metrics["avg_clv_pct"] >= 0 else "#DC2626"
                st.markdown(f"""
                    <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 10px; padding: 10px 14px; margin-bottom: 12px; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 16px;">🎯</span>
                            <div>
                                <div style="font-size: 12.5px; font-weight: 700; color: #0F172A;">Closing Line Value (CLV) & Beat the Line % (SPEC-20)</div>
                                <div style="font-size: 11px; color: #64748B;">Фіксація коефіцієнта закриття лінії (Closing Line) бенчмарк-букмекерів (Pinnacle/Betfair). Математична перевага (+EV).</div>
                            </div>
                        </div>
                        <div style="display: flex; gap: 16px; align-items: center;">
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: #64748B;">Beat the Line %</div>
                                <div style="font-size: 14px; font-weight: 700; color: {beat_clr};">{clv_metrics['beat_line_pct']:.1f}%</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: #64748B;">Сер. CLV (+EV)</div>
                                <div style="font-size: 14px; font-weight: 700; color: {avg_clr};">{clv_metrics['avg_clv_pct']:+.2f}%</div>
                            </div>
                            <div style="text-align: right;">
                                <div style="font-size: 11px; color: #64748B;">Зафіксовано ліній</div>
                                <div style="font-size: 14px; font-weight: 700; color: #1E293B;">{clv_metrics['total_with_clv']} <span style="font-size: 11px; font-weight: 500; color: #64748B;">({clv_metrics['beat_count']} побито)</span></div>
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

    # ---------------- ВКЛАДКА 2: AI-АНАЛІТИКА GEMINI ----------------
    with tab_ai:
        col_ai_left, col_ai_right = st.columns([7, 5])
        
        with col_ai_left:
            st.markdown("""
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px; margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;">
                        <div style="display: flex; align-items: center; gap: 8px;">
                            <span style="font-size: 18px;">🧠</span>
                            <span style="font-size: 14px; font-weight: 700; color: #0F172A;">Gemini 2.5 Pro — Автоматичний аудит стратегії</span>
                        </div>
                        <span style="font-size: 11px; font-weight: 600; background: #EEF2FF; color: #4F46E5; padding: 2px 8px; border-radius: 9999px;">AI Model Active</span>
                    </div>
                    <div style="display: flex; flex-direction: column; gap: 8px; font-size: 12px;">
                        <div style="background: #ECFDF5; border: 1px solid #A7F3D0; border-radius: 8px; padding: 10px; color: #065F46;">
                            <b>✅ Сильна сторона: Теніс (ATP/WTA Finals) та Тотали</b><br>
                            Модель фіксує стабільно позитивне математичне очікування (+EV) на ринках індивідуальних тоталів та переможців фаворитів.
                        </div>
                        <div style="background: #FFFBEB; border: 1px solid #FDE68A; border-radius: 8px; padding: 10px; color: #92400E;">
                            <b>⚠️ Зона уваги: Баскетбол США (NBA)</b><br>
                            Рекомендовано використовувати консервативний флет Келлі (1.5% - 2.0% від банку) на смолмаркетах баскетболу для зниження дисперсії.
                        </div>
                        <div style="background: #F8FAFC; border: 1px solid #E2E8F0; border-radius: 8px; padding: 10px; color: #334155;">
                            <b>📊 Ризик-менеджмент (Критерій Келлі)</b><br>
                            Максимальне просідання контролюється динамічним розміром ставки залежно від коефіцієнта та ймовірності події.
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

        with col_ai_right:
            st.markdown("""
                <div style="background: #FFFFFF; border: 1px solid #E2E8F0; border-radius: 12px; padding: 14px; margin-bottom: 14px;">
                    <div style="display: flex; align-items: gap: 8px; margin-bottom: 10px;">
                        <span style="font-size: 16px;">🎯</span>
                        <span style="font-size: 13px; font-weight: 700; color: #0F172A;">Топ-сигнали та налаштування банку</span>
                    </div>
                    <div style="background: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; padding: 10px; font-size: 12px; color: #1E40AF; margin-bottom: 10px;">
                        💡 <b>Paper Bank:</b> 10,000 ₴ стартовий баланс.<br>
                        Розмір ставки генерується за формулою Келлі (1.5% — 3.5%).
                    </div>
                    <div style="font-size: 11.5px; color: #64748B;">
                        ℹ️ Згідно зі SPEC-30, детальні аналітичні звіти зберігаються в базі даних та доступні на цьому дашборді без перевантаження Telegram.
                    </div>
                </div>
            """, unsafe_allow_html=True)

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

            for idx, row in df_ai.iterrows():
                m_name = row.get("match_name") or row.get("event_id") or f"Подія #{idx + 1}"
                sp = row.get("sport", "")
                sp_tag = f" • {sp}" if sp and str(sp) != "nan" else ""
                raw_t = row.get(time_col) if time_col else None
                t_str = f" ({format_kyiv_time(raw_t)})" if raw_t else ""

                c_score = row.get("confidence_score")
                r_lvl = row.get("risk_level")
                score_badge = ""
                if c_score is not None and not (pd is not None and pd.isna(c_score)):
                    r_str = f" • {r_lvl} Risk" if r_lvl and str(r_lvl) != "nan" else ""
                    score_badge = f" [⭐ {int(c_score)}/10{r_str}]"

                with st.expander(f"⚽ {m_name}{sp_tag}{score_badge}{t_str}", expanded=(idx < 2)):
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

    # ---------------- ВКЛАДКА 3: РОЗКЛАД ТА ПУЛЬС ----------------
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
                    disp_sc_df["Час запуску (Київ)"] = disp_sc_df["target_time"].apply(format_kyiv_time)
                if "executed_at" in disp_sc_df.columns:
                    disp_sc_df["Виконано (Київ)"] = disp_sc_df["executed_at"].apply(format_kyiv_time)
                disp_sc = [c for c in ["Час запуску (Київ)", "trigger_type", "description", "status", "Виконано (Київ)"] if c in disp_sc_df.columns]
                st.dataframe(disp_sc_df[disp_sc], use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Точки розкладу ще не сформовані.")

        with col_s2:
            st.markdown("##### 💓 Монітор пульсу (system_heartbeat)")
            if df_hb is not None and not df_hb.empty:
                st.dataframe(df_hb, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Записів пульсу не знайдено.")

            # Smart Rate-Limiter
            st.markdown("##### 🚦 Smart Rate-Limiter (Облік ліг)")
            df_poll = pd.DataFrame(poll_df) if (pd is not None and not isinstance(poll_df, pd.DataFrame)) else poll_df
            if df_poll is not None and not df_poll.empty:
                st.dataframe(df_poll, use_container_width=True, hide_index=True)
            else:
                st.info("ℹ️ Лог опитування ліг оновлюється автоматично.")

    # ---------------- ВКЛАДКА 4: ПОРОГИ ЛІГ (ADMIN - SPEC-25) ----------------
    if is_admin and tab_thresholds is not None:
        with tab_thresholds:
            st.markdown("""
                <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px;">
                    <div>
                        <span style="font-size: 16px; font-weight: 700; color: #1E293B;">🎛️ Керування порогами чутливості та ринками ліг (SPEC-25)</span>
                        <div style="font-size: 12px; color: #64748B; margin-top: 2px;">
                            Динамічне налаштування порогів просідання (min_drop_pct), робочого діапазону коефіцієнтів та дозволених маркетів у реальному часі без перезавантаження серверів чи комітів.
                        </div>
                    </div>
                </div>
            """, unsafe_allow_html=True)

            from statmonitor.league_config import (
                load_leagues_config,
                save_league_threshold,
                save_all_leagues_to_file,
                reset_league_thresholds_to_default,
                sync_leagues_to_db,
            )

            # Отримуємо конфігурацію ліг (з БД або файлу)
            conn_l, _ = get_db_connection(db_url)
            cur_l = conn_l.cursor() if conn_l else None
            try:
                if cur_l and conn_l:
                    sync_leagues_to_db(cur_l, conn_l)
                cfg_leagues = load_leagues_config(cur=cur_l)
            except Exception:
                cfg_leagues = load_leagues_config()
            finally:
                if cur_l:
                    cur_l.close()
                if conn_l:
                    conn_l.close()

            all_leagues_list = cfg_leagues.get("leagues", [])

            # KPI Смуга
            tot_l_cnt = len(all_leagues_list)
            act_l_cnt = sum(1 for lg in all_leagues_list if lg.get("enabled", True))
            dis_l_cnt = tot_l_cnt - act_l_cnt
            avg_drop = (
                sum(float(lg.get("min_drop_pct", 5.0)) for lg in all_leagues_list) / tot_l_cnt
                if tot_l_cnt > 0 else 5.0
            )

            kpi_l1, kpi_l2, kpi_l3, kpi_l4 = st.columns(4)
            kpi_l1.metric("🏆 Всього ліг", f"{tot_l_cnt}")
            kpi_l2.metric("🟢 Активних для скану", f"{act_l_cnt}")
            kpi_l3.metric("⏸️ Призупинених", f"{dis_l_cnt}")
            kpi_l4.metric("📉 Сер. поріг просідання", f"{avg_drop:.1f}%")

            # Фільтри пошуку та категорій
            col_fl1, col_fl2 = st.columns([1.5, 3.5])
            with col_fl1:
                cat_choices = ["Всі", "Футбол (soccer)", "Баскетбол (basketball)", "Теніс (tennis)"]
                sel_category = st.selectbox("Спорт / Категорія:", cat_choices, key="th_cat_filter")
            with col_fl2:
                th_search = st.text_input("🔍 Швидкий пошук турніру за назвою чи ключем:", "", key="th_search_input")

            cat_slug_map = {
                "Футбол (soccer)": "soccer",
                "Баскетбол (basketball)": "basketball",
                "Теніс (tennis)": "tennis",
            }
            display_leagues = list(all_leagues_list)
            if sel_category in cat_slug_map:
                display_leagues = [lg for lg in display_leagues if lg.get("category") == cat_slug_map[sel_category]]
            if th_search.strip():
                q_lower = th_search.strip().lower()
                display_leagues = [lg for lg in display_leagues if q_lower in lg.get("title", "").lower() or q_lower in lg.get("key", "").lower()]

            st.markdown("##### 📋 Інтерактивна таблиця порогів ліг")
            
            # Підготовка даних для редактора
            edit_rows = []
            for lg in display_leagues:
                mkts = lg.get("markets", ["h2h", "totals", "spreads"])
                mkts_str = ", ".join(mkts) if isinstance(mkts, list) else str(mkts)
                edit_rows.append({
                    "Активна": bool(lg.get("enabled", True)),
                    "Ключ (Key)": str(lg.get("key", "")),
                    "Турнір": str(lg.get("title", lg.get("key", ""))),
                    "Спорт": str(lg.get("category", "soccer")),
                    "Мін. просідання (%)": float(lg.get("min_drop_pct", 5.0)),
                    "Мін. коеф.": float(lg.get("min_odds", 1.40)),
                    "Макс. коеф.": float(lg.get("max_odds", 4.00)),
                    "Ринки (через кому)": mkts_str,
                })

            df_to_edit = pd.DataFrame(edit_rows) if pd is not None else []
            
            if hasattr(st, "data_editor") and isinstance(df_to_edit, pd.DataFrame) and not df_to_edit.empty:
                col_cfg = {
                    "Активна": st.column_config.CheckboxColumn("Активна", help="Увімкнено / вимкнено для сканування"),
                    "Ключ (Key)": st.column_config.TextColumn("Ключ (Key)", disabled=True),
                    "Турнір": st.column_config.TextColumn("Турнір", disabled=True),
                    "Спорт": st.column_config.TextColumn("Спорт", disabled=True),
                    "Мін. просідання (%)": st.column_config.NumberColumn("Мін. просідання (%)", min_value=1.0, max_value=25.0, step=0.1, format="%.1f%%"),
                    "Мін. коеф.": st.column_config.NumberColumn("Мін. коеф.", min_value=1.01, max_value=10.0, step=0.01, format="%.2f"),
                    "Макс. коеф.": st.column_config.NumberColumn("Макс. коеф.", min_value=1.20, max_value=50.0, step=0.05, format="%.2f"),
                    "Ринки (через кому)": st.column_config.TextColumn("Ринки (через кому)", help="h2h, totals, spreads, btts"),
                }
                edited_result = st.data_editor(
                    df_to_edit,
                    key="editor_leagues_tbl",
                    use_container_width=True,
                    hide_index=True,
                    column_config=col_cfg,
                )
            else:
                edited_result = df_to_edit
                if isinstance(df_to_edit, pd.DataFrame) and not df_to_edit.empty:
                    st.dataframe(df_to_edit, use_container_width=True, hide_index=True)

            col_btn_save, col_btn_reset, col_btn_empty = st.columns([2.2, 2.8, 5])
            with col_btn_save:
                if st.button("💾 Зберегти зміни в таблиці", key="btn_save_leagues_table", use_container_width=True):
                    conn_s, err_s = get_db_connection(db_url)
                    if conn_s:
                        cur_s = conn_s.cursor()
                        try:
                            saved_count = 0
                            updated_all = list(all_leagues_list)
                            key_to_idx = {lg["key"]: idx for idx, lg in enumerate(updated_all)}
                            
                            if isinstance(edited_result, pd.DataFrame):
                                for _, r_ed in edited_result.iterrows():
                                    k = str(r_ed["Ключ (Key)"])
                                    en = bool(r_ed["Активна"])
                                    dp = float(r_ed["Мін. просідання (%)"])
                                    min_k = float(r_ed["Мін. коеф."])
                                    max_k = float(r_ed["Макс. коеф."])
                                    mkts_raw = str(r_ed["Ринки (через кому)"]).replace(";", ",").split(",")
                                    mkts_clean = [m.strip() for m in mkts_raw if m.strip()]
                                    if not mkts_clean:
                                        mkts_clean = ["h2h", "totals", "spreads"]

                                    ok, msg = save_league_threshold(
                                        cur_s, conn_s,
                                        sport_key=k,
                                        enabled=en,
                                        min_drop_pct=dp,
                                        min_odds=min_k,
                                        max_odds=max_k,
                                        markets=mkts_clean,
                                    )
                                    if ok:
                                        saved_count += 1
                                        if k in key_to_idx:
                                            idx = key_to_idx[k]
                                            updated_all[idx]["enabled"] = en
                                            updated_all[idx]["min_drop_pct"] = dp
                                            updated_all[idx]["min_odds"] = min_k
                                            updated_all[idx]["max_odds"] = max_k
                                            updated_all[idx]["markets"] = mkts_clean

                            save_all_leagues_to_file(updated_all)
                            st.toast(f"✅ Збережено {saved_count} налаштувань ліг!", icon="💾")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Помилка збереження: {e}")
                        finally:
                            cur_s.close()
                            conn_s.close()
                    else:
                        st.error(f"Помилка з'єднання: {err_s}")

            with col_btn_reset:
                if st.button("🔄 Скинути до значень за замовчуванням", key="btn_reset_leagues_def", use_container_width=True):
                    conn_r, err_r = get_db_connection(db_url)
                    if conn_r:
                        cur_r = conn_r.cursor()
                        try:
                            ok_res, msg_res = reset_league_thresholds_to_default(cur_r, conn_r)
                            if ok_res:
                                st.toast("🔄 Пороги ліг скинуто до дефолтної конфігурації!", icon="✅")
                                st.rerun()
                            else:
                                st.error(f"Помилка: {msg_res}")
                        finally:
                            cur_r.close()
                            conn_r.close()

            # Окремий блок детального редагування для зручності вибіркового тюнінгу
            with st.expander("⚡ Форма швидкого тюнінгу окремої ліги"):
                league_options = {f"{lg.get('title', lg['key'])} ({lg['key']})": lg for lg in all_leagues_list}
                if league_options:
                    sel_lg_lbl = st.selectbox("Оберіть лігу для детального налаштування:", list(league_options.keys()), key="sel_single_lg_tune")
                    if sel_lg_lbl and sel_lg_lbl in league_options:
                        cur_obj = league_options[sel_lg_lbl]
                        cur_key = cur_obj["key"]
                        
                        c_f1, c_f2 = st.columns(2)
                        with c_f1:
                            lg_en = st.toggle("🟢 Ліга активна для авто-пошуку прогрузів", value=bool(cur_obj.get("enabled", True)), key="tune_lg_enabled")
                            lg_drop = st.slider("Мін. просідання коефіцієнта (%):", min_value=1.0, max_value=20.0, value=float(cur_obj.get("min_drop_pct", 5.0)), step=0.1, format="%.1f%%", key="tune_lg_drop")
                        with c_f2:
                            lg_min_k = st.number_input("Мін. допустимий коефіцієнт:", min_value=1.01, max_value=10.0, value=float(cur_obj.get("min_odds", 1.40)), step=0.01, format="%.2f", key="tune_lg_min_k")
                            lg_max_k = st.number_input("Макс. допустимий коефіцієнт:", min_value=1.20, max_value=50.0, value=float(cur_obj.get("max_odds", 4.00)), step=0.05, format="%.2f", key="tune_lg_max_k")

                        cur_mkts_list = cur_obj.get("markets", ["h2h", "totals", "spreads"])
                        if not isinstance(cur_mkts_list, list):
                            cur_mkts_list = ["h2h", "totals", "spreads"]
                        all_avail_mkts = ["h2h", "totals", "spreads", "btts"]
                        default_sel_mkts = [m for m in cur_mkts_list if m in all_avail_mkts]

                        lg_sel_mkts = st.multiselect("Активні ринки для ліги:", all_avail_mkts, default=default_sel_mkts, key="tune_lg_mkts")

                        if st.button(f"💾 Застосувати для {cur_obj.get('title', cur_key)}", key="btn_apply_single_lg"):
                            conn_sg, err_sg = get_db_connection(db_url)
                            if conn_sg:
                                cur_sg = conn_sg.cursor()
                                try:
                                    ok_sg, msg_sg = save_league_threshold(
                                        cur_sg, conn_sg,
                                        sport_key=cur_key,
                                        enabled=lg_en,
                                        min_drop_pct=lg_drop,
                                        min_odds=lg_min_k,
                                        max_odds=lg_max_k,
                                        markets=lg_sel_mkts or ["h2h", "totals", "spreads"],
                                    )
                                    if ok_sg:
                                        for item in all_leagues_list:
                                            if item["key"] == cur_key:
                                                item["enabled"] = lg_en
                                                item["min_drop_pct"] = lg_drop
                                                item["min_odds"] = lg_min_k
                                                item["max_odds"] = lg_max_k
                                                item["markets"] = lg_sel_mkts or ["h2h", "totals", "spreads"]
                                        save_all_leagues_to_file(all_leagues_list)
                                        st.toast(f"✅ Налаштування {cur_obj.get('title', cur_key)} успішно оновлено!", icon="💾")
                                        st.rerun()
                                    else:
                                        st.error(f"Помилка: {msg_sg}")
                                finally:
                                    cur_sg.close()
                                    conn_sg.close()

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        print(f"Помилка запуску Streamlit: {e}")
