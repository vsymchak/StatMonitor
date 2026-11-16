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

def get_db_connection(db_url):
    if not db_url:
        return None
    try:
        return psycopg2.connect(db_url)
    except Exception as e:
        return None

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
    """
    conn = get_db_connection(db_url)
    if not conn:
        return None, None, None, None

    try:
        # 1. Ставки
        bets_df = pd.read_sql_query(
            "SELECT * FROM paper_bets ORDER BY commence_time DESC LIMIT 100;", conn
        )
    except Exception:
        bets_df = pd.DataFrame()

    try:
        # 2. AI вердикти
        ai_df = pd.read_sql_query(
            """
            SELECT a.event_id, a.verdict_text, a.created_at, e.sport,
                   COALESCE(e.home_team || ' - ' || e.away_team, e.sport) AS match_name,
                   e.commence_time
            FROM ai_match_analysis a
            LEFT JOIN events e ON a.event_id = e.id
            ORDER BY a.created_at DESC LIMIT 30;
            """,
            conn,
        )
    except Exception:
        ai_df = pd.DataFrame()

    try:
        # 3. Розклад
        sched_df = pd.read_sql_query(
            "SELECT * FROM scheduler_plan ORDER BY target_time ASC LIMIT 25;", conn
        )
    except Exception:
        sched_df = pd.DataFrame()

    try:
        # 4. Пульс системи
        heartbeat_df = pd.read_sql_query(
            "SELECT * FROM system_heartbeat WHERE service_name='StatMonitor';", conn
        )
    except Exception:
        heartbeat_df = pd.DataFrame()

    conn.close()
    return bets_df, ai_df, sched_df, heartbeat_df

def run_streamlit_app():
    import streamlit as st
    import plotly.express as px

    st.set_page_config(
        page_title="StatMonitor Dashboard",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    # Бокова панель
    st.sidebar.title("⚽ StatMonitor")
    st.sidebar.caption("Платформа спортивного моніторингу та аналітики v2.0")

    env_db_url = os.environ.get("SUPABASE_DB_URL", "")
    db_url = st.sidebar.text_input(
        "Supabase DB URL",
        value=env_db_url,
        type="password",
        help="Рядок підключення до PostgreSQL бази даних Supabase",
    )

    if st.sidebar.button("🔄 Оновити дані"):
        st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.subheader("🚀 Керування тригером")
    trigger_url = "https://statmonitor.symchak.workers.dev"
    st.sidebar.caption(f"Шлюз виклику: `{trigger_url}`")
    if st.sidebar.button("⚡ Запустити моніторинг зараз"):
        try:
            from trigger_dispatch import trigger_workflow
            ok, code, msg = trigger_workflow()
            if ok:
                st.sidebar.success(f"Запущено! [{code}] {msg}")
            else:
                st.sidebar.error(f"Помилка [{code}]: {msg}")
        except Exception as e:
            st.sidebar.error(f"Помилка виклику: {e}")

    # Завантаження даних
    if not db_url:
        st.warning("⚠️ Будь ласка, вкажіть `SUPABASE_DB_URL` у боковій панелі або змінних оточення.")
        st.info("💡 Підказка: дашборд автоматично підтягує дані про ставки, AI-аналіз та розклад.")
        return

    bets_df, ai_df, sched_df, heartbeat_df = fetch_data(db_url)
    metrics = compute_metrics(bets_df)

    # 1. Верхній блок KPI карток
    st.title("📊 Моніторинг та аналітика системи")

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
        # Графік кумулятивного прибутку
        if bets_df is not None and not bets_df.empty:
            settled_df = bets_df[bets_df["status"].isin(["WON", "LOST", "VOID"])].copy()
            if not settled_df.empty and "settled_at" in settled_df.columns:
                settled_df = settled_df.sort_values(by="settled_at", ascending=True)
                settled_df["cum_profit"] = settled_df["profit_uah"].cumsum()
                settled_df["balance"] = INITIAL_BANKROLL + settled_df["cum_profit"]

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

        col_left, col_right = st.columns([1, 1])

        with col_left:
            st.subheader("⏳ Активні ставки в грі (Pending)")
            if bets_df is not None and not bets_df.empty:
                pending_df = bets_df[bets_df["status"] == "PENDING"]
                if not pending_df.empty:
                    st.dataframe(
                        pending_df[["sport", "match_name", "pick_label", "odds", "stake_uah", "commence_time"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("Наразі немає відкритих ставок у грі.")
            else:
                st.info("Дані відсутні.")

        with col_right:
            st.subheader("📋 Історія розрахованих ставок")
            if bets_df is not None and not bets_df.empty:
                settled_df = bets_df[bets_df["status"].isin(["WON", "LOST", "VOID"])]
                if not settled_df.empty:
                    st.dataframe(
                        settled_df[["match_name", "pick_label", "odds", "stake_uah", "match_score", "status", "profit_uah"]],
                        use_container_width=True,
                        hide_index=True,
                    )
                else:
                    st.info("Історія розрахунків порожня.")
            else:
                st.info("Дані відсутні.")

    # Вкладка 2: AI-аналітика Gemini
    with tab_ai:
        st.subheader("🤖 Останні AI-вердикти та рекомендації матчів")
        if ai_df is not None and not ai_df.empty:
            for _, row in ai_df.iterrows():
                with st.expander(f"⚽ {row.get('match_name', 'Матч')} ({row.get('sport', '')}) — {str(row.get('created_at', ''))[:16]}"):
                    st.markdown(row.get("verdict_text", "Текст аналізу відсутній"))
        else:
            st.info("AI-вердикти поки що не збережені в базі даних.")

    # Вкладка 3: Планувальник та здоров'я
    with tab_sched:
        col_s1, col_s2 = st.columns([1, 1])
        with col_s1:
            st.subheader("⏰ Контрольні точки розкладу (scheduler_plan)")
            if sched_df is not None and not sched_df.empty:
                st.dataframe(
                    sched_df[["target_time", "trigger_type", "description", "status"]],
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.info("Точки розкладу ще не сформовані.")

        with col_s2:
            st.subheader("💓 Монітор пульсу (system_heartbeat)")
            if heartbeat_df is not None and not heartbeat_df.empty:
                st.dataframe(heartbeat_df, use_container_width=True, hide_index=True)
            else:
                st.info("Записів пульсу не знайдено.")

if __name__ == "__main__":
    try:
        run_streamlit_app()
    except Exception as e:
        print(f"Помилка запуску Streamlit: {e}")
