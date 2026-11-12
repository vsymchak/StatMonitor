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
        print("ПОМИЛКА: TG_BOT_TOKEN або TG_CHAT_ID порожн? у Secrets!")
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code != 200:
            print(f"Помилка Telegram API ({resp.status_code}): {resp.text}")
        else:
            print("Пов?домлення усп?шно доставлено в Telegram!")
    except Exception as e:
        print(f"Мережева помилка в?дправки Telegram: {e}")

def fetch_and_save_odds():
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"1. Зб?р котирувань до {commence_to_str}...")

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
                print(f"Помилка API ({sport}): {resp.status_code}")
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
        print("Под?й у в?кн? 5 дн?в не знайдено.")
        return False

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    try:
        execute_values(
            cur,
            """
            INSERT INTO events (id, sport, home_team, away_team, commence_time)
            VALUES %s
            ON CONFLICT (id) DO UPDATE SET commence_time = EXCLUDED.commence_time;
            """,
            events_batch
        )
        execute_values(
            cur,
            "INSERT INTO odds_history (event_id, bookmaker, outcome, odds_value) VALUES %s;",
            odds_batch
        )
        cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '1 day';")
        conn.commit()
        print(f"Збережено под?й: {len(events_batch)}, котирувань: {len(odds_batch)}")
        return True
    except Exception as e:
        print(f"Помилка запису в БД: {e}")
        conn.rollback()
        return False
    finally:
        cur.close()
        conn.close()

def check_alerts_and_notify():
    print("2. Формування зв?ту та перев?рка алерт?в...")
    
    # Формуємо рядок з? статусом оновлення за київським часом
    kyiv_now = datetime.now(ZoneInfo("Europe/Kyiv"))
    status_line = f" коеф. {kyiv_now.strftime('%d.%m.%Y')} оновлено в {kyiv_now.strftime('%H:%M')}"
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
        msg = " <b>Прос?дання/рух коеф?ц?єнт?в (>8%)</b>\n\n"
        for a in odds_alerts:
            sport, match, c_time, bm, outcome, init_k, curr_k, pct = a
            icon = "" if pct < 0 else ""
            msg += f" <b>{match}</b> ({sport})\n {c_time.strftime('%d.%m %H:%M')} | БК: {bm} | <b>{outcome}</b>\n{icon} <code>{init_k}</code>  <code>{curr_k}</code> (<b>{pct}%</b>)\n\n"
        send_telegram_alert(msg)

    if arb_3way:
        msg = " <b>Футбольний арб?траж (>5%)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            msg += f" <b>{match}</b> (+<b>{profit}%</b>)\n 1: {p1} ({s1}%)\n X: {draw} ({s_x}%)\n 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    if arb_2way:
        msg = " <b>2-way Вилка (>5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            msg += f" <b>{match}</b> (+<b>{profit}%</b>)\n 1: {p1} ({s1}%)\n 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

if __name__ == "__main__":
    if fetch_and_save_odds():
        check_alerts_and_notify()
