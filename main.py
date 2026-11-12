import os
from datetime import datetime, timezone, timedelta
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

def fetch_and_save_odds():
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    
    # Формат ISO-8601 для параметра ф?льтрац?ї в API (наприклад: 2026-11-17T09:00:00Z)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"1. Зб?р котирувань для под?й до {commence_to_str} (в?кно 5 дн?в)...")

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
                print(f"Помилка API ({sport}): {resp.status_code} - {resp.text}")
                continue

            events_data = resp.json()
            for ev in events_data:
                ev_id = ev["id"]
                home_team = ev["home_team"]
                away_team = ev["away_team"]
                commence_str = ev["commence_time"]
                
                # Додаткова сувора перев?рка дати на сторон? Python
                ev_dt = datetime.fromisoformat(commence_str.replace("Z", "+00:00"))
                if not (now_utc <= ev_dt <= max_date_utc):
                    continue

                events_batch.append((ev_id, sport, home_team, away_team, commence_str))

                for bm in ev.get("bookmakers", []):
                    bm_name = bm["key"]
                    for market in bm.get("markets", []):
                        if market["key"] == "h2h":
                            for outcome in market.get("outcomes", []):
                                odds_batch.append((ev_id, bm_name, outcome["name"], outcome["price"]))

        except Exception as e:
            print(f"Помилка запиту для {sport}: {e}")

    if not events_batch:
        print("Не знайдено под?й у межах найближчих 5 дн?в.")
        return

    # Швидкий пакетний запис у Supabase (за 1-2 секунди)
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
            """
            INSERT INTO odds_history (event_id, bookmaker, outcome, odds_value)
            VALUES %s;
            """,
            odds_batch
        )

        # Автоматичне видалення вже завершених або старих под?й
        cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '1 day';")
        conn.commit()
        print(f"Усп?шно збережено! Под?й: {len(events_batch)}, котирувань: {len(odds_batch)}")
    except Exception as e:
        print(f"Помилка запису в БД: {e}")
        conn.rollback()
    finally:
        cur.close()
        conn.close()

def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("Telegram не налаштовано. Спов?щення:")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Помилка в?дправки Telegram: {e}")

def check_alerts_and_notify():
    print("2. Перев?рка динам?ки (>8%) та вилок (>5%)...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    cur.execute("""
        SELECT sport, match_name, commence_time, bookmaker, outcome, initial_odds, current_odds, pct_change 
        FROM v_odds_alerts 
        LIMIT 10;
    """)
    odds_alerts = cur.fetchall()

    if odds_alerts:
        msg = " <b>StatMonitor: Прос?дання/рух коеф?ц?єнт?в (>8%)</b>\n\n"
        for a in odds_alerts:
            sport, match, c_time, bm, outcome, init_k, curr_k, pct = a
            icon = "" if pct < 0 else ""
            msg += f" <b>{match}</b> ({sport})\n"
            msg += f" Початок: {c_time.strftime('%d.%m %H:%M')}\n"
            msg += f" БК: {bm} | Результат: <b>{outcome}</b>\n"
            msg += f"{icon} Рух: <code>{init_k}</code>  <code>{curr_k}</code> (<b>{pct}%</b>)\n\n"
        send_telegram_alert(msg)

    cur.execute("""
        SELECT sport, match_name, commence_time, p1_side, draw_side, p2_side, profit_percent, stake_p1_pct, stake_draw_pct, stake_p2_pct 
        FROM v_arbitrage_3way 
        LIMIT 5;
    """)
    arb_3way = cur.fetchall()

    if arb_3way:
        msg = " <b>StatMonitor: Футбольний арб?траж / Вилка (>5%)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            msg += f" <b>{match}</b>\n"
            msg += f" {c_time.strftime('%d.%m %H:%M')} | Проф?т: <b>+{profit}%</b>\n"
            msg += f" 1: {p1}  ставка {s1}%\n"
            msg += f" X: {draw}  ставка {s_x}%\n"
            msg += f" 2: {p2}  ставка {s2}%\n\n"
        send_telegram_alert(msg)

    cur.execute("""
        SELECT sport, match_name, commence_time, p1_side, p2_side, profit_percent, stake_p1_pct, stake_p2_pct 
        FROM v_arbitrage_2way 
        LIMIT 5;
    """)
    arb_2way = cur.fetchall()

    if arb_2way:
        msg = " <b>StatMonitor: 2-way Вилка (>5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            msg += f" <b>{match}</b>\n"
            msg += f" {c_time.strftime('%d.%m %H:%M')} | Проф?т: <b>+{profit}%</b>\n"
            msg += f" 1: {p1}  ставка {s1}%\n"
            msg += f" 2: {p2}  ставка {s2}%\n\n"
        send_telegram_alert(msg)

    cur.close()
    conn.close()

if __name__ == "__main__":
    fetch_and_save_odds()
    check_alerts_and_notify()
