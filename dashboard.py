import os
import sys
from datetime import datetime, timezone, timedelta
import psycopg2

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

from decimal import Decimal

def get_db_connection(db_url):
    if not db_url:
        return None, "URL бази даних порожній"
    try:
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

    net_profit = sum(float(b.get("profit_uah", 0.0)) for b in bets if b.get("status") in ("WON", "LOST", "VOID"))
    turnover = sum(float(b.get("stake_uah", 0.0)) for b in bets if b.get("status") in ("WON", "LOST", "VOID"))

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

def fetch_data(db_url):
    """
    Завантажує дані з Supabase PostgreSQL.
    Повертає (bets_df, ai_df, sched_df, heartbeat_df, error_msg)
    """
    conn, err = get_db_connection(db_url)
    if not conn:
        return None, None, None, None, err

    bets_data = pd.DataFrame() if pd is not None else []
    ai_data = pd.DataFrame() if pd is not None else []
    sched_data = pd.DataFrame() if pd is not None else []
    hb_data = pd.DataFrame() if pd is not None else []

    try:
        cur = conn.cursor()
        # 1. Ставки
        try:
            bets_data = query_to_dataframe(cur, "SELECT * FROM paper_bets ORDER BY commence_time DESC LIMIT 100;")
        except Exception as e:
            print("Bets query err:", e)

        # 2. AI вердикти
        try:
            ai_data = query_to_dataframe(
                cur,
                """
                SELECT a.event_id, a.verdict_text, a.created_at, e.sport,
                       COALESCE(e.home_team || ' - ' || e.away_team, e.sport) AS match_name,
                       e.commence_time
                FROM ai_match_analysis a
                LEFT JOIN events e ON a.event_id = e.id
                ORDER BY a.created_at DESC LIMIT 30;
                """,
            )
        except Exception as e:
            print("AI query err:", e)

        # 3. Розклад
        try:
            sched_data = query_to_dataframe(cur, "SELECT * FROM scheduler_plan ORDER BY target_time ASC LIMIT 25;")
        except Exception as e:
            print("Sched query err:", e)

        # 4. Пульс
        try:
            hb_data = query_to_dataframe(cur, "SELECT * FROM system_heartbeat WHERE service_name='StatMonitor';")
        except Exception as e:
            print("Heartbeat query err:", e)

        cur.close()
        conn.close()
        return bets_data, ai_data, sched_data, hb_data, None
    except Exception as e:
        conn.close()
        return None, None, None, None, str(e)

def run_streamlit_app():
    import streamlit as st
    import plotly.express as px

    st.set_page_config(
        page_title="StatMonitor Dashboard",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # Приховуємо ліву панель для чистого повноекранного інтерфейсу
    st.markdown("""
        <style>
            [data-testid="stSidebar"] { display: none; }
            [data-testid="collapsedControl"] { display: none; }
            .block-container { padding-top: 1.8rem; padding-bottom: 2rem; }
        </style>
    """, unsafe_allow_html=True)

    # Автоматичне читання налаштувань зі Streamlit Secrets або env
    db_url = ""
    secret_key = ""
    try:
        db_url = st.secrets.get("SUPABASE_DB_URL", "")
        secret_key = st.secrets.get("SECRET_KEY", "")
    except Exception:
        pass
    db_url = db_url or os.environ.get("SUPABASE_DB_URL", "")
    secret_key = secret_key or os.environ.get("SECRET_KEY", "")

    # Завантаження даних
    if not db_url:
        st.warning("⚠️ Будь ласка, додайте `SUPABASE_DB_URL` у Streamlit Secrets.")
        st.info("💡 Підказка: у правому верхньому кутку відкрийте `Settings` -> `Secrets` і збережіть `SUPABASE_DB_URL`.")
        return

    bets_df, ai_df, sched_df, heartbeat_df, db_err = fetch_data(db_url)
    if db_err:
        st.error(f"❌ Помилка з'єднання з базою Supabase:\n\n`{db_err}`")
        st.info("💡 Підказка: перевірте наявність правильного рядка підключення через Pooler у Secrets.")
    metrics = compute_metrics(bets_df)

    # 1. Шапка з кнопками дій
    col_title, col_btn_refresh, col_btn_run = st.columns([6, 2, 2])
    with col_title:
        st.title("📊 Моніторинг та аналітика системи")
        st.caption("StatMonitor — інтелектуальна платформа спортивного моніторингу та трейдингу v2.0")
    
    with col_btn_refresh:
        st.write("")
        if st.button("🔄 Оновити дані", use_container_width=True):
            st.rerun()

    with col_btn_run:
        st.write("")
        if st.button("⚡ Запустити моніторинг", use_container_width=True):
            try:
                import requests
                trigger_url = "https://statmonitor.symchak.workers.dev"
                if secret_key:
                    resp = requests.get(f"{trigger_url}/?secret={secret_key}&source=dashboard_button", timeout=12)
                    if resp.status_code == 200:
                        st.toast("🚀 Моніторинг успішно запущено!", icon="✅")
                    else:
                        st.error(f"Помилка [{resp.status_code}]: {resp.text[:120]}")
                else:
                    st.warning("Вкажіть SECRET_KEY у Secrets для запуску через вебхук.")
            except Exception as e:
                st.error(f"Помилка виклику: {e}")

    st.markdown("---")

    # 2. Верхній блок KPI карток
    col1, col2, col3, col4 = st.columns(4)

    delta_bank = metrics["net_profit"]
    col1.metric(
        label="💰 Банкрол (Paper Bank)",
        value=f"{metrics['current_bank']:,.2f} грн",
        delta=f"{delta_bank:+,.2f} грн" if delta_bank != 0 else None,
    )

    col2.metric(
        label="📈 ROI / Оборот",
        value=f"{metrics['roi_pct']:+.2f}%",
        delta=f"Оборот: {metrics['turnover']:,.0f} грн",
    )

    col3.metric(
        label="🎯 Вінрейт (Win Rate)",
        value=f"{metrics['win_rate']:.1f}%",
        delta=f"Всього: {metrics['total_bets']} (в грі: {metrics['pending']})",
    )

    hb_status = "🟢 Норма"
    hb_time = "Немає даних"
    if heartbeat_df is not None and not heartbeat_df.empty:
        hb_row = heartbeat_df.iloc[0]
        t_raw = hb_row.get("last_ping_at")
        if t_raw:
            hb_time = t_raw.strftime("%d.%m %H:%M") if hasattr(t_raw, "strftime") else str(t_raw)[:16]
        hb_status = f"🟢 {hb_row.get('last_status', 'OK')}"

    col4.metric(
        label="💓 Пульс системи (Watchdog)",
        value=hb_status,
        delta=f"Останній чек: {hb_time}",
    )

    st.markdown("---")

    # 2. Вкладки інтерфейсу
    tab_bets, tab_ai, tab_sched = st.tabs([
        "💼 Ставки та Капітал",
        "🧠 AI-аналітика Gemini",
        "⚙️ Розклад та Пульс",
    ])

    # Вкладка 1: Ставки
    with tab_bets:
        df_all = pd.DataFrame(bets_df) if (pd is not None and not isinstance(bets_df, pd.DataFrame)) else bets_df

        # Графік кумулятивного прибутку
        try:
            if df_all is not None and not df_all.empty:
                settled_df = df_all[df_all["status"].isin(["WON", "LOST", "VOID"])].copy()
                if not settled_df.empty and "settled_at" in settled_df.columns:
                    settled_df = settled_df.dropna(subset=["settled_at"]).sort_values(by="settled_at", ascending=True)
                    if not settled_df.empty:
                        settled_df["profit_uah"] = settled_df["profit_uah"].astype(float)
                        settled_df["cum_profit"] = settled_df["profit_uah"].cumsum()
                        settled_df["balance"] = float(INITIAL_BANKROLL) + settled_df["cum_profit"]

                        fig = px.line(
                            settled_df,
                            x="settled_at",
                            y="balance",
                            title="📈 Динаміка капіталу (Paper Bank Balance Growth)",
                            markers=True,
                            labels={"settled_at": "Дата розрахунку", "balance": "Баланс (грн)"},
                        )
                        fig.update_layout(template="plotly_dark", height=380)
                        st.plotly_chart(fig, use_container_width=True)
        except Exception as chart_err:
            st.warning(f"Графік очікує даних: {chart_err}")

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.subheader("⏳ Активні ставки в грі (Pending)")
            try:
                if df_all is not None and not df_all.empty:
                    pending_df = df_all[df_all["status"] == "PENDING"]
                    if not pending_df.empty:
                        disp_cols = [c for c in ["sport", "match_name", "pick_label", "odds", "stake_uah", "commence_time"] if c in pending_df.columns]
                        st.dataframe(pending_df[disp_cols], use_container_width=True, hide_index=True)
                    else:
                        st.info("Наразі немає відкритих ставок у грі.")
                else:
                    st.info("Дані відсутні.")
            except Exception as e:
                st.error(f"Помилка таблиці ставок: {e}")

        with col_right:
            st.subheader("📋 Історія розрахованих ставок")
            try:
                if df_all is not None and not df_all.empty:
                    settled_df = df_all[df_all["status"].isin(["WON", "LOST", "VOID"])]
                    if not settled_df.empty:
                        disp_cols = [c for c in ["match_name", "pick_label", "odds", "stake_uah", "match_score", "status", "profit_uah"] if c in settled_df.columns]
                        st.dataframe(settled_df[disp_cols], use_container_width=True, hide_index=True)
                    else:
                        st.info("Історія розрахунків порожня.")
                else:
                    st.info("Дані відсутні.")
            except Exception as e:
                st.error(f"Помилка таблиці історії: {e}")

    # Вкладка 2: AI-аналітика Gemini
    with tab_ai:
        st.subheader("🤖 Останні AI-вердикти та рекомендації матчів")
        df_ai = pd.DataFrame(ai_df) if (pd is not None and not isinstance(ai_df, pd.DataFrame)) else ai_df
        if df_ai is not None and not df_ai.empty:
            for _, row in df_ai.iterrows():
                with st.expander(f"⚽ {row.get('match_name', 'Матч')} ({row.get('sport', '')}) — {str(row.get('created_at', ''))[:16]}"):
                    st.markdown(row.get("verdict_text", "Текст аналізу відсутній"))
        else:
            st.info("AI-вердикти поки що не збережені в базі даних.")

    # Вкладка 3: Планувальник та здоров'я
    with tab_sched:
        col_s1, col_s2 = st.columns([1, 1])
        df_sched = pd.DataFrame(sched_df) if (pd is not None and not isinstance(sched_df, pd.DataFrame)) else sched_df
        df_hb = pd.DataFrame(heartbeat_df) if (pd is not None and not isinstance(heartbeat_df, pd.DataFrame)) else heartbeat_df

        with col_s1:
            st.subheader("⏰ Контрольні точки розкладу (scheduler_plan)")
            if df_sched is not None and not df_sched.empty:
                disp_sc = [c for c in ["target_time", "trigger_type", "description", "status"] if c in df_sched.columns]
                st.dataframe(df_sched[disp_sc], use_container_width=True, hide_index=True)
            else:
                st.info("Точки розкладу ще не сформовані.")

        with col_s2:
            st.subheader("💓 Монітор пульсу (system_heartbeat)")
            if df_hb is not None and not df_hb.empty:
                st.dataframe(df_hb, use_container_width=True, hide_index=True)
            else:
                st.info("Записів пульсу не знайдено.")

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        print(f"Помилка запуску Streamlit: {e}")
