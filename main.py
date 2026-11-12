import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests
import psycopg2
from psycopg2.extras import execute_values

DB_URL = os.environ.get("SUPABASE_DB_URL")
API_KEY = os.environ.get("ODDS_API_KEY")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")

SPORTS = [
    "soccer_epl",
    "soccer_uefa_champs_league",
    "basketball_nba"
]

def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("TG_BOT_TOKEN або TG_CHAT_ID порожні!")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Помилка Telegram API ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Мережева помилка відправки Telegram: {e}")

def fetch_and_save_odds():
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    events_batch = []
    odds_batch = []

    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "h2h",
            "commenceTimeTo": commence_to_str
        }
        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
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
            print(f"Помилка запиту для {sport}: {e}")

    if not events_batch:
        return False

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
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
        cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '1 day';")
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def check_alerts_and_notify():
    kyiv_now = datetime.now(ZoneInfo("Europe/Kyiv"))
    status_line = f"\u2705 \u043a\u043e\u0435\u0444. {kyiv_now.strftime('%d.%m.%Y')} \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e \u0432 {kyiv_now.strftime('%H:%M')}"
    send_telegram_alert(status_line)

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    cur.execute("SELECT sport, match_name, commence_time, bookmaker, outcome, initial_odds, current_odds, pct_change FROM v_odds_alerts LIMIT 10;")
    odds_alerts = cur.fetchall()
    cur.execute("SELECT sport, match_name, commence_time, p1_side, draw_side, p2_side, profit_percent, stake_p1_pct, stake_draw_pct, stake_p2_pct FROM v_arbitrage_3way LIMIT 5;")
    arb_3way = cur.fetchall()
    cur.execute("SELECT sport, match_name, commence_time, p1_side, p2_side, profit_percent, stake_p1_pct, stake_p2_pct FROM v_arbitrage_2way LIMIT 5;")
    arb_2way = cur.fetchall()
    cur.close()
    conn.close()

    if odds_alerts:
        msg = "\U0001f4c9 <b>\u041f\u0440\u043e\u0441\u0456\u0434\u0430\u043d\u043d\u044f/\u0440\u0443\u0445 \u043a\u043e\u0435\u0444\u0456\u0446\u0456\u0454\u043d\u0442\u0456\u0432 (&gt;8%)</b>\n\n"
        for a in odds_alerts:
            sport, match, c_time, bm, outcome, init_k, curr_k, pct = a
            icon = "\U0001f53b" if pct < 0 else "\U0001f53a"
            msg += f"\u26bd <b>{match}</b> ({sport})\n\U0001f4c5 {c_time.strftime('%d.%m %H:%M')} | \u0411\u041a: {bm} | <b>{outcome}</b>\n{icon} <code>{init_k}</code> \u2794 <code>{curr_k}</code> (<b>{pct}%</b>)\n\n"
        send_telegram_alert(msg)

    if arb_3way:
        msg = "\u26a1 <b>\u0424\u0443\u0442\u0431\u043e\u043b\u044c\u043d\u0438\u0439 \u0430\u0440\u0431\u0456\u0442\u0440\u0430\u0436 (&gt;5%)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            msg += f"\U0001f3c6 <b>{match}</b> (+<b>{profit}%</b>)\n\u2022 1: {p1} ({s1}%)\n\u2022 X: {draw} ({s_x}%)\n\u2022 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    if arb_2way:
        msg = "\u26a1 <b>2-way \u0412\u0438\u043b\u043a\u0430 (&gt;5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            msg += f"\U0001f3c0 <b>{match}</b> (+<b>{profit}%</b>)\n\u2022 1: {p1} ({s1}%)\n\u2022 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

if __name__ == "__main__":
    if fetch_and_save_odds():
        check_alerts_and_notify()
