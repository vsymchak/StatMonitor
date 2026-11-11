import os
import requests
import psycopg2

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
    print("1. Збір та збереження свіжих котирувань...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    total_events = 0
    total_odds = 0

    for sport in SPORTS:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {"apiKey": API_KEY, "regions": "eu", "markets": "h2h"}

        try:
            resp = requests.get(url, params=params, timeout=15)
            if resp.status_code != 200:
                print(f"Помилка {sport}: {resp.status_code}")
                continue

            events_data = resp.json()
            for ev in events_data:
                ev_id = ev["id"]
                home_team = ev["home_team"]
                away_team = ev["away_team"]
                commence_time = ev["commence_time"]

                cur.execute("""
                    INSERT INTO events (id, sport, home_team, away_team, commence_time)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET commence_time = EXCLUDED.commence_time;
                """, (ev_id, sport, home_team, away_team, commence_time))
                total_events += 1

                for bm in ev.get("bookmakers", []):
                    bm_name = bm["key"]
                    for market in bm.get("markets", []):
                        if market["key"] == "h2h":
                            for outcome in market.get("outcomes", []):
                                out_name = outcome["name"]
                                price = outcome["price"]

                                cur.execute("""
                                    INSERT INTO odds_history (event_id, bookmaker, outcome, odds_value)
                                    VALUES (%s, %s, %s, %s);
                                """, (ev_id, bm_name, out_name, price))
                                total_odds += 1

            conn.commit()
        except Exception as e:
            print(f"Помилка при зборі {sport}: {e}")
            conn.rollback()

    cur.close()
    conn.close()
    print(f"Оновлено подій: {total_events}, додано котирувань: {total_odds}")

def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("Telegram не налаштовано, вивід у лог:")
        print(text)
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TG_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"Помилка відправки Telegram: {e}")

def check_alerts_and_notify():
    print("2. Перевірка динаміки (>8%) та вилок (>5%)...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()

    # 1. Рух коефіцієнтів (> 8%)
    cur.execute("""
        SELECT sport, match_name, commence_time, bookmaker, outcome, initial_odds, current_odds, pct_change 
        FROM v_odds_alerts 
        LIMIT 10;
    """)
    odds_alerts = cur.fetchall()

    if odds_alerts:
        msg = "📉 <b>StatMonitor: Просідання/рух коефіцієнтів (>8%)</b>\n\n"
        for a in odds_alerts:
            sport, match, c_time, bm, outcome, init_k, curr_k, pct = a
            icon = "🔻" if pct < 0 else "🔺"
            msg += f"⚽ <b>{match}</b> ({sport})\n"
            msg += f"📅 Початок: {c_time.strftime('%d.%m %H:%M')}\n"
            msg += f"📊 БК: {bm} | Результат: <b>{outcome}</b>\n"
            msg += f"{icon} Рух: <code>{init_k}</code> ➔ <code>{curr_k}</code> (<b>{pct}%</b>)\n\n"
        send_telegram_alert(msg)

    # 2. Футбольні вилки (3-way > 5%)
    cur.execute("""
        SELECT sport, match_name, commence_time, p1_side, draw_side, p2_side, profit_percent, stake_p1_pct, stake_draw_pct, stake_p2_pct 
        FROM v_arbitrage_3way 
        LIMIT 5;
    """)
    arb_3way = cur.fetchall()

    if arb_3way:
        msg = "⚡ <b>StatMonitor: Футбольний арбітраж / Вилка (>5%)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            msg += f"🏆 <b>{match}</b>\n"
            msg += f"📅 {c_time.strftime('%d.%m %H:%M')} | Профіт: <b>+{profit}%</b>\n"
            msg += f"• 1: {p1} — ставка {s1}%\n"
            msg += f"• X: {draw} — ставка {s_x}%\n"
            msg += f"• 2: {p2} — ставка {s2}%\n\n"
        send_telegram_alert(msg)

    # 3. Баскетбол / Теніс (2-way > 5%)
    cur.execute("""
        SELECT sport, match_name, commence_time, p1_side, p2_side, profit_percent, stake_p1_pct, stake_p2_pct 
        FROM v_arbitrage_2way 
        LIMIT 5;
    """)
    arb_2way = cur.fetchall()

    if arb_2way:
        msg = "⚡ <b>StatMonitor: 2-way Вилка (>5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            msg += f"🏀 <b>{match}</b>\n"
            msg += f"📅 {c_time.strftime('%d.%m %H:%M')} | Профіт: <b>+{profit}%</b>\n"
            msg += f"• 1: {p1} — ставка {s1}%\n"
            msg += f"• 2: {p2} — ставка {s2}%\n\n"
        send_telegram_alert(msg)

    cur.close()
    conn.close()

if __name__ == "__main__":
    fetch_and_save_odds()
    check_alerts_and_notify()
