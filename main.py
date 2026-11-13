import io
import os
import re
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
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

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

SPORT_TITLES_UA = {
    "soccer_epl": "Англія. Прем'єр-ліга (EPL)",
    "soccer_spain_la_liga": "Іспанія. Ла Ліга",
    "soccer_italy_serie_a": "Італія. Серія А",
    "soccer_germany_bundesliga": "Німеччина. Бундесліга",
    "soccer_france_ligue_one": "Франція. Ліга 1",
    "soccer_poland_ekstraklasa": "Польща. Екстракляса",
    "soccer_ukraine_premier_league": "Україна. УПЛ",
    "soccer_uefa_champs_league": "Ліга чемпіонів УЄФА",
    "soccer_uefa_nations_league": "Ліга націй УЄФА",
    "basketball_nba": "Баскетбол. NBA",
    "tennis_wta_finals": "Теніс. Підсумковий турнір WTA"
}

KYIV_TZ = ZoneInfo("Europe/Kyiv")

def get_db_connection():
    return psycopg2.connect(DB_URL, connect_timeout=10, options="-c statement_timeout=20000")

def get_active_sports():
    active_map = {}
    try:
        resp = requests.get(f"https://api.the-odds-api.com/v4/sports/?apiKey={API_KEY}", timeout=10)
        if resp.status_code == 200:
            for item in resp.json():
                key = item.get("key", "")
                if item.get("active"):
                    if key in TARGET_SPORTS or key.startswith(("tennis_atp_", "tennis_wta_", "soccer_uefa_nations", "soccer_fifa_world_cup", "soccer_international")):
                        title = SPORT_TITLES_UA.get(key) or item.get("title", key)
                        active_map[key] = title
        else:
            return {k: SPORT_TITLES_UA.get(k, k) for k in TARGET_SPORTS}
    except Exception as e:
        print(f"Помилка перевірки списку турнірів: {e}")
        return {k: SPORT_TITLES_UA.get(k, k) for k in TARGET_SPORTS}

    ordered = {k: active_map[k] for k in TARGET_SPORTS if k in active_map}
    for k in sorted(active_map.keys()):
        if k not in ordered:
            ordered[k] = active_map[k]
    return ordered

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

def format_point(pt):
    if pt is None:
        return ""
    val = float(pt)
    return f"{val:g}"

def format_signed_point(pt):
    if pt is None:
        return ""
    val = float(pt)
    if val > 0:
        return f"+{val:g}"
    return f"{val:g}"

def is_standard_handicap(point):
    if point is None:
        return True
    return round(abs(float(point)) * 100) % 50 == 0

def encode_outcome_key(market_key, outcome):
    name = outcome.get("name", "")
    point = outcome.get("point")
    if market_key == "totals" and point is not None:
        return f"Total {name} {format_point(point)}"
    if market_key == "spreads" and point is not None:
        return f"Spread {name} ({format_signed_point(point)})"
    return name

def format_outcome_label(match_name, outcome, sport_key=""):
    parts = match_name.split(" - ", 1)

    if outcome.startswith("Total Over "):
        line = outcome.replace("Total Over ", "", 1)
        return "Тотал (ТБ/ТМ)", f"ТБ {line}"
    if outcome.startswith("Total Under "):
        line = outcome.replace("Total Under ", "", 1)
        return "Тотал (ТБ/ТМ)", f"ТМ {line}"

    if outcome.startswith("Spread "):
        raw = outcome.replace("Spread ", "", 1)
        if len(parts) == 2:
            if raw.startswith(parts[0].strip() + " "):
                hcap = raw[len(parts[0].strip()):].strip()
                return "Фора (гандикап)", f"Ф1 {hcap} ({parts[0].strip()})"
            if raw.startswith(parts[1].strip() + " "):
                hcap = raw[len(parts[1].strip()):].strip()
                return "Фора (гандикап)", f"Ф2 {hcap} ({parts[1].strip()})"
        return "Фора (гандикап)", raw

    market_name = "Переможець (1-2)" if ("basketball" in sport_key or "tennis" in sport_key) else "Основний час (1X2)"
    if outcome.lower() == "draw":
        pick = "Х (Нічия)"
    elif len(parts) == 2 and outcome.strip() == parts[0].strip():
        pick = f"П1 ({outcome})"
    elif len(parts) == 2 and outcome.strip() == parts[1].strip():
        pick = f"П2 ({outcome})"
    else:
        pick = outcome
    return market_name, pick

def sanitize_html_for_tg(raw_text):
    text = raw_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return text.strip()

def analyze_match_with_gemini(match_name, sport_title, commence_str, drops_summary):
    if not GEMINI_API_KEY:
        return None

    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash"
    ]
    prompt = (
        f"Ти професійний спортивний аналітик. Оціни матч перед ставкою:\n"
        f"Матч: {match_name}\n"
        f"Турнір: {sport_title}\n"
        f"Дата та час початку (Київ): {commence_str}\n"
        f"Виявлені різкі просідання коефіцієнтів:\n{drops_summary}\n\n"
        f"Дай стислу структуровану відповідь українською мовою (до 600 символів) у форматі:\n"
        f"1. Контекст матчу: (рівень суперників, фактор поля, турнірна значущість)\n"
        f"2. Оцінка прогрузу: (чи виглядає падіння коефіцієнтів як впевнений рух грошей, чи ринок ще нестабільний)\n"
        f"3. Вердикт: (конкретна рекомендована ставка або порада пропустити матч)"
    )

    for model_name in models_to_try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 550
            }
        }

        try:
            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    answer = "".join(p.get("text", "") for p in parts)
                    if answer.strip():
                        print(f"OK Gemini ({model_name}) для {match_name}")
                        time.sleep(6)
                        return sanitize_html_for_tg(answer)
            else:
                err_msg = resp.json().get("error", {}).get("message", resp.text)
                print(f"Gemini {model_name} ({resp.status_code}): {err_msg}")
                time.sleep(2)
        except Exception as e:
            print(f"Помилка запиту до Gemini ({model_name}): {e}")
    return None

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

def build_odds_chart(cur, event_id, match_name, outcome, target_bm, pick_label, sport_title):
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

    ax.set_title(f"{match_name} ({sport_title})\nСтавка: {pick_label} | БК: {target_bm}", fontsize=10.5, fontweight="bold", pad=10)
    ax.set_ylabel("Коефіцієнт")
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

def fetch_and_save_odds(sports_titles_map):
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    sports_to_scan = list(sports_titles_map.keys())
    print(f"1. Активні турніри ({len(sports_to_scan)}): {sports_to_scan}")

    events_batch = []
    odds_batch = []
    remaining_credits = "?"

    for sport in sports_to_scan:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": API_KEY,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "commenceTimeTo": commence_to_str
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
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
                        m_key = market["key"]
                        if m_key in ("h2h", "totals", "spreads"):
                            for outcome in market.get("outcomes", []):
                                if m_key == "spreads" and not is_standard_handicap(outcome.get("point")):
                                    continue
                                encoded_name = encode_outcome_key(m_key, outcome)
                                odds_batch.append((ev_id, bm["key"], encoded_name, outcome["price"]))
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

def check_alerts_and_notify(sports_titles_map):
    print("4. Перевірка алертів, AI-аналіз та відправка в Telegram...")
    kyiv_now = datetime.now(KYIV_TZ)
    status_line = f"\u2705 \u043a\u043e\u0435\u0444. {kyiv_now.strftime('%d.%m.%Y')} \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e \u0432 {kyiv_now.strftime('%H:%M')}"
    send_telegram_alert(status_line)

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("""
        SELECT event_id, sport, match_name, commence_time, bookmaker, outcome, initial_odds, initial_time, current_odds, current_time, pct_change 
        FROM v_odds_alerts 
        WHERE pct_change < 0
          AND initial_odds <= 4.00
          AND current_odds <= 4.00
        ORDER BY pct_change ASC
        LIMIT 50;
    """)
    odds_alerts = cur.fetchall()

    grouped_alerts = {}
    for a in odds_alerts:
        ev_id = a[0]
        if ev_id not in grouped_alerts:
            if len(grouped_alerts) >= 15:
                continue
            grouped_alerts[ev_id] = []
        grouped_alerts[ev_id].append(a)

    for ev_id, alerts_list in grouped_alerts.items():
        first = alerts_list[0]
        _, sport, match, c_time, top_bm, top_outcome, _, _, _, _, _ = first
        s_icon = get_sport_icon(sport)
        sport_title = sports_titles_map.get(sport) or SPORT_TITLES_UA.get(sport, sport)
        c_str = format_kyiv_time(c_time)
        _, top_pick_label = format_outcome_label(match, top_outcome, sport)

        header = (
            f"{s_icon} <b>{match}</b>\n"
            f"\U0001f3c6 <b>{sport_title}</b>\n"
            f"\U0001f4c5 Початок: {c_str}\n"
        )

        lines = []
        plain_drops = []
        for item in alerts_list:
            _, _, _, _, bm, outcome, init_k, init_t, curr_k, curr_t, pct = item
            market_name, pick_label = format_outcome_label(match, outcome, sport)
            t1_str = format_kyiv_time(init_t)
            t2_str = format_kyiv_time(curr_t)
            plain_drops.append(f"- {pick_label} ({market_name}) у БК {bm}: {init_k} -> {curr_k} ({pct}%)")

            if len(alerts_list) == 1:
                lines.append(
                    f"\U0001f3af Ринок: {market_name} | <b>{pick_label}</b>\n"
                    f"\U0001f4ca БК: <b>{bm}</b>\n"
                    f"\U0001f53b <b>Просідання:</b> <code>{init_k}</code> ({t1_str}) \u2794 <code>{curr_k}</code> ({t2_str}) (<b>{pct}%</b>)"
                )
            else:
                lines.append(
                    f"\u2022 <b>{pick_label}</b> [{market_name}] | БК: <b>{bm}</b>\n"
                    f"  \U0001f53b <code>{init_k}</code> ({t1_str}) \u2794 <code>{curr_k}</code> ({t2_str}) (<b>{pct}%</b>)"
                )

        if len(alerts_list) > 1:
            header += f"\n\U0001f4c9 <b>Виявлено просідань по матчу: {len(alerts_list)}</b>\n"

        caption = header + "\n".join(lines)
        chart = build_odds_chart(cur, ev_id, match, top_outcome, top_bm, top_pick_label, sport_title)

        if chart and len(caption) <= 1024:
            send_telegram_photo(chart, caption)
        else:
            send_telegram_alert(caption)

        ai_verdict = analyze_match_with_gemini(match, sport_title, c_str, "\n".join(plain_drops))
        if ai_verdict:
            ai_msg = f"\U0001f9e0 <b>AI-аналіз: {match}</b>\n\n{ai_verdict}"
            send_telegram_alert(ai_msg)

    cur.execute("SELECT sport, match_name, commence_time, p1_side, draw_side, p2_side, profit_percent, stake_p1_pct, stake_draw_pct, stake_p2_pct FROM v_arbitrage_3way LIMIT 5;")
    arb_3way = cur.fetchall()
    if arb_3way:
        msg = "\u26a1 <b>Футбольний арбітраж (&gt;5%) | Ринок: Основний час (1X2)</b>\n\n"
        for arb in arb_3way:
            sport, match, c_time, p1, draw, p2, profit, s1, s_x, s2 = arb
            sport_title = sports_titles_map.get(sport) or SPORT_TITLES_UA.get(sport, sport)
            c_str = format_kyiv_time(c_time)
            msg += f"\u26bd <b>{match}</b> [{sport_title}] ({c_str}) | +<b>{profit}%</b>\n\u2022 П1: {p1} ({s1}%)\n\u2022 Х: {draw} ({s_x}%)\n\u2022 П2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    cur.execute("SELECT sport, match_name, commence_time, p1_side, p2_side, profit_percent, stake_p1_pct, stake_p2_pct FROM v_arbitrage_2way LIMIT 5;")
    arb_2way = cur.fetchall()
    if arb_2way:
        msg = "\u26a1 <b>2-way Вилка (&gt;5%)</b>\n\n"
        for arb in arb_2way:
            sport, match, c_time, p1, p2, profit, s1, s2 = arb
            s_icon = get_sport_icon(sport)
            sport_title = sports_titles_map.get(sport) or SPORT_TITLES_UA.get(sport, sport)
            c_str = format_kyiv_time(c_time)
            msg += f"{s_icon} <b>{match}</b> [{sport_title}] ({c_str}) | +<b>{profit}%</b>\n\u2022 Плече 1: {p1} ({s1}%)\n\u2022 Плече 2: {p2} ({s2}%)\n\n"
        send_telegram_alert(msg)

    cur.close()
    conn.close()
    print("5. Готово!")

if __name__ == "__main__":
    active_sports_map = get_active_sports()
    if fetch_and_save_odds(active_sports_map):
        check_alerts_and_notify(active_sports_map)
