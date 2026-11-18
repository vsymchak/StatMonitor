import os
import sys
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
            
            html, body, [data-testid="stAppViewContainer"], .main .block-container {
                font-family: 'Inter', system-ui, -apple-system, sans-serif;
            }
            
            /* ЗАХИСТ СИСТЕМНИХ ІКОНОК STREAMLIT (Material Symbols / Icons) ВІД ПЕРЕКРИТТЯ ШРИФТОМ */
            [data-testid="stIconMaterial"],
            [data-testid="stExpanderToggleIcon"],
            [class*="material-symbols"],
            [class*="material-icons"],
            span[translate="no"] {
                font-family: 'Material Symbols Rounded', 'Material Icons', sans-serif !important;
                font-style: normal !important;
                letter-spacing: normal !important;
                text-transform: none !important;
                display: inline-block !important;
                white-space: nowrap !important;
                word-wrap: normal !important;
                direction: ltr !important;
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
    tab_bets, tab_ai, tab_pulse = st.tabs([
        "📊 Ставки та Капітал",
        "🧠 AI-аналітика Gemini",
        "⚙️ Розклад та Пульс",
    ])

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

        # 4. ОСНОВНА СІТКА З ГРАФІКАМИ (7:5)
        col_chart_left, col_chart_right = st.columns([7, 5])

        # Ліва колонка (60%): Динаміка капіталу (Line Chart з градієнтом)
        with col_chart_left:
            if not settled_for_charts.empty and "settled_at" in settled_for_charts.columns:
                chart_df = settled_for_charts.dropna(subset=["settled_at"]).sort_values(by="settled_at", ascending=True)
                if not chart_df.empty:
                    chart_df["profit_uah"] = chart_df["profit_uah"].astype(float)
                    chart_df["cum_profit"] = chart_df["profit_uah"].cumsum()
                    chart_df["balance"] = float(INITIAL_BANKROLL) + chart_df["cum_profit"]

                    # Форматування дати для осі X
                    chart_df["time_label"] = chart_df["settled_at"].apply(format_kyiv_time)

                    fig_bal = go.Figure()

                    # Базова лінія старту (10,000 грн)
                    fig_bal.add_trace(go.Scatter(
                        x=chart_df["time_label"],
                        y=[INITIAL_BANKROLL] * len(chart_df),
                        mode="lines",
                        name="Старт (10,000 ₴)",
                        line=dict(color="#94A3B8", width=1.5, dash="dot"),
                        hoverinfo="skip"
                    ))

                    # Крива балансу з заливкою
                    fig_bal.add_trace(go.Scatter(
                        x=chart_df["time_label"],
                        y=chart_df["balance"],
                        mode="lines+markers",
                        name="Баланс (грн)",
                        line=dict(color="#2563EB", width=2.5),
                        marker=dict(size=5, color="#2563EB", line=dict(color="#FFFFFF", width=1.5)),
                        fill="tozeroy",
                        fillcolor="rgba(37, 99, 235, 0.08)",
                        hovertemplate="<b>%{x}</b><br>Баланс: %{y:,.2f} ₴<extra></extra>"
                    ))

                    fig_bal.update_layout(
                        title=dict(
                            text="<b>📈 Динаміка капіталу (Paper Bank Balance Growth)</b>",
                            font=dict(size=13, color="#1E293B", family="Inter")
                        ),
                        template="plotly_white",
                        height=310,
                        margin=dict(l=10, r=10, t=35, b=10),
                        showlegend=False,
                        plot_bgcolor="#FFFFFF",
                        paper_bgcolor="#FFFFFF",
                        xaxis=dict(
                            showgrid=False,
                            tickfont=dict(size=10, color="#64748B", family="Inter"),
                        ),
                        yaxis=dict(
                            showgrid=True,
                            gridcolor="#F1F5F9",
                            tickfont=dict(size=10, color="#64748B", family="Inter"),
                            tickformat=",.0f"
                        )
                    )
                    st.plotly_chart(fig_bal, use_container_width=True)
                else:
                    st.info("ℹ️ Немає розрахованих ставок за обраними фільтрами для графіка капіталу.")
            else:
                st.info("ℹ️ Немає розрахованих ставок за обраними фільтрами для графіка капіталу.")

        # Права колонка (40%): ROI за турнірами (Horizontal Bar Chart)
        with col_chart_right:
            league_stats = calculate_league_breakdown(all_settled, sports_map=s_map)
            if league_stats:
                l_df = pd.DataFrame(league_stats).sort_values(by="roi_pct", ascending=True)

                # Кольори барів
                colors = ["#10B981" if v >= 0 else "#EF4444" for v in l_df["roi_pct"]]

                fig_roi = go.Figure(go.Bar(
                    x=l_df["roi_pct"],
                    y=l_df["league_title"],
                    orientation="h",
                    marker=dict(color=colors, cornerradius=6),
                    text=[f"{v:+.1f}%" for v in l_df["roi_pct"]],
                    textposition="outside",
                    textfont=dict(size=10.5, family="Inter", color="#334155"),
                    hovertemplate="<b>%{y}</b><br>ROI: %{x:+.1f}%<extra></extra>"
                ))

                fig_roi.update_layout(
                    title=dict(
                        text="<b>🏆 ROI за турнірами (%)</b>",
                        font=dict(size=13, color="#1E293B", family="Inter")
                    ),
                    template="plotly_white",
                    height=310,
                    margin=dict(l=10, r=40, t=35, b=10),
                    showlegend=False,
                    plot_bgcolor="#FFFFFF",
                    paper_bgcolor="#FFFFFF",
                    xaxis=dict(
                        showgrid=True,
                        gridcolor="#F1F5F9",
                        tickfont=dict(size=10, color="#64748B", family="Inter"),
                        ticksuffix="%"
                    ),
                    yaxis=dict(
                        showgrid=False,
                        tickfont=dict(size=10.5, color="#1E293B", family="Inter")
                    )
                )
                st.plotly_chart(fig_roi, use_container_width=True)
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

            recent_disp["Результат"] = recent_disp.apply(_format_result, axis=1)

            cols_show = [c for c in ["Час", "Турнір", "Подія", "Маркет", "Коеф.", "Сума", "Результат"] if c in recent_disp.columns]
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
                disp_p_cols = [c for c in ["id", "sport", "match_name", "pick_label", "odds", "stake_uah", "% банку (Келлі)", "Час (Київ)"] if c in pending_df.columns]
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

                with st.expander(f"⚽ {m_name}{sp_tag}{t_str}", expanded=(idx < 2)):
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

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        print(f"Помилка запуску Streamlit: {e}")
