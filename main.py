import io
import json
import os
import re
import time
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
API_KEY_RESERVE = os.environ.get("ODDS_API_KEY_RESERVE")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
INITIAL_BANKROLL = 10000.00
INITIAL_BANKROLL = 10000.00

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

EXHAUSTED_MODELS = set()

def analyze_match_with_gemini(match_name, sport_title, commence_str, drops_summary):
    if not GEMINI_API_KEY:
        return None

    models_to_try = [
        "gemini-3.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-3.8-flash"
    ]
    prompt = (
        f"Ти професійний спортивний аналітик і гандикапер. Оціни матч на основі просідання коефіцієнтів:\n"
        f"Матч: {match_name}\n"
        f"Турнір: {sport_title}\n"
        f"Початок (Київ): {commence_str}\n"
        f"Просідання лінії:\n{drops_summary}\n\n"
        f"Напиши завершений аналіз українською мовою (400-700 символів) СТРОГО за такою структурою:\n"
        f"📌 **Коротка ставка:** (тільки лаконічний маркет без слів про коефіцієнт, наприклад: П1, Ф2 (+1.5), ТМ 2.5, або Пропустити)\n"
        f"🎯 **Рекомендована ставка:** (чітко вкажи: яку саме ставку брати з коефіцієнтом або чому краще пропустити)\n"
        f"📉 **Суть прогрузу:** (що означає цей рух коефіцієнтів у вказаних БК, особливо якщо там є гострі БК типу Pinnacle)\n"
        f"⚽ **Ігровий контекст:** (співвідношення сил, мотивація команд у турнірі, логіка вибраної фори/тоталу/результату)"
    )

    for model_name in models_to_try:
        if model_name in EXHAUSTED_MODELS:
            continue

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        gen_config = {
            "temperature": 0.3,
            "maxOutputTokens": 1500
        }
        if "2.5" in model_name:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config
        }

        for attempt in range(2):
            try:
                resp = requests.post(url, json=payload, timeout=35)
                if resp.status_code == 200:
                    data = resp.json()
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        answer = "".join(p.get("text", "") for p in parts if not p.get("thought"))
                        if len(answer.strip()) > 80:
                            print(f"OK Gemini ({model_name}) для {match_name} ({len(answer)} симв.)")
                            time.sleep(4)
                            return sanitize_html_for_tg(answer)
                    break
                elif resp.status_code == 404:
                    print(f"Gemini {model_name} (404): модель недоступна, пропускаю надалі")
                    EXHAUSTED_MODELS.add(model_name)
                    break
                elif resp.status_code == 429:
                    err_msg = resp.json().get("error", {}).get("message", "")
                    print(f"Gemini {model_name} (429): ліміт вичерпано, переключаюсь на резервну модель")
                    if "per day" in err_msg.lower() or "limit: 20" in err_msg.lower():
                        EXHAUSTED_MODELS.add(model_name)
                    break
                elif resp.status_code == 503 and attempt == 0:
                    print(f"Gemini {model_name} (503): високе навантаження, повтор через 4с...")
                    time.sleep(4)
                    continue
                else:
                    err_msg = resp.json().get("error", {}).get("message", resp.text[:160])
                    print(f"Gemini {model_name} ({resp.status_code}): {err_msg}")
                    break
            except Exception as e:
                print(f"Помилка запиту до Gemini ({model_name}): {e}")
                break
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
    current_api_key = API_KEY
    using_reserve = False

    for sport in sports_to_scan:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": current_api_key,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "commenceTimeTo": commence_to_str
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            remaining_credits = resp.headers.get("x-requests-remaining", remaining_credits)
            
            # Перевіряємо, чи не вичерпано ліміт на основному ключі
            if (resp.status_code == 401 or (remaining_credits != "?" and int(remaining_credits) <= 1)) and not using_reserve and API_KEY_RESERVE:
                print(f"⚠️ Основний ключ The Odds API вичерпано (лишилось кредитів: {remaining_credits}). Перемикаюся на RESERVE ключ!")
                current_api_key = API_KEY_RESERVE
                using_reserve = True
                params["apiKey"] = current_api_key
                resp = requests.get(url, params=params, timeout=12)
                remaining_credits = resp.headers.get("x-requests-remaining", remaining_credits)

            if resp.status_code != 200:
                print(f"API {sport} (ключ {reserve if using_reserve else main}): {resp.status_code} - {resp.text[:100]}")
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
    settle_finished_paper_bets(cur, conn)
    send_daily_bankroll_report(cur, conn)
    settle_finished_paper_bets(cur, conn)
    send_daily_bankroll_report(cur, conn)
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

def extract_short_pick(ai_verdict, fallback_pick):
    lines = ai_verdict.splitlines()
    for line in lines:
        if "Коротка ставка" in line:
            clean = re.sub(r"<[^>]+>", "", line)
            if ":" in clean:
                rec = clean.split(":", 1)[1].strip(" .,-;")
                if "пропустити" in rec.lower() or "утриматися" in rec.lower():
                    return "⏭ Пропустити матч"
                if rec:
                    return rec

    for line in lines:
        if "Рекомендована ставка" in line:
            clean = re.sub(r"<[^>]+>", "", line)
            if ":" in clean:
                rec = clean.split(":", 1)[1].strip()
                if "пропустити" in rec.lower() or "утриматися" in rec.lower():
                    return "⏭ Пропустити матч"
                rec = re.split(
                    r"\s*(?:,|\()?\s*(?:з|по|за|у|в)?\s*(?:поточн\w+|орієнтовн\w+|середн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|@)\s*(?:близько|біля|в районі|у діапазоні|від|до)?\s*[~0-9].*$",
                    rec,
                    maxsplit=1,
                    flags=re.IGNORECASE
                )[0]
                rec = re.split(r"\s+(?:за|@)\s+[~0-9].*$", rec, maxsplit=1, flags=re.IGNORECASE)[0]
                rec = re.split(r"\.(?:\s|$)", rec, maxsplit=1)[0].strip(" ,;-")
                if rec.count("(") > rec.count(")"):
                    rec += ")" * (rec.count("(") - rec.count(")"))
                if rec:
                    return rec
    return fallback_pick

def get_bankroll_state(cur):
    cur.execute("""
        SELECT
            COALESCE(SUM(profit_uah), 0) AS realized_profit,
            COALESCE(SUM(CASE WHEN status = 'PENDING' THEN stake_uah ELSE 0 END), 0) AS locked_stakes
        FROM paper_bets;
    """)
    realized_profit, locked_stakes = cur.fetchone()
    total_bank = round(INITIAL_BANKROLL + float(realized_profit), 2)
    available_bank = round(max(0.0, total_bank - float(locked_stakes)), 2)
    return total_bank, available_bank

def calculate_smart_stake(available_bank, odds):
    if available_bank < 50.0:
        return 0.0
    k = float(odds)
    if k <= 1.75:
        pct = 0.04   # Низький ризик: 4% від банку
    elif k <= 2.35:
        pct = 0.03   # Середній ризик: 3% від банку
    else:
        pct = 0.02   # Підвищений ризик: 2% від банку
    stake = round(available_bank * pct, 2)
    return min(stake, available_bank)

def place_paper_bet(cur, conn, event_id, sport, match_name, commence_time, pick_label, odds):
    if "пропустити" in pick_label.lower() or "утриматися" in pick_label.lower():
        return None
    cur.execute("SELECT id FROM paper_bets WHERE event_id = %s;", (event_id,))
    if cur.fetchone():
        return None

    _, available_bank = get_bankroll_state(cur)
    stake = calculate_smart_stake(available_bank, odds)
    if stake <= 0:
        return None

    cur.execute("""
        INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
        ON CONFLICT (event_id) DO NOTHING;
    """, (event_id, sport, match_name, commence_time, pick_label, float(odds), stake))
    conn.commit()
    print(f"💰 Paper Bet: {match_name} | {pick_label} @ {odds} | Ставка: {stake:.2f} грн")
    return stake

def settle_finished_paper_bets(cur, conn):
    if not GEMINI_API_KEY:
        return
    cur.execute("""
        SELECT id, sport, match_name, commence_time, pick_label, odds, stake_uah
        FROM paper_bets
        WHERE status = 'PENDING'
          AND commence_time < NOW() - INTERVAL '2 hours 45 minutes'
        ORDER BY commence_time ASC
        LIMIT 15;
    """)
    pending = cur.fetchall()
    if not pending:
        return

    items_desc = []
    for bet_id, sport, m_name, c_time, pick, odds, stake in pending:
        c_str = format_kyiv_time(c_time)
        items_desc.append(f"ID={bet_id} | Матч: {m_name} | Початок: {c_str} | Ставка: {pick} | Коеф: {odds}")

    prompt = (
        "Ти спортивний статистик. Перевір реальні фінальні рахунки завершених матчів і розрахуй результат кожної ставки.\n"
        "Список ставок для перевірки:\n" + "\n".join(items_desc) + "\n\n"
        "Поверни відповідь СТРОГО у форматі JSON-масиву об'єктів без markdown-обгорток (без ```json):\n"
        '[{"id": 1, "score": "2:1", "status": "WON"}]\n'
        "Правила для поля status:\n"
        "- WON: ставка виграла повністю\n"
        "- LOST: ставка програла\n"
        "- VOID: повернення ставки (наприклад, фора 0 при нічиїй, фора -1 при перемозі рівно в 1 м'яч, тотал більше 2 при рівно 2 голах)\n"
        "- UNKNOWN: якщо матч ще не завершився, перенесений або точний рахунок невідомий\n"
        "Враховуй азійські/європейські фори (Ф1/Ф2) та тотали (ТБ/ТМ) строго за фінальним рахунком основного часу (для баскетболу/тенісу — з урахуванням овертайму/сетів)."
    )

    models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    for model_name in models_to_try:
        if model_name in EXHAUSTED_MODELS:
            continue
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_name}:generateContent?key={GEMINI_API_KEY}"
        gen_config = {"temperature": 0.1, "maxOutputTokens": 1200}
        if "2.5" in model_name:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_config}

        try:
            resp = requests.post(url, json=payload, timeout=35)
            if resp.status_code == 200:
                parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                raw = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                results = json.loads(raw)
                bet_map = {b[0]: b for b in pending}
                settled_count = 0

                for res in results:
                    b_id = int(res.get("id", 0))
                    st = str(res.get("status", "")).upper()
                    score = str(res.get("score", ""))
                    if b_id not in bet_map or st not in ("WON", "LOST", "VOID"):
                        continue

                    _, _, m_name, _, pick, odds, stake = bet_map[b_id]
                    stake_f = float(stake)
                    odds_f = float(odds)
                    if st == "WON":
                        profit = round(stake_f * (odds_f - 1.0), 2)
                    elif st == "LOST":
                        profit = round(-stake_f, 2)
                    else:
                        profit = 0.0

                    cur.execute("""
                        UPDATE paper_bets
                        SET status = %s, match_score = %s, profit_uah = %s, settled_at = NOW()
                        WHERE id = %s AND status = 'PENDING';
                    """, (st, score, profit, b_id))
                    settled_count += 1
                    print(f"📊 Розраховано ставку #{b_id} ({m_name}): {score} -> {st} ({profit:+.2f} грн)")

                conn.commit()
                if settled_count > 0:
                    time.sleep(3)
                return
            elif resp.status_code == 429:
                EXHAUSTED_MODELS.add(model_name)
        except Exception as e:
            print(f"Помилка розрахунку paper_bets ({model_name}): {e}")

def send_daily_bankroll_report(cur, conn):
    kyiv_now = datetime.now(KYIV_TZ)
    if kyiv_now.hour < 8:
        return
    today_date = kyiv_now.date()
    cur.execute("SELECT 1 FROM paper_daily_reports WHERE report_date = %s;", (today_date,))
    if cur.fetchone():
        return

    cur.execute("""
        SELECT
            COUNT(*) AS total_bets,
            COUNT(*) FILTER (WHERE status = 'WON') AS won_bets,
            COUNT(*) FILTER (WHERE status = 'LOST') AS lost_bets,
            COUNT(*) FILTER (WHERE status = 'VOID') AS void_bets,
            COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_bets,
            COALESCE(SUM(stake_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS settled_turnover,
            COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS net_profit
        FROM paper_bets;
    """)
    total_b, won_b, lost_b, void_b, pend_b, turnover, net_profit = cur.fetchone()
    final_bank = round(INITIAL_BANKROLL + float(net_profit), 2)
    roi = round((float(net_profit) / float(turnover)) * 100, 2) if float(turnover) > 0 else 0.0
    bank_diff = round(final_bank - INITIAL_BANKROLL, 2)

    report_msg = (
        f"💼 <b>ЩОДЕННИЙ ЗВІТ PAPER BANK ({kyiv_now.strftime('%d.%m.%Y')})</b>\n\n"
        f"🏦 Початковий банк: <code>{INITIAL_BANKROLL:,.2f} грн</code>\n"
        f"💰 Кінцевий банк: <b><code>{final_bank:,.2f} грн</code></b> (<code>{bank_diff:+.2f} грн</code>)\n"
        f"📈 ROI (по розрахованих): <b><code>{roi:+.2f}%</code></b>\n\n"
        f"📊 Всього ставок: <b>{total_b}</b> (в грі: {pend_b})\n"
        f"✅ Виграшні: <b>{won_b}</b> | ❌ Програшні: <b>{lost_b}</b> | 🔄 Повернення: <b>{void_b}</b>"
    )
    send_telegram_alert(report_msg)
    cur.execute("INSERT INTO paper_daily_reports (report_date) VALUES (%s) ON CONFLICT DO NOTHING;", (today_date,))
    conn.commit()

def get_bankroll_state(cur):
    cur.execute("""
        SELECT
            COALESCE(SUM(profit_uah), 0) AS realized_profit,
            COALESCE(SUM(CASE WHEN status = 'PENDING' THEN stake_uah ELSE 0 END), 0) AS locked_stakes
        FROM paper_bets;
    """)
    realized_profit, locked_stakes = cur.fetchone()
    total_bank = round(INITIAL_BANKROLL + float(realized_profit), 2)
    available_bank = round(max(0.0, total_bank - float(locked_stakes)), 2)
    return total_bank, available_bank

def calculate_smart_stake(available_bank, odds):
    if available_bank < 50.0:
        return 0.0
    k = float(odds)
    if k <= 1.75:
        pct = 0.04   # Низький ризик: 4% від банку
    elif k <= 2.35:
        pct = 0.03   # Середній ризик: 3% від банку
    else:
        pct = 0.02   # Підвищений ризик: 2% від банку
    stake = round(available_bank * pct, 2)
    return min(stake, available_bank)

def place_paper_bet(cur, conn, event_id, sport, match_name, commence_time, pick_label, odds):
    if "пропустити" in pick_label.lower() or "утриматися" in pick_label.lower():
        return None
    cur.execute("SELECT id FROM paper_bets WHERE event_id = %s;", (event_id,))
    if cur.fetchone():
        return None

    _, available_bank = get_bankroll_state(cur)
    stake = calculate_smart_stake(available_bank, odds)
    if stake <= 0:
        return None

    cur.execute("""
        INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah, status)
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
        ON CONFLICT (event_id) DO NOTHING;
    """, (event_id, sport, match_name, commence_time, pick_label, float(odds), stake))
    conn.commit()
    print(f"💰 Paper Bet: {match_name} | {pick_label} @ {odds} | Ставка: {stake:.2f} грн")
    return stake

def settle_finished_paper_bets(cur, conn):
    if not GEMINI_API_KEY:
        return
    cur.execute("""
        SELECT id, sport, match_name, commence_time, pick_label, odds, stake_uah
        FROM paper_bets
        WHERE status = 'PENDING'
          AND commence_time < NOW() - INTERVAL '2 hours 45 minutes'
        ORDER BY commence_time ASC
        LIMIT 15;
    """)
    pending = cur.fetchall()
    if not pending:
        return

    items_desc = []
    for bet_id, sport, m_name, c_time, pick, odds, stake in pending:
        c_str = format_kyiv_time(c_time)
        items_desc.append(f"ID={bet_id} | Матч: {m_name} | Початок: {c_str} | Ставка: {pick} | Коеф: {odds}")

    prompt = (
        "Ти спортивний статистик. Перевір реальні фінальні рахунки завершених матчів і розрахуй результат кожної ставки.\n"
        "Список ставок для перевірки:\n" + "\n".join(items_desc) + "\n\n"
        "Поверни відповідь СТРОГО у форматі JSON-масиву об'єктів без markdown-обгорток (без ```json):\n"
        '[{"id": 1, "score": "2:1", "status": "WON"}]\n'
        "Правила для поля status:\n"
        "- WON: ставка виграла повністю\n"
        "- LOST: ставка програла\n"
        "- VOID: повернення ставки (наприклад, фора 0 при нічиїй, фора -1 при перемозі рівно в 1 м'яч, тотал більше 2 при рівно 2 голах)\n"
        "- UNKNOWN: якщо матч ще не завершився, перенесений або точний рахунок невідомий\n"
        "Враховуй азійські/європейські фори (Ф1/Ф2) та тотали (ТБ/ТМ) строго за фінальним рахунком основного часу (для баскетболу/тенісу — з урахуванням овертайму/сетів)."
    )

    models_to_try = ["gemini-2.5-flash", "gemini-3.5-flash-lite", "gemini-3.8-flash"]
    for model_name in models_to_try:
        if model_name in EXHAUSTED_MODELS:
            continue
        url = f"[https://generativelanguage.googleapis.com/v1beta/models/](https://generativelanguage.googleapis.com/v1beta/models/){model_name}:generateContent?key={GEMINI_API_KEY}"
        gen_config = {"temperature": 0.1, "maxOutputTokens": 1200}
        if "2.5" in model_name:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen_config}

        try:
            resp = requests.post(url, json=payload, timeout=35)
            if resp.status_code == 200:
                parts = resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                raw = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
                results = json.loads(raw)
                bet_map = {b[0]: b for b in pending}
                settled_count = 0

                for res in results:
                    b_id = int(res.get("id", 0))
                    st = str(res.get("status", "")).upper()
                    score = str(res.get("score", ""))
                    if b_id not in bet_map or st not in ("WON", "LOST", "VOID"):
                        continue

                    _, _, m_name, _, pick, odds, stake = bet_map[b_id]
                    stake_f = float(stake)
                    odds_f = float(odds)
                    if st == "WON":
                        profit = round(stake_f * (odds_f - 1.0), 2)
                    elif st == "LOST":
                        profit = round(-stake_f, 2)
                    else:
                        profit = 0.0

                    cur.execute("""
                        UPDATE paper_bets
                        SET status = %s, match_score = %s, profit_uah = %s, settled_at = NOW()
                        WHERE id = %s AND status = 'PENDING';
                    """, (st, score, profit, b_id))
                    settled_count += 1
                    print(f"📊 Розраховано ставку #{b_id} ({m_name}): {score} -> {st} ({profit:+.2f} грн)")

                conn.commit()
                if settled_count > 0:
                    time.sleep(3)
                return
            elif resp.status_code == 429:
                EXHAUSTED_MODELS.add(model_name)
        except Exception as e:
            print(f"Помилка розрахунку paper_bets ({model_name}): {e}")

def send_daily_bankroll_report(cur, conn):
    kyiv_now = datetime.now(KYIV_TZ)
    if kyiv_now.hour < 8:
        return
    today_date = kyiv_now.date()
    cur.execute("SELECT 1 FROM paper_daily_reports WHERE report_date = %s;", (today_date,))
    if cur.fetchone():
        return

    cur.execute("""
        SELECT
            COUNT(*) AS total_bets,
            COUNT(*) FILTER (WHERE status = 'WON') AS won_bets,
            COUNT(*) FILTER (WHERE status = 'LOST') AS lost_bets,
            COUNT(*) FILTER (WHERE status = 'VOID') AS void_bets,
            COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_bets,
            COALESCE(SUM(stake_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS settled_turnover,
            COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS net_profit
        FROM paper_bets;
    """)
    total_b, won_b, lost_b, void_b, pend_b, turnover, net_profit = cur.fetchone()
    final_bank = round(INITIAL_BANKROLL + float(net_profit), 2)
    roi = round((float(net_profit) / float(turnover)) * 100, 2) if float(turnover) > 0 else 0.0
    bank_diff = round(final_bank - INITIAL_BANKROLL, 2)

    report_msg = (
        f"💼 <b>ЩОДЕННИЙ ЗВІТ PAPER BANK ({kyiv_now.strftime('%d.%m.%Y')})</b>\n\n"
        f"🏦 Початковий банк: <code>{INITIAL_BANKROLL:,.2f} грн</code>\n"
        f"💰 Кінцевий банк: <b><code>{final_bank:,.2f} грн</code></b> (<code>{bank_diff:+.2f} грн</code>)\n"
        f"📈 ROI (по розрахованих): <b><code>{roi:+.2f}%</code></b>\n\n"
        f"📊 Всього ставок: <b>{total_b}</b> (в грі: {pend_b})\n"
        f"✅ Виграшні: <b>{won_b}</b> | ❌ Програшні: <b>{lost_b}</b> | 🔄 Повернення: <b>{void_b}</b>"
    )
    send_telegram_alert(report_msg)
    cur.execute("INSERT INTO paper_daily_reports (report_date) VALUES (%s) ON CONFLICT DO NOTHING;", (today_date,))
    conn.commit()

def check_alerts_and_notify(sports_titles_map):
    print("4. Перевірка алертів, AI-аналіз та відправка в Telegram...")
    kyiv_now = datetime.now(KYIV_TZ)
    status_line = f"\u2705 \u043a\u043e\u0435\u0444. {kyiv_now.strftime('%d.%m.%Y')} \u043e\u043d\u043e\u0432\u043b\u0435\u043d\u043e \u0432 {kyiv_now.strftime('%H:%M')}"
    send_telegram_alert(status_line)

    conn = get_db_connection()
    cur = conn.cursor()
    settle_finished_paper_bets(cur, conn)
    send_daily_bankroll_report(cur, conn)
    settle_finished_paper_bets(cur, conn)
    send_daily_bankroll_report(cur, conn)

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

    summary_table_rows = []
    for ev_id, alerts_list in grouped_alerts.items():
        first = alerts_list[0]
        _, sport, match, c_time, top_bm, top_outcome, _, _, top_curr_k, _, _ = first
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

            short_pick = extract_short_pick(ai_verdict, top_pick_label)
            place_paper_bet(cur, conn, ev_id, sport, match, c_time, short_pick, top_curr_k)
            sort_dt = c_time if getattr(c_time, "tzinfo", None) else c_time.replace(tzinfo=timezone.utc)
            summary_table_rows.append({
                "dt": sort_dt,
                "time": c_str,
                "match": match,
                "championship": sport_title,
                "pick": short_pick,
                "odds": f"{float(top_curr_k):.2f}"
            })

    if summary_table_rows:
        summary_table_rows.sort(key=lambda x: x["dt"])
        lines_out = ["📋 <b>ЗВЕДЕННЯ СТАВОК (AI-ВЕРДИКТ)</b>"]
        for idx, r in enumerate(summary_table_rows, 1):
            lines_out.append(
                f"<b>{idx}. {r['match']}</b>\n"
                f"   🕒 <code>{r['time']}</code> | <i>{r['championship']}</i>\n"
                f"   🎯 <b>{r['pick']}</b> — Коеф: <code>{r['odds']}</code>"
            )
        send_telegram_alert("\n\n".join(lines_out))

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
