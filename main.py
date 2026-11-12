import io
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg2
from psycopg2.extras import execute_values
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

DB_URL = os.environ.get("SUPABASE_DB_URL")
API_KEY = os.environ.get("ODDS_API_KEY")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

TARGET_SPORTS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_poland_ekstraklasa",
    "soccer_ukraine_premier_league",
    "soccer_uefa_champs_league",
    "soccer_uefa_nations_league",
    "basketball_nba"
]

KYIV_TZ = ZoneInfo("Europe/Kyiv")

def get_db_connection():
    return psycopg2.connect(DB_URL, connect_timeout=10, options="-c statement_timeout=20000")

def get_active_sports():
    active_set = set()
    try:
        resp = requests.get(f"https://api.the-odds-api.com/v4/sports/?apiKey={API_KEY}", timeout=10)
        if resp.status_code == 200:
            for item in resp.json():
                key = item.get("key", "")
                if item.get("active"):
                    if key in TARGET_SPORTS or key.startswith(("tennis_atp_", "tennis_wta_", "soccer_uefa_nations", "soccer_fifa_world_cup", "soccer_international")):
                        active_set.add(key)
        else:
            return list(TARGET_SPORTS)
    except Exception as e:
        print(f"Помилка перевірки списку турнірів: {e}")
        return list(TARGET_SPORTS)

    ordered = [s for s in TARGET_SPORTS if s in active_set]
    extra = sorted([s for s in active_set if s not in ordered])
    return ordered + extra

def format_kyiv_time(val):
    if hasattr(val, "astimezone"):
        if val.tzinfo is None:
            val = val.replace(tzinfo=timezone.utc)
        return val.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")
    return val.strftime("%H:%M")

def get_sport_icon(sport_key):
    if "basketball" in sport_key:
        return "\U0001f3c0"
    if "tennis" in sport_key:
        return "\U0001f3be"
    return "\u26bd"

def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Помилка Telegram API ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Мережева помилка Telegram: {e}")

def send_telegram_photo(photo_buf, caption):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", photo_buf, "image/png")}
    data = {"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, files=files, data=data, timeout=15)
        if resp.status_code != 200:
            print(f"Помилка відправки фото ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Помилка відправки фото: {e}")

def build_odds_chart(cur, event_id, match_name, outcome, target_bm):
    cur.execute("""
        SELECT odds_value, recorded_at
        FROM odds_history
        WHERE event_id = %s AND outcome = %s AND bookmaker = %s
        ORDER BY recorded_at ASC;
    """, (event_id, outcome, target_bm))
    rows = cur.fetchall()
    if len(rows) < 2:
        return None

    times = []
    vals = []
    for val, rec_at in rows:
        if rec_at.tzinfo is None:
            rec_at = rec_at.replace(tzinfo=timezone.utc)
        times.append(rec_at.astimezone(KYIV_TZ))
        vals.append(float(val))

    fig, ax = plt.subplots(figsize=(7.5, 3.8), dpi=130)
    color = "#d9534f" if vals[-1] < vals[0] else "#2ca02c"
    ax.plot(times, vals, marker="o", color=color, linewidth=2.5, markersize=6)

    for i, (t, v) in enumerate(zip(times, vals)):
        if i == 0 or i == len(vals) - 1 or v != vals[i - 1]:
            ax.annotate(
                f"{v:.2f}",
                (t, v),
                textcoords="offset points",
                xytext=(0, 8),
                ha="center",
                fontsize=9,
                fontweight="bold",
                color="#222222"
            )

    ax.set_title(f"{match_name}\nOutcome: {outcome} | БК: {target_bm}", fontsize=11, fontweight="bold", pad=10)
    ax.set_ylabel("Odds")
    ax.margins(x=0.08, y=0.22)
    ax.grid(True, linestyle="--", alpha=0.45)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=KYIV_TZ))
    fig.autofmt_xdate()
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf

def fetch_and_save_odds():
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    sports_to_scan = get_active_sports()
    print(f"1. Активні турніри ({len(sports_to_scan)}): {sports_to_scan}")

    events_batch = []
    odds_batch = []
    remaining_credits = "?"

    for sport in sports_to_scan:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "commenceTimeTo": commence_to_str
        }
        try:
            resp = requests.get(url, params=params, timeout=10)
            remaining_credits = resp.headers.get("x-requests-remaining", remaining_credits)
            if resp.status_code != 200:
                print(f"API {sport}: {resp.status_code}")
                continue
            for ev in resp.json():
                ev_id = ev["id"]
                commence_str = ev["commence_time"]
                ev_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
                if not (now_utc <= ev_dt <= max_date_utc):
                    continue
                events_batch.append((ev_id, sport, ev["home_team"], ev["away_team"], commence_str))
                for bm in ev.get("bookmakers", []):
                    for market in bm.get("markets", []):
                        if market["key"] == "h2h":
                            for outcome in market.get("outcomes", []):
                                odds_batch.append((ev_id, bm["key"], outcome["name"], outcome["price"]))
        except Exception as e:
            print(f"Помилка запиту {sport}: {e}")

    print(f"2. Залишок кредитів API: {remaining_credits}. Запис у БД...")

    conn = get_db_connection()
    cur = conn.cursor()
    try:
        if events_batch:
            execute_values(
                cur,
                "INSERT INTO events (id, sport, home_team, away_team, commence_time) VALUES %s ON CONFLICT (id) DO UPDATE SET commence_time = EXCLUDED.commence_time;",
                events_batch
            )
            execute_values(
                cur,
                "INSERT INTO odds_history (event_id, bookmaker, outcome, odds_value) VALUES %s;",
                odds_batch
            )

        cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '1 day' OR commence_time > NOW() + INTERVAL '5 days';")
        conn.commit()
        print(f"3. Успішно збережено подій: {len(events_batch)}, котирувань: {len(odds_batch)}")
        return True
    except Exception as e:
        print(f"Помилка БД: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def check_alerts_and_notify():
    print("4. Перевірка алертів та відправка в Telegram...")
    kyiv_now = datetime.now(KYIV_TZ)
    status_line = f"\u2705 \u043a\u043e\u0435\u0444. {kyiv_now.strftime('%d.%m.%Y')} \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e \u0432 {kyiv_now.strftime('%H:%M')}"
    send_telegram_alert(status_line)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT event_id, sport, match_name, commence_time, bookmaker, outcome, initial_odds, initial_time, current_odds, current_time, pct_change 
        FROM v_odds_alerts 
        LIMIT 8;
    """)
    odds_alerts = cur.fetchall()

    for a in odds_alerts:
        ev_id, sport, match, c_time, bm, outcome, init_k, init_t, curr_k, curr_t, pct = a
        s_icon = get_sport_icon(sport)
        t_icon = "\U0001f53b" if pct < 0 else "\U0001f53a"
        c_str = format_kyiv_time(c_time)
        t1_str = format_kyiv_time(init_t)
        t2_str = format_kyiv_time(curr_t)

        caption = (
            f"{s_icon} <b>{match}</b> ({sport})\n"
            f"\U0001f4c5 \u041f\u043e\u0447\u0430\u0442\u043e\u043a: {c_str}\n"
            f"\U0001f4ca \u0411\u041a: {bm} | \u0420\u0435\u0437\u0443\u043b\u044c\u0442\u0430\u0442: <b>{outcome}</b>\n"
            f"{t_icon} <code>{init_k}</code> ({t1_str}) \u2794 <code>{curr_k}</code> ({t2_str}) (<b>{pct}%</b>)"
        )

        chart = build_odds_chart(cur, ev_id, match, outcome, bm)
        if chart:
            send_telegram_photo(chart, caption)
        else:
            send_telegram_alert(caption)

    cur.execute("SELECT sport, match_name, commence_time, p1_side, draw_side, p2_side, profit_percent, stake_p1_pct, stake_draw_pct, stake_p2_pct FROM v_arbitrage_3way LIMIT 5;")
    arb_3way = cur.fetchall()
    if arb_3way:
        msg = "\u26a1 <b>\u0424\u0443\u0442\u0431\u043e\u043b\u044c\u043d\u0438\u0439 \u0430\u0440\u0431\u0456\u0442\u0440\u0430\u0436 (&gt;5%)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            c_str = format_kyiv_time(c_time)
            msg += f"\u26bd <b>{match}</b> ({c_str}) | +<b>{profit}%</b>\n\u2022 1: {p1} ({s1}%)\n\u2022 X: {draw} ({s_x}%)\n\u2022 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    cur.execute("SELECT sport, match_name, commence_time, p1_side, p2_side, profit_percent, stake_p1_pct, stake_p2_pct FROM v_arbitrage_2way LIMIT 5;")
    arb_2way = cur.fetchall()
    if arb_2way:
        msg = "\u26a1 <b>2-way \u0412\u0438\u043b\u043a\u0430 (&gt;5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            s_icon = get_sport_icon(sport)
            c_str = format_kyiv_time(c_time)
            msg += f"{s_icon} <b>{match}</b> ({c_str}) | +<b>{profit}%</b>\n\u2022 1: {p1} ({s1}%)\n\u2022 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    cur.close()
    conn.close()
    print("5. Готово!")

if __name__ == "__main__":
    if fetch_and_save_odds():
        check_alerts_and_notify()
