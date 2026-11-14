import os
import re
import io
import json
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

# --- КОНФІГУРАЦІЯ ---
DB_URL = os.environ.get("SUPABASE_DB_URL")
API_KEY = os.environ.get("ODDS_API_KEY")
API_KEY_RESERVE = os.environ.get("ODDS_API_KEY_RESERVE")
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

INITIAL_BANKROLL = 10000.00
KYIV_TZ = ZoneInfo("Europe/Kyiv")
EXHAUSTED_MODELS = set()

TARGET_SPORTS = [
    "soccer_epl",
    "soccer_spain_la_liga",
    "soccer_italy_serie_a",
    "soccer_germany_bundesliga",
    "soccer_france_ligue_one",
    "soccer_ukraine_premier_league",
    "soccer_poland_ekstraklasa",
    "soccer_uefa_champs_league",
    "soccer_uefa_europa_league",
    "soccer_uefa_conference_league",
    "soccer_uefa_nations_league",
    "basketball_nba",
    "tennis_atp_tour_finals",
    "tennis_wta_finals",
]


def get_db_connection():
    return psycopg2.connect(DB_URL)


def ensure_tables_exist(cur, conn):
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS ai_match_analysis (
            event_id TEXT PRIMARY KEY,
            verdict_text TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW()
        );
        CREATE TABLE IF NOT EXISTS paper_bets (
            id SERIAL PRIMARY KEY,
            event_id TEXT UNIQUE NOT NULL,
            sport TEXT NOT NULL,
            match_name TEXT NOT NULL,
            commence_time TIMESTAMPTZ NOT NULL,
            pick_label TEXT NOT NULL,
            odds NUMERIC(6,3) NOT NULL,
            stake_uah NUMERIC(10,2) NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            match_score TEXT,
            profit_uah NUMERIC(10,2) NOT NULL DEFAULT 0.00,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            settled_at TIMESTAMPTZ
        );
        CREATE TABLE IF NOT EXISTS paper_daily_reports (
            report_date DATE PRIMARY KEY,
            sent_at TIMESTAMPTZ DEFAULT NOW()
        );
        """
    )
    conn.commit()


def get_table_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s;
        """,
        (table_name,),
    )
    return {row[0] for row in cur.fetchall()}


def pick_col(cols, candidates, default=None):
    for c in candidates:
        if c in cols:
            return c
    return default


def pick_val(row_dict, candidates, default=None):
    for c in candidates:
        if c in row_dict and row_dict[c] is not None:
            return row_dict[c]
    return default


def detect_odds_schema(cur):
    cols = get_table_columns(cur, "odds_history")
    print(f"Колонки odds_history у БД: {sorted(list(cols))}")

    schema = {
        "event_id": pick_col(cols, ("event_id", "match_id"), "event_id"),
        "bookmaker": pick_col(cols, ("bookmaker", "bm", "bookie"), "bookmaker"),
        "market": pick_col(cols, ("market_key", "market", "market_type", "mkt"), None),
        "outcome": pick_col(cols, ("outcome_name", "outcome", "selection", "team", "name"), None),
        "point": pick_col(cols, ("point", "handicap", "line", "points"), None),
        "price": pick_col(cols, ("price", "odds", "odd", "value", "coeff"), None),
        "time": pick_col(cols, ("recorded_at", "created_at", "timestamp", "updated_at"), None),
    }
    return schema


def format_kyiv_time(dt_obj):
    if dt_obj is None:
        return ""
    if isinstance(dt_obj, str):
        return dt_obj
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")


def send_telegram_alert(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TG_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=12)
        if resp.status_code != 200:
            print(f"Помилка Telegram API ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Помилка відправки повідомлення в Telegram: {e}")


def send_telegram_photo(photo_buf, caption):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    files = {"photo": ("chart.png", photo_buf, "image/png")}
    data = {
        "chat_id": TG_CHAT_ID,
        "caption": caption,
        "parse_mode": "HTML",
    }
    try:
        resp = requests.post(url, data=data, files=files, timeout=20)
        if resp.status_code != 200:
            print(f"Помилка відправки фото ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Помилка відправки фото в Telegram: {e}")


def get_active_sports_map():
    url = "https://api.the-odds-api.com/v4/sports/"
    keys_to_try = [k for k in (API_KEY, API_KEY_RESERVE) if k]
    for idx, key in enumerate(keys_to_try):
        try:
            resp = requests.get(url, params={"apiKey": key}, timeout=12)
            if resp.status_code == 200:
                active_map = {}
                for s in resp.json():
                    sp_key = s.get("key")
                    if sp_key in TARGET_SPORTS and s.get("active"):
                        active_map[sp_key] = s.get("title", sp_key)
                if active_map:
                    return active_map
            print(f"Sports list API ({'main' if idx == 0 else 'reserve'}): {resp.status_code}")
        except Exception as e:
            print(f"Помилка отримання списку турнірів: {e}")
    return {k: k for k in TARGET_SPORTS}


def fetch_and_save_odds(sports_titles_map):
    now_utc = datetime.now(timezone.utc)
    max_date_utc = now_utc + timedelta(days=5)
    commence_to_str = max_date_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    sports_to_scan = list(sports_titles_map.keys())
    print(f"1. Активні турніри ({len(sports_to_scan)}): {sports_to_scan}")

    events_batch = []
    odds_raw = []
    remaining_credits = "?"
    current_api_key = API_KEY or API_KEY_RESERVE
    using_reserve = (current_api_key == API_KEY_RESERVE and not API_KEY)

    for sport in sports_to_scan:
        url = f"https://api.the-odds-api.com/v4/sports/{sport}/odds/"
        params = {
            "apiKey": current_api_key,
            "regions": "eu",
            "markets": "h2h,totals,spreads",
            "commenceTimeTo": commence_to_str,
        }
        try:
            resp = requests.get(url, params=params, timeout=12)
            remaining_credits = resp.headers.get("x-requests-remaining", remaining_credits)

            try:
                rem_int = int(float(remaining_credits))
            except Exception:
                rem_int = 999

            if (resp.status_code in (401, 402, 429) or rem_int <= 1) and not using_reserve and API_KEY_RESERVE:
                print(
                    f"⚠️ Основний ключ The Odds API вичерпано (статус {resp.status_code}, залишок: {remaining_credits}). "
                    f"Перемикаюся на ODDS_API_KEY_RESERVE!"
                )
                current_api_key = API_KEY_RESERVE
                using_reserve = True
                params["apiKey"] = current_api_key
                resp = requests.get(url, params=params, timeout=12)
                remaining_credits = resp.headers.get("x-requests-remaining", remaining_credits)

            if resp.status_code != 200:
                print(
                    f"API {sport} (ключ {'reserve' if using_reserve else 'main'}): "
                    f"{resp.status_code} - {resp.text[:100]}"
                )
                continue

            for ev in resp.json():
                ev_id = ev["id"]
                home_team = ev.get("home_team", "")
                away_team = ev.get("away_team", "")
                commence_time = ev["commence_time"]
                events_batch.append((ev_id, sport, home_team, away_team, commence_time))

                for bm in ev.get("bookmakers", []):
                    bm_key = bm["key"]
                    for mkt in bm.get("markets", []):
                        mkt_key = mkt["key"]
                        for out in mkt.get("outcomes", []):
                            out_name = out.get("name", "")
                            point = out.get("point")
                            price = out.get("price")
                            if price is not None:
                                odds_raw.append(
                                    {
                                        "event_id": ev_id,
                                        "bookmaker": bm_key,
                                        "market": mkt_key,
                                        "outcome": out_name,
                                        "point": point,
                                        "price": price,
                                        "time": now_utc,
                                    }
                                )
        except Exception as e:
            print(f"Помилка при запиті {sport}: {e}")

    print(f"2. Залишок кредитів API: {remaining_credits}. Запис у БД...")
    conn = get_db_connection()
    cur = conn.cursor()
    ensure_tables_exist(cur, conn)

    ev_cols = get_table_columns(cur, "events")
    if events_batch:
        id_col = pick_col(ev_cols, ("id", "event_id"), "id")
        if "home_team" in ev_cols and "away_team" in ev_cols:
            execute_values(
                cur,
                f"""
                INSERT INTO events ({id_col}, sport, home_team, away_team, commence_time)
                VALUES %s
                ON CONFLICT ({id_col}) DO UPDATE SET
                    commence_time = EXCLUDED.commence_time,
                    home_team = EXCLUDED.home_team,
                    away_team = EXCLUDED.away_team;
                """,
                events_batch,
            )
        elif "match_name" in ev_cols:
            ev_match_batch = [(e[0], e[1], f"{e[2]} - {e[3]}", e[4]) for e in events_batch]
            execute_values(
                cur,
                f"""
                INSERT INTO events ({id_col}, sport, match_name, commence_time)
                VALUES %s
                ON CONFLICT ({id_col}) DO UPDATE SET
                    commence_time = EXCLUDED.commence_time,
                    match_name = EXCLUDED.match_name;
                """,
                ev_match_batch,
            )

    sc = detect_odds_schema(cur)

    if odds_raw and sc["outcome"] and sc["price"]:
        field_order = []
        col_names = []
        for key in ("event_id", "bookmaker", "market", "outcome", "point", "price", "time"):
            if sc[key]:
                field_order.append(key)
                col_names.append(sc[key])

        odds_tuples = [tuple(item[k] for k in field_order) for item in odds_raw]
        cols_sql = ", ".join(col_names)
        execute_values(
            cur,
            f"INSERT INTO odds_history ({cols_sql}) VALUES %s;",
            odds_tuples,
        )

    if sc["time"]:
        cur.execute(f"DELETE FROM odds_history WHERE {sc['time']} < NOW() - INTERVAL '4 days';")
    cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '4 days';")

    conn.commit()
    cur.close()
    conn.close()
    print(f"3. Успішно збережено подій: {len(events_batch)}, котирувань: {len(odds_raw)}")


def format_pick_label(market, outcome, point, match_name):
    out_str = str(outcome).strip()
    if re.match(r"^(?:П1|П2|Х|Ф1|Ф2|ТБ|ТМ)\b", out_str):
        return out_str

    parts = [p.strip() for p in match_name.split(" - ", 1)]
    home_t = parts[0] if len(parts) == 2 else ""
    away_t = parts[1] if len(parts) == 2 else ""

    if market == "h2h":
        if out_str == home_t:
            return f"П1 ({home_t})"
        if out_str == away_t:
            return f"П2 ({away_t})"
        if out_str.lower() == "draw":
            return "Х (Нічия)"
        return out_str

    if market == "spreads":
        pt_str = f"{float(point):+g}" if point is not None else ""
        if out_str == home_t:
            return f"Ф1 ({pt_str})"
        if out_str == away_t:
            return f"Ф2 ({pt_str})"
        return f"Фора {out_str} ({pt_str})"

    if market == "totals":
        pt_str = f"{float(point):g}" if point is not None else ""
        if out_str.lower() == "over":
            return f"ТБ {pt_str}"
        if out_str.lower() == "under":
            return f"ТМ {pt_str}"
        return f"{out_str} {pt_str}".strip()

    if point is not None:
        if out_str.lower() in ("over", "under"):
            return format_pick_label("totals", out_str, point, match_name)
        return format_pick_label("spreads", out_str, point, match_name)

    return format_pick_label("h2h", out_str, None, match_name)


def translate_market_ua(market):
    mapping = {
        "h2h": "Основний результат (1X2)",
        "spreads": "Фора (гандикап)",
        "totals": "Тотал",
    }
    return mapping.get(market, market)


def infer_market_type(outcome_name, point):
    out_s = str(outcome_name).lower()
    if out_s.startswith(("тб", "тм", "over", "under")):
        return "totals"
    if out_s.startswith(("ф1", "ф2", "фора")):
        return "spreads"
    if point is not None:
        if out_s in ("over", "under"):
            return "totals"
        return "spreads"
    return "h2h"


def build_odds_chart(cur, conn, event_id, bookmaker, outcome_name, point, match_name, sport_title, pick_label, sc):
    try:
        ev_c = sc["event_id"]
        bm_c = sc["bookmaker"]
        out_c = sc["outcome"]
        pt_c = sc["point"]
        pr_c = sc["price"]
        tm_c = sc["time"]

        if not (out_c and pr_c and tm_c):
            return None

        if pt_c and point is not None:
            cur.execute(
                f"""
                SELECT {tm_c}, {pr_c}
                FROM odds_history
                WHERE {ev_c} = %s AND {bm_c} = %s AND {out_c} = %s AND {pt_c} = %s
                ORDER BY {tm_c} ASC;
                """,
                (event_id, bookmaker, outcome_name, point),
            )
        elif pt_c and point is None:
            cur.execute(
                f"""
                SELECT {tm_c}, {pr_c}
                FROM odds_history
                WHERE {ev_c} = %s AND {bm_c} = %s AND {out_c} = %s AND {pt_c} IS NULL
                ORDER BY {tm_c} ASC;
                """,
                (event_id, bookmaker, outcome_name),
            )
        else:
            cur.execute(
                f"""
                SELECT {tm_c}, {pr_c}
                FROM odds_history
                WHERE {ev_c} = %s AND {bm_c} = %s AND {out_c} = %s
                ORDER BY {tm_c} ASC;
                """,
                (event_id, bookmaker, outcome_name),
            )

        rows = cur.fetchall()
        if len(rows) < 2:
            return None

        times = []
        prices = []
        for rec_at, pr in rows:
            if rec_at.tzinfo is None:
                rec_at = rec_at.replace(tzinfo=timezone.utc)
            times.append(rec_at.astimezone(KYIV_TZ))
            prices.append(float(pr))

        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=130)
        ax.plot(times, prices, marker="o", linewidth=2.2, markersize=5, color="#c0392b")

        for t, p in zip(times, prices):
            ax.annotate(
                f"{p:.2f}",
                (t, p),
                textcoords="offset points",
                xytext=(0, 7),
                ha="center",
                fontsize=8,
                fontweight="bold",
                color="#2c3e50",
            )

        ax.set_title(
            f"{match_name} ({sport_title})\nСтавка: {pick_label} | БК: {bookmaker}",
            fontsize=10,
            fontweight="bold",
            pad=12,
        )
        ax.set_ylabel("Коефіцієнт", fontsize=9)
        ax.grid(True, linestyle="--", alpha=0.45)

        p_min, p_max = min(prices), max(prices)
        margin = max(0.05, (p_max - p_min) * 0.25)
        ax.set_ylim(p_min - margin, p_max + margin)

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=KYIV_TZ))
        fig.autofmt_xdate(rotation=25)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception as e:
        conn.rollback()
        print(f"Помилка побудови графіка: {e}")
        return None


def format_ai_html(raw_text):
    clean = raw_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
    clean = re.sub(r"^\s*[\*\-]\s+", "• ", clean, flags=re.MULTILINE)
    return clean.strip()


def analyze_match_with_gemini(match_name, sport_title, commence_str, drops_summary):
    if not GEMINI_API_KEY:
        return None

    prompt = (
        f"Ти професійний спортивний аналітик і спеціаліст із руху букмекерських ліній.\n"
        f"Матч: {match_name} (Турнір: {sport_title}, Початок: {commence_str} за Києвом).\n"
        f"Зафіксовані аномальні просідання коефіцієнтів:\n{drops_summary}\n\n"
        f"Надай стислий, структурований український аналіз (до 700 символів) у такому форматі:\n"
        f"📌 **Коротка ставка:** (тільки лаконічний маркет без слів про коефіцієнт, наприклад: П1, Ф2 (+1.5), ТМ 2.5, або Пропустити)\n"
        f"🎯 **Рекомендована ставка:** (чітко вкажи: яку саме ставку брати з коефіцієнтом або чому краще пропустити)\n\n"
        f"📉 **Суть прогрузу:** (1–2 речення: куди йдуть гроші та наскільки сильний сигнал)\n\n"
        f"⚽ **Ігровий контекст:** (2–3 речення: мотивація, форма, клас команд, чи виправданий поточний коефіцієнт)"
    )

    models_to_try = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-3.8-flash"]

    for model_name in models_to_try:
        if model_name in EXHAUSTED_MODELS:
            continue

        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent?key={GEMINI_API_KEY}"
        gen_config = {
            "temperature": 0.35,
            "maxOutputTokens": 900,
        }
        if "2.5" in model_name:
            gen_config["thinkingConfig"] = {"thinkingBudget": 0}

        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": gen_config,
        }

        try:
            resp = requests.post(url, json=payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    text_parts = [p.get("text", "") for p in parts if not p.get("thought")]
                    full_text = "".join(text_parts).strip()
                    if len(full_text) >= 120:
                        print(f"OK Gemini ({model_name}) для {match_name} ({len(full_text)} симв.)")
                        return format_ai_html(full_text)
            elif resp.status_code == 429:
                print(f"Ліміт (429) на {model_name}, перемикаюсь далі...")
                EXHAUSTED_MODELS.add(model_name)
            else:
                print(f"Помилка Gemini {model_name} ({resp.status_code}): {resp.text[:140]}")
        except Exception as e:
            print(f"Виняток при запиті {model_name}: {e}")

    return None


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
                    flags=re.IGNORECASE,
                )[0]
                rec = re.split(r"\s+(?:за|@)\s+[~0-9].*$", rec, maxsplit=1, flags=re.IGNORECASE)[0]
                rec = re.split(r"\.(?:\s|$)", rec, maxsplit=1)[0].strip(" ,;-")
                if rec.count("(") > rec.count(")"):
                    rec += ")" * (rec.count("(") - rec.count(")"))
                if rec:
                    return rec
    return fallback_pick


# --- МОДУЛЬ PAPER TRADING (PAPER_BETS) ---

def get_bankroll_state(cur):
    cur.execute(
        """
        SELECT
            COALESCE(SUM(profit_uah), 0) AS realized_profit,
            COALESCE(SUM(CASE WHEN status = 'PENDING' THEN stake_uah ELSE 0 END), 0) AS locked_stakes
        FROM paper_bets;
        """
    )
    realized_profit, locked_stakes = cur.fetchone()
    total_bank = round(INITIAL_BANKROLL + float(realized_profit), 2)
    available_bank = round(max(0.0, total_bank - float(locked_stakes)), 2)
    return total_bank, available_bank


def calculate_smart_stake(available_bank, odds):
    if available_bank < 50.0:
        return 0.0
    k = float(odds)
    if k <= 1.75:
        pct = 0.04
    elif k <= 2.35:
        pct = 0.03
    else:
        pct = 0.02
    stake = round(available_bank * pct, 2)
    return min(stake, available_bank)


def place_paper_bet(cur, conn, event_id, sport, match_name, commence_time, pick_label, odds):
    try:
        if "пропустити" in pick_label.lower() or "утриматися" in pick_label.lower():
            return None
        cur.execute("SELECT id FROM paper_bets WHERE event_id = %s;", (event_id,))
        if cur.fetchone():
            return None

        _, available_bank = get_bankroll_state(cur)
        stake = calculate_smart_stake(available_bank, odds)
        if stake <= 0:
            return None

        cur.execute(
            """
            INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'PENDING')
            ON CONFLICT (event_id) DO NOTHING;
            """,
            (event_id, sport, match_name, commence_time, pick_label, float(odds), stake),
        )
        conn.commit()
        print(f"💰 Paper Bet: {match_name} | {pick_label} @ {odds} | Ставка: {stake:.2f} грн")
        return stake
    except Exception as e:
        conn.rollback()
        print(f"Помилка place_paper_bet: {e}")
        return None


def parse_score_value(raw_score):
    if raw_score is None:
        return None
    s = str(raw_score).strip()
    try:
        return int(float(s))
    except Exception:
        nums = re.findall(r"\d+", s)
        if nums:
            return int(nums[0])
    return None


def evaluate_bet_outcome(pick_label, match_name, home_score, away_score):
    pick = pick_label.strip()
    parts = [p.strip() for p in match_name.split(" - ", 1)]
    home_team = parts[0].lower() if len(parts) == 2 else ""
    away_team = parts[1].lower() if len(parts) == 2 else ""
    pick_low = pick.lower()

    m_tot = re.search(r"(?:тб|тотал\s*більше|over)\s*\(?([0-9]+(?:\.[0-9]+)?)\)?", pick_low)
    if m_tot:
        line = float(m_tot.group(1))
        total_goals = home_score + away_score
        if total_goals > line:
            return "WON"
        if total_goals < line:
            return "LOST"
        return "VOID"

    m_und = re.search(r"(?:тм|тотал\s*менше|under)\s*\(?([0-9]+(?:\.[0-9]+)?)\)?", pick_low)
    if m_und:
        line = float(m_und.group(1))
        total_goals = home_score + away_score
        if total_goals < line:
            return "WON"
        if total_goals > line:
            return "LOST"
        return "VOID"

    m_hand = re.search(r"ф([12])\s*\(?([+-]?[0-9]+(?:\.[0-9]+)?)\)?", pick_low)
    if m_hand:
        side = m_hand.group(1)
        h_val = float(m_hand.group(2))
        diff = (home_score + h_val - away_score) if side == "1" else (away_score + h_val - home_score)
        if diff > 0:
            return "WON"
        if diff < 0:
            return "LOST"
        return "VOID"

    if re.search(r"(?:^|\b|\()п1(?:\b|\)|$)", pick_low) or (
        home_team and home_team in pick_low and "фора" not in pick_low
    ):
        return "WON" if home_score > away_score else "LOST"

    if re.search(r"(?:^|\b|\()п2(?:\b|\)|$)", pick_low) or (
        away_team and away_team in pick_low and "фора" not in pick_low
    ):
        return "WON" if away_score > home_score else "LOST"

    if re.search(r"(?:^|\b|\()[хx](?:\b|\)|$)", pick_low) or "нічия" in pick_low:
        return "WON" if home_score == away_score else "LOST"

    return None


def settle_finished_paper_bets(cur, conn):
    try:
        cur.execute(
            """
            SELECT id, event_id, sport, match_name, commence_time, pick_label, odds, stake_uah
            FROM paper_bets
            WHERE status = 'PENDING'
              AND commence_time < NOW() - INTERVAL '2 hours 15 minutes'
            ORDER BY commence_time ASC;
            """
        )
        pending = cur.fetchall()
        if not pending:
            return

        sports_needed = list({row[2] for row in pending})
        scores_by_event = {}
        current_key = API_KEY or API_KEY_RESERVE

        for sp in sports_needed:
            url = f"https://api.the-odds-api.com/v4/sports/{sp}/scores/"
            params = {"apiKey": current_key, "daysFrom": 3}
            try:
                resp = requests.get(url, params=params, timeout=12)
                rem = resp.headers.get("x-requests-remaining", "?")
                try:
                    rem_int = int(float(rem))
                except Exception:
                    rem_int = 999

                if (
                    (resp.status_code in (401, 402, 429) or rem_int <= 1)
                    and API_KEY_RESERVE
                    and current_key != API_KEY_RESERVE
                ):
                    current_key = API_KEY_RESERVE
                    params["apiKey"] = current_key
                    resp = requests.get(url, params=params, timeout=12)

                if resp.status_code == 200:
                    for ev in resp.json():
                        if ev.get("completed") and ev.get("scores"):
                            scores_by_event[ev["id"]] = ev
                else:
                    print(f"Scores API ({sp}): {resp.status_code}")
            except Exception as e:
                print(f"Помилка запиту Scores API ({sp}): {e}")

        settled_count = 0
        for bet_id, ev_id, sport, m_name, c_time, pick, odds, stake in pending:
            ev_data = scores_by_event.get(ev_id)
            if not ev_data:
                continue

            home_t = ev_data.get("home_team", "")
            away_t = ev_data.get("away_team", "")
            home_sc, away_sc = None, None
            for s_item in ev_data.get("scores", []):
                if s_item.get("name") == home_t:
                    home_sc = parse_score_value(s_item.get("score"))
                elif s_item.get("name") == away_t:
                    away_sc = parse_score_value(s_item.get("score"))

            if home_sc is None or away_sc is None:
                continue

            score_str = f"{home_sc}:{away_sc}"
            st = evaluate_bet_outcome(pick, f"{home_t} - {away_t}", home_sc, away_sc)
            if st not in ("WON", "LOST", "VOID"):
                print(f"⚠️ Не вдалося автоматично розпізнати маркет '{pick}' для рахунку {score_str}")
                continue

            stake_f = float(stake)
            odds_f = float(odds)
            if st == "WON":
                profit = round(stake_f * (odds_f - 1.0), 2)
            elif st == "LOST":
                profit = round(-stake_f, 2)
            else:
                profit = 0.0

            cur.execute(
                """
                UPDATE paper_bets
                SET status = %s, match_score = %s, profit_uah = %s, settled_at = NOW()
                WHERE id = %s AND status = 'PENDING';
                """,
                (st, score_str, profit, bet_id),
            )
            settled_count += 1
            print(f"📊 Розраховано #{bet_id} ({m_name}): {score_str} | {pick} -> {st} ({profit:+.2f} грн)")

        if settled_count > 0:
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Помилка settle_finished_paper_bets: {e}")


def send_daily_bankroll_report(cur, conn):
    try:
        kyiv_now = datetime.now(KYIV_TZ)
        if kyiv_now.hour < 8:
            return
        today_date = kyiv_now.date()
        cur.execute("SELECT 1 FROM paper_daily_reports WHERE report_date = %s;", (today_date,))
        if cur.fetchone():
            return

        cur.execute(
            """
            SELECT
                COUNT(*) AS total_bets,
                COUNT(*) FILTER (WHERE status = 'WON') AS won_bets,
                COUNT(*) FILTER (WHERE status = 'LOST') AS lost_bets,
                COUNT(*) FILTER (WHERE status = 'VOID') AS void_bets,
                COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_bets,
                COALESCE(SUM(stake_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS settled_turnover,
                COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON', 'LOST', 'VOID')), 0) AS net_profit
            FROM paper_bets;
            """
        )
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
        cur.execute(
            "INSERT INTO paper_daily_reports (report_date) VALUES (%s) ON CONFLICT DO NOTHING;",
            (today_date,),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Помилка send_daily_bankroll_report: {e}")


def parse_alert_row(row, v_cols):
    d = dict(zip(v_cols, row))
    ev_id = pick_val(d, ("event_id", "id", "match_id"), row[0] if len(row) > 0 else "")
    sport = pick_val(d, ("sport", "sport_key", "league"), row[1] if len(row) > 1 else "")
    match = pick_val(d, ("match_name", "match", "event_name"), row[2] if len(row) > 2 else "")
    c_time = pick_val(d, ("commence_time", "match_time", "event_time"), row[3] if len(row) > 3 else None)
    bm = pick_val(d, ("bookmaker", "bm", "bookie"), row[4] if len(row) > 4 else "")
    outcome = pick_val(
        d,
        ("outcome_name", "outcome", "selection", "team", "side", "bet_name", "name"),
        row[5] if len(row) > 5 else "",
    )
    market = pick_val(d, ("market_key", "market", "market_type", "mkt"), None)
    point = pick_val(d, ("point", "handicap", "line", "points"), None)

    if market is None and point is None and len(row) > 6:
        val6 = row[6]
        if isinstance(val6, str) and val6.lower() in ("h2h", "spreads", "totals"):
            market = val6.lower()
        elif isinstance(val6, (int, float)) or (
            isinstance(val6, str) and re.match(r"^[+-]?\d+(?:\.\d+)?$", val6.strip())
        ):
            point = float(val6)

    start_k = pick_val(
        d,
        ("start_odds", "initial_odds", "open_odds", "first_odds", "old_odds", "prev_odds", "start_price", "first_price"),
        row[7] if len(row) > 7 else 0.0,
    )
    curr_k = pick_val(
        d,
        ("current_odds", "curr_odds", "latest_odds", "last_odds", "new_odds", "odds", "price", "current_price", "last_price"),
        row[8] if len(row) > 8 else 0.0,
    )
    drop_pct = pick_val(
        d,
        ("drop_pct", "change_pct", "diff_pct", "pct_change", "drop_percent", "drop"),
        row[9] if len(row) > 9 else 0.0,
    )
    start_t = pick_val(
        d,
        ("start_time", "first_time", "initial_time", "open_time", "old_time", "recorded_at"),
        row[10] if len(row) > 10 else None,
    )

    return {
        "event_id": ev_id,
        "sport": sport,
        "match": match,
        "commence_time": c_time,
        "bookmaker": bm,
        "outcome": outcome,
        "market": market,
        "point": point,
        "start_odds": float(start_k) if start_k is not None else 0.0,
        "current_odds": float(curr_k) if curr_k is not None else 0.0,
        "drop_pct": float(drop_pct) if drop_pct is not None else 0.0,
        "start_time": start_t,
    }


# --- ОСНОВНИЙ ЦИКЛ ОБРОБКИ АЛЕРТІВ ---

def check_alerts_and_notify(sports_titles_map):
    print("4. Перевірка алертів, AI-аналіз та відправка в Telegram...")
    conn = get_db_connection()
    cur = conn.cursor()
    ensure_tables_exist(cur, conn)
    sc = detect_odds_schema(cur)

    settle_finished_paper_bets(cur, conn)
    send_daily_bankroll_report(cur, conn)

    kyiv_now = datetime.now(KYIV_TZ)
    status_line = f"✅ коеф. {kyiv_now.strftime('%d.%m.%Y')} оновлено в {kyiv_now.strftime('%H:%M')}"
    send_telegram_alert(status_line)

    cur.execute("SELECT * FROM v_odds_alerts;")
    v_cols = [desc[0] for desc in cur.description]
    raw_rows = cur.fetchall()
    print(f"Колонки v_odds_alerts: {v_cols} (отримано рядків: {len(raw_rows)})")

    filtered_alerts = []
    for row in raw_rows:
        item = parse_alert_row(row, v_cols)
        if item["current_odds"] <= 0 or item["current_odds"] > 4.00:
            continue
        if item["point"] is not None and abs((float(item["point"]) * 100) % 50) != 0:
            continue
        if re.search(r"\d+\.(?:25|75)\b", str(item["outcome"])):
            continue
        filtered_alerts.append(item)

    filtered_alerts.sort(key=lambda x: x["drop_pct"])
    filtered_alerts = filtered_alerts[:40]

    grouped_alerts = {}
    for item in filtered_alerts:
        ev_id = item["event_id"]
        if ev_id not in grouped_alerts:
            grouped_alerts[ev_id] = []
        grouped_alerts[ev_id].append(item)

    summary_table_rows = []
    processed_events = 0

    for ev_id, alerts_list in grouped_alerts.items():
        if processed_events >= 15:
            break
        processed_events += 1

        first = alerts_list[0]
        sport = first["sport"]
        match = first["match"]
        c_time = first["commence_time"]
        top_bm = first["bookmaker"]
        top_outcome = first["outcome"]
        top_point = first["point"]
        top_curr_k = first["current_odds"]

        sport_title = sports_titles_map.get(sport, sport)
        c_str = format_kyiv_time(c_time)

        top_market = first["market"] or infer_market_type(top_outcome, top_point)
        if not first["market"] and sc["market"] and sc["outcome"] and sc["time"]:
            try:
                cur.execute(
                    f"""
                    SELECT {sc['market']}
                    FROM odds_history
                    WHERE {sc['event_id']} = %s AND {sc['bookmaker']} = %s AND {sc['outcome']} = %s
                    ORDER BY {sc['time']} DESC LIMIT 1;
                    """,
                    (ev_id, top_bm, top_outcome),
                )
                m_res = cur.fetchone()
                if m_res and m_res[0]:
                    top_market = m_res[0]
            except Exception:
                conn.rollback()

        top_pick_label = format_pick_label(top_market, top_outcome, top_point, match)

        plain_drops = []
        html_drops = []
        for al in alerts_list[:4]:
            bm = al["bookmaker"]
            out_n = al["outcome"]
            pt = al["point"]
            s_k = al["start_odds"]
            curr_k = al["current_odds"]
            d_pct = al["drop_pct"]
            s_t = al["start_time"]

            mk = al["market"] or infer_market_type(out_n, pt)
            if not al["market"] and sc["market"] and sc["outcome"] and sc["time"]:
                try:
                    cur.execute(
                        f"""
                        SELECT {sc['market']} FROM odds_history
                        WHERE {sc['event_id']} = %s AND {sc['bookmaker']} = %s AND {sc['outcome']} = %s
                        ORDER BY {sc['time']} DESC LIMIT 1;
                        """,
                        (ev_id, bm, out_n),
                    )
                    mk_row = cur.fetchone()
                    if mk_row and mk_row[0]:
                        mk = mk_row[0]
                except Exception:
                    conn.rollback()

            p_lbl = format_pick_label(mk, out_n, pt, match)
            s_time_str = format_kyiv_time(s_t)

            plain_drops.append(f"- {p_lbl} ({bm}): {s_k} -> {curr_k} ({d_pct}%)")
            html_drops.append(
                f"📉 <b>{p_lbl}</b> | БК: <code>{bm}</code>\n"
                f"   <code>{s_k:.3f}</code> ({s_time_str}) ➔ <b><code>{curr_k:.3f}</code></b> (<b>{d_pct}%</b>)"
            )

        card_caption = (
            f"⚽ <b>{match}</b>\n"
            f"🏆 <i>{sport_title}</i>\n"
            f"🗓 Початок: <code>{c_str}</code>\n"
            f"🎯 Ринок: {translate_market_ua(top_market)} | <b>{top_pick_label}</b>\n\n"
            + "\n".join(html_drops)
        )

        chart_buf = build_odds_chart(
            cur, conn, ev_id, top_bm, top_outcome, top_point, match, sport_title, top_pick_label, sc
        )
        if chart_buf:
            send_telegram_photo(chart_buf, card_caption)
        else:
            send_telegram_alert(card_caption)

        ai_verdict = None
        try:
            cur.execute(
                """
                SELECT verdict_text FROM ai_match_analysis
                WHERE verdict_text LIKE '%Коротка ставка%'
                  AND event_id = %s
                  AND created_at > NOW() - INTERVAL '12 hours';
                """,
                (ev_id,),
            )
            cached = cur.fetchone()
            if cached:
                ai_verdict = cached[0]
            else:
                ai_verdict = analyze_match_with_gemini(match, sport_title, c_str, "\n".join(plain_drops))
                if ai_verdict:
                    cur.execute(
                        """
                        INSERT INTO ai_match_analysis (event_id, verdict_text, created_at)
                        VALUES (%s, %s, NOW())
                        ON CONFLICT (event_id) DO UPDATE SET
                            verdict_text = EXCLUDED.verdict_text,
                            created_at = NOW();
                        """,
                        (ev_id, ai_verdict),
                    )
                    conn.commit()
                    time.sleep(3)
        except Exception as e:
            conn.rollback()
            print(f"Помилка кешу AI: {e}")

        if ai_verdict:
            ai_msg = f"🧠 <b>AI-аналіз: {match}</b>\n\n{ai_verdict}"
            send_telegram_alert(ai_msg)

            short_pick = extract_short_pick(ai_verdict, top_pick_label)
            place_paper_bet(cur, conn, ev_id, sport, match, c_time, short_pick, top_curr_k)

            sort_dt = (
                c_time
                if hasattr(c_time, "tzinfo") and c_time.tzinfo
                else (c_time.replace(tzinfo=timezone.utc) if hasattr(c_time, "replace") else datetime.now(timezone.utc))
            )
            summary_table_rows.append(
                {
                    "dt": sort_dt,
                    "time": c_str,
                    "match": match,
                    "championship": sport_title,
                    "pick": short_pick,
                    "odds": f"{float(top_curr_k):.2f}",
                }
            )

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

    cur.close()
    conn.close()


if __name__ == "__main__":
    active_sports_map = get_active_sports_map()
    fetch_and_save_odds(active_sports_map)
    check_alerts_and_notify(active_sports_map)
