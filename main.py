import os, re, io, time
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import requests, psycopg2
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
try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except Exception:
    KYIV_TZ = timezone(timedelta(hours=2))
EXHAUSTED_MODELS = set()

TARGET_SPORTS = [
    "soccer_epl", "soccer_spain_la_liga", "soccer_italy_serie_a",
    "soccer_germany_bundesliga", "soccer_france_ligue_one",
    "soccer_ukraine_premier_league", "soccer_poland_ekstraklasa",
    "soccer_uefa_champs_league", "soccer_uefa_europa_league",
    "soccer_uefa_conference_league", "soccer_uefa_nations_league",
    "basketball_nba", "tennis_atp_tour_finals", "tennis_wta_finals",
]

def get_db():
    return psycopg2.connect(DB_URL)

def esc(val):
    return str(val or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def fmt_kyiv(dt_obj):
    if not dt_obj:
        return ""
    if isinstance(dt_obj, str):
        return dt_obj
    if dt_obj.tzinfo is None:
        dt_obj = dt_obj.replace(tzinfo=timezone.utc)
    return dt_obj.astimezone(KYIV_TZ).strftime("%d.%m %H:%M")

def get_cols(cur, table):
    cur.execute("SELECT column_name FROM information_schema.columns WHERE table_schema='public' AND table_name=%s;", (table,))
    return {r[0] for r in cur.fetchall()}

def pick(cols, names, default=None):
    for n in names:
        if n in cols:
            return n
    return default

def pick_v(d, names, default=None):
    for n in names:
        if n in d and d[n] is not None:
            return d[n]
    return default

def ensure_tables(cur, conn):
    try:
        from migrate import run_migrations
        run_migrations(db_url=SUPABASE_DB_URL)
    except Exception as e:
        print(f"Migrations run notice: {e}")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ai_match_analysis (
                event_id TEXT PRIMARY KEY, verdict_text TEXT NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
            );
            CREATE TABLE IF NOT EXISTS paper_bets (
                id SERIAL PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, sport TEXT NOT NULL,
                match_name TEXT NOT NULL, commence_time TIMESTAMPTZ NOT NULL, pick_label TEXT NOT NULL,
                odds NUMERIC(6,3) NOT NULL, stake_uah NUMERIC(10,2) NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING', match_score TEXT,
                profit_uah NUMERIC(10,2) NOT NULL DEFAULT 0.00,
                created_at TIMESTAMPTZ DEFAULT NOW(), settled_at TIMESTAMPTZ
            );
            CREATE TABLE IF NOT EXISTS paper_daily_reports (
                report_date DATE PRIMARY KEY, sent_at TIMESTAMPTZ DEFAULT NOW()
            );
        """)
        conn.commit()

def _post_tg_chunk(url, chunk):
    for attempt in range(2):
        try:
            r = requests.post(url, json={"chat_id": TG_CHAT_ID, "text": chunk, "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=12)
            if r.status_code == 200:
                time.sleep(0.45)
                return
            if r.status_code == 429:
                wait_s = r.json().get("parameters", {}).get("retry_after", 5)
                print(f"TG 429 pause {wait_s}s...")
                time.sleep(int(wait_s) + 1)
                continue
            print(f"TG HTML err ({r.status_code}): {r.text[:120]}")
            plain = re.sub(r"<[^>]+>", "", chunk)
            requests.post(url, json={"chat_id": TG_CHAT_ID, "text": plain, "disable_web_page_preview": True}, timeout=12)
            time.sleep(0.45)
            return
        except Exception as e:
            print(f"TG msg err: {e}")

def send_tg(text):
    if not TG_BOT_TOKEN or not TG_CHAT_ID or not text:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    if len(text) <= 3800:
        _post_tg_chunk(url, text)
        return
    blocks = text.split("\n\n")
    buf = ""
    for b in blocks:
        if len(buf) + len(b) + 2 > 3800 and buf:
            _post_tg_chunk(url, buf)
            buf = b
        else:
            buf = f"{buf}\n\n{b}" if buf else b
    if buf:
        _post_tg_chunk(url, buf)

def send_photo(buf, caption):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendPhoto"
    for attempt in range(2):
        try:
            buf.seek(0)
            r = requests.post(
                url,
                data={"chat_id": TG_CHAT_ID, "caption": caption, "parse_mode": "HTML"},
                files={"photo": ("chart.png", buf, "image/png")},
                timeout=20,
            )
            if r.status_code == 200:
                time.sleep(0.45)
                return
            if r.status_code == 429:
                wait_s = r.json().get("parameters", {}).get("retry_after", 5)
                time.sleep(int(wait_s) + 1)
                continue
            print(f"TG photo err ({r.status_code}): {r.text[:120]}")
            return
        except Exception as e:
            print(f"TG photo err: {e}")
            return

def get_sports_map():
    for k in [x for x in (API_KEY, API_KEY_RESERVE) if x]:
        try:
            r = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": k}, timeout=12)
            if r.status_code == 200:
                res = {s["key"]: s.get("title", s["key"]) for s in r.json() if s.get("key") in TARGET_SPORTS and s.get("active")}
                if res:
                    return res
        except Exception:
            pass
    return {k: k for k in TARGET_SPORTS}

def fetch_and_save_odds(sports_map):
    now_utc = datetime.now(timezone.utc)
    to_str = (now_utc + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    print(f"1. Турніри ({len(sports_map)}): {list(sports_map.keys())}")

    events_batch, odds_raw = [], []
    rem_credits, cur_key, using_res = "?", (API_KEY or API_KEY_RESERVE), (not API_KEY and bool(API_KEY_RESERVE))

    for sp in sports_map:
        url = f"https://api.the-odds-api.com/v4/sports/{sp}/odds/"
        params = {"apiKey": cur_key, "regions": "eu", "markets": "h2h,totals,spreads", "commenceTimeTo": to_str}
        try:
            r = requests.get(url, params=params, timeout=12)
            rem_credits = r.headers.get("x-requests-remaining", rem_credits)
            rem_int = int(float(rem_credits)) if str(rem_credits).replace(".", "").isdigit() else 999
            if (r.status_code in (401, 402, 429) or rem_int <= 1) and not using_res and API_KEY_RESERVE:
                cur_key, using_res = API_KEY_RESERVE, True
                params["apiKey"] = cur_key
                r = requests.get(url, params=params, timeout=12)
                rem_credits = r.headers.get("x-requests-remaining", rem_credits)
            if r.status_code != 200:
                continue
            for ev in r.json():
                events_batch.append((ev["id"], sp, ev.get("home_team", ""), ev.get("away_team", ""), ev["commence_time"]))
                for bm in ev.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        for out in mkt.get("outcomes", []):
                            if out.get("price") is not None:
                                odds_raw.append({
                                    "event_id": ev["id"], "bookmaker": bm["key"], "market": mkt["key"],
                                    "outcome": out.get("name", ""), "point": out.get("point"),
                                    "price": out["price"], "time": now_utc
                                })
        except Exception as e:
            print(f"API err {sp}: {e}")

    print(f"2. Залишок кредитів: {rem_credits}")
    conn = get_db()
    cur = conn.cursor()
    ensure_tables(cur, conn)

    ev_cols = get_cols(cur, "events")
    if events_batch:
        id_c = pick(ev_cols, ("id", "event_id"), "id")
        if "home_team" in ev_cols:
            execute_values(cur, f"INSERT INTO events ({id_c}, sport, home_team, away_team, commence_time) VALUES %s ON CONFLICT ({id_c}) DO UPDATE SET commence_time=EXCLUDED.commence_time;", events_batch)
        elif "match_name" in ev_cols:
            execute_values(cur, f"INSERT INTO events ({id_c}, sport, match_name, commence_time) VALUES %s ON CONFLICT ({id_c}) DO UPDATE SET commence_time=EXCLUDED.commence_time;", [(e[0], e[1], f"{e[2]} - {e[3]}", e[4]) for e in events_batch])

    oh_cols = get_cols(cur, "odds_history")
    sc = {
        "event_id": pick(oh_cols, ("event_id", "match_id")),
        "bookmaker": pick(oh_cols, ("bookmaker", "bm")),
        "market": pick(oh_cols, ("market_key", "market", "mkt")),
        "outcome": pick(oh_cols, ("outcome_name", "outcome", "selection", "name")),
        "point": pick(oh_cols, ("point", "handicap", "line")),
        "price": pick(oh_cols, ("price", "odds", "value")),
        "time": pick(oh_cols, ("recorded_at", "created_at", "timestamp")),
    }
    if odds_raw and sc["outcome"] and sc["price"]:
        keys = [k for k in ("event_id", "bookmaker", "market", "outcome", "point", "price", "time") if sc[k]]
        cols_sql = ", ".join(sc[k] for k in keys)
        execute_values(cur, f"INSERT INTO odds_history ({cols_sql}) VALUES %s;", [tuple(x[k] for k in keys) for x in odds_raw])

    if sc["time"]:
        cur.execute(f"DELETE FROM odds_history WHERE {sc['time']} < NOW() - INTERVAL '4 days';")
    cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '4 days';")
    conn.commit()
    cur.close()
    conn.close()
    print(f"3. Збережено подій: {len(events_batch)}, котирувань: {len(odds_raw)}")

def format_pick(market, outcome, point, match_name):
    out_s = str(outcome).strip()
    if re.match(r"^(?:П1|П2|Х|Ф1|Ф2|ТБ|ТМ)\b", out_s):
        return out_s
    parts = [p.strip() for p in match_name.split(" - ", 1)]
    h_t, a_t = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
    if market == "totals" or out_s.lower() in ("over", "under"):
        pt = f"{float(point):g}" if point is not None else ""
        return f"{'ТБ' if out_s.lower() == 'over' else 'ТМ'} {pt}".strip()
    if market == "spreads" or point is not None:
        pt = f"{float(point):+g}" if point is not None else ""
        if out_s == h_t: return f"Ф1 ({pt})"
        if out_s == a_t: return f"Ф2 ({pt})"
        return f"Фора {out_s} ({pt})"
    if out_s == h_t: return f"П1 ({h_t})"
    if out_s == a_t: return f"П2 ({a_t})"
    return "Х (Нічия)" if out_s.lower() == "draw" else out_s

def build_chart(cur, conn, ev_id, bm, out_n, pt, match, title, pick_lbl, sc):
    try:
        if not (sc["outcome"] and sc["price"] and sc["time"]):
            return None
        q = f"SELECT {sc['time']}, {sc['price']} FROM odds_history WHERE {sc['event_id']}=%s AND {sc['bookmaker']}=%s AND {sc['outcome']}=%s"
        args = [ev_id, bm, out_n]
        if sc["point"]:
            q += f" AND {sc['point']}=%s" if pt is not None else f" AND {sc['point']} IS NULL"
            if pt is not None:
                args.append(pt)
        cur.execute(q + f" ORDER BY {sc['time']} ASC;", tuple(args))
        rows = cur.fetchall()
        if len(rows) < 2:
            return None
        times = [(r[0].replace(tzinfo=timezone.utc) if r[0].tzinfo is None else r[0]).astimezone(KYIV_TZ) for r in rows]
        prices = [float(r[1]) for r in rows]

        fig, ax = plt.subplots(figsize=(7.5, 3.6), dpi=130)
        ax.plot(times, prices, marker="o", linewidth=2.2, markersize=5, color="#c0392b")
        for t, p in zip(times, prices):
            ax.annotate(f"{p:.2f}", (t, p), textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8, fontweight="bold")
        ax.set_title(f"{match} ({title})\nСтавка: {pick_lbl} | БК: {bm}", fontsize=10, fontweight="bold", pad=12)
        ax.grid(True, linestyle="--", alpha=0.45)
        margin = max(0.05, (max(prices) - min(prices)) * 0.25)
        ax.set_ylim(min(prices) - margin, max(prices) + margin)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m %H:%M", tz=KYIV_TZ))
        fig.autofmt_xdate(rotation=25)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png")
        plt.close(fig)
        buf.seek(0)
        return buf
    except Exception:
        conn.rollback()
        return None

def analyze_gemini(match, title, c_str, drops):
    if not GEMINI_API_KEY:
        return None
    prompt = (
        f"Ти професійний спортивний аналітик та експерт з оцінки букмекерських рухів ліній (Smart Money).\n"
        f"Матч: {match} ({title}, початок {c_str} за Києвом).\n"
        f"Просідання коефіцієнтів (рух ринку):\n{drops}\n\n"
        f"Проведи глибокий аналіз матчу українською мовою з урахуванням складів, поточної форми, свіжих новин та прихованих причин руху котирувань.\n"
        f"Формат відповіді (строго за цими розділами, до 1100 символів):\n"
        f"📌 **Коротка ставка:** (тільки маркет без слів про коефіцієнт: П1, Ф2 (+1.5), ТМ 2.5 або Пропустити)\n"
        f"🎯 **Рекомендована ставка:** (чітка рекомендація: брати чи пропустити, і чому)\n\n"
        f"🏥 **Склади та кадрові втрати:** (травми, дискваліфікації лідерів, очікувана ротація чи підтверджені склади)\n"
        f"🔥 **Поточна форма та тонус:** (серії команд, тонус ключових бомбардирів/воротарів, втома через календар)\n"
        f"🗣️ **Інсайди, чутки та суть прогрузу:** (чому саме сюди йдуть великі гроші: інсайд про проблеми, зміна тактики чи пастка бука)\n"
        f"⚖️ **Оцінка валую (Value):** (чи вигідний поточний коефіцієнт після падіння, чи лінію вже віджали занадто низько)"
    )
    for model in ["gemini-3.5-flash-lite", "gemini-2.5-flash-lite", "gemini-2.5-flash", "gemini-3.8-flash"]:
        if model in EXHAUSTED_MODELS:
            continue
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        cfg = {"temperature": 0.35, "maxOutputTokens": 1200}
        if "2.5" in model:
            cfg["thinkingConfig"] = {"thinkingBudget": 0}

        # Спочатку намагаємося використати Google Search Grounding для свіжих новин/складів
        payload_with_search = {
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"google_search": {}}],
            "generationConfig": cfg,
        }
        try:
            r = requests.post(url, json=payload_with_search, timeout=35)
            # Якщо модель не підтримує tools у даному режимі, повторюємо чистий запит
            if r.status_code != 200:
                payload_pure = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": cfg}
                r = requests.post(url, json=payload_pure, timeout=30)

            if r.status_code == 200:
                parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                txt = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
                if len(txt) >= 40:
                    clean = esc(txt)
                    clean = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", clean)
                    return clean
            elif r.status_code in (404, 429):
                EXHAUSTED_MODELS.add(model)
        except Exception:
            pass
    return None

def extract_short_pick(ai_verdict, fallback):
    if not ai_verdict:
        return fallback
    for tag in ("Коротка ставка", "Рекомендована ставка"):
        for line in ai_verdict.splitlines():
            if tag in line:
                clean = re.sub(r"<[^>]+>", "", line)
                if ":" in clean:
                    rec = clean.split(":", 1)[1].strip()
                    if any(w in rec.lower() for w in ("пропустити", "утриматися")):
                        return "⏭ Пропустити матч"
                    rec = re.split(r"\s*(?:,|\()?\s*(?:з|по|за|у|в)?\s*(?:поточн\w+|орієнтовн\w+)?\s*(?:коефіцієнт\w*|кеф\w*|@)\s*(?:близько|біля|в районі|у діапазоні)?\s*[~0-9].*$", rec, maxsplit=1, flags=re.I)[0]
                    rec = re.split(r"\.(?:\s|$)", rec, maxsplit=1)[0].strip(" ,;-")
                    if len(rec) > 55:
                        rec = rec[:55].rsplit(" ", 1)[0].strip(" ,;-")
                    if rec.count("(") > rec.count(")"):
                        rec += ")" * (rec.count("(") - rec.count(")"))
                    if rec:
                        return rec
    return fallback

def place_paper_bet(cur, conn, ev_id, sport, match, c_time, pick_lbl, odds):
    try:
        if any(w in pick_lbl.lower() for w in ("пропустити", "утриматися")):
            return
        cur.execute("SELECT 1 FROM paper_bets WHERE event_id=%s;", (ev_id,))
        if cur.fetchone():
            return
        cur.execute("SELECT COALESCE(SUM(profit_uah),0), COALESCE(SUM(CASE WHEN status='PENDING' THEN stake_uah ELSE 0 END),0) FROM paper_bets;")
        prof, locked = cur.fetchone()
        avail = round(max(0.0, INITIAL_BANKROLL + float(prof) - float(locked)), 2)
        if avail < 50:
            return
        k = float(odds)
        pct = 0.04 if k <= 1.75 else (0.03 if k <= 2.35 else 0.02)
        stake = min(round(avail * pct, 2), avail)
        cur.execute(
            "INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;",
            (ev_id, sport, match, c_time, pick_lbl, k, stake),
        )
        conn.commit()
    except Exception:
        conn.rollback()

def eval_outcome(pick_lbl, match_name, h_sc, a_sc):
    p = pick_lbl.lower()
    parts = [x.strip().lower() for x in match_name.split(" - ", 1)]
    h_t, a_t = (parts[0], parts[1]) if len(parts) == 2 else ("", "")
    m_tb = re.search(r"(?:тб|over)\s*\(?([0-9.]+)\)?", p)
    if m_tb:
        ln = float(m_tb.group(1))
        return "WON" if (h_sc + a_sc) > ln else ("LOST" if (h_sc + a_sc) < ln else "VOID")
    m_tm = re.search(r"(?:тм|under)\s*\(?([0-9.]+)\)?", p)
    if m_tm:
        ln = float(m_tm.group(1))
        return "WON" if (h_sc + a_sc) < ln else ("LOST" if (h_sc + a_sc) > ln else "VOID")
    m_f = re.search(r"ф([12])\s*\(?([+-]?[0-9.]+)\)?", p)
    if m_f:
        hv = float(m_f.group(2))
        diff = (h_sc + hv - a_sc) if m_f.group(1) == "1" else (a_sc + hv - h_sc)
        return "WON" if diff > 0 else ("LOST" if diff < 0 else "VOID")
    if re.search(r"(?:^|\b|\()п1(?:\b|\)|$)", p) or (h_t and h_t in p):
        return "WON" if h_sc > a_sc else "LOST"
    if re.search(r"(?:^|\b|\()п2(?:\b|\)|$)", p) or (a_t and a_t in p):
        return "WON" if a_sc > h_sc else "LOST"
    if re.search(r"(?:^|\b|\()[хx](?:\b|\)|$)", p) or "нічия" in p:
        return "WON" if h_sc == a_sc else "LOST"
    return None

def settle_and_report(cur, conn):
    try:
        cur.execute("SELECT id, event_id, sport, match_name, pick_label, odds, stake_uah FROM paper_bets WHERE status='PENDING' AND commence_time < NOW() - INTERVAL '2 hours 15 minutes';")
        pending = cur.fetchall()
        if pending:
            scores = {}
            cur_k = API_KEY or API_KEY_RESERVE
            for sp in {r[2] for r in pending}:
                r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sp}/scores/", params={"apiKey": cur_k, "daysFrom": 3}, timeout=12)
                if r.status_code != 200 and API_KEY_RESERVE and cur_k != API_KEY_RESERVE:
                    cur_k = API_KEY_RESERVE
                    r = requests.get(f"https://api.the-odds-api.com/v4/sports/{sp}/scores/", params={"apiKey": cur_k, "daysFrom": 3}, timeout=12)
                if r.status_code == 200:
                    for ev in r.json():
                        if ev.get("completed") and ev.get("scores"):
                            scores[ev["id"]] = ev
            for bid, eid, sp, m_name, pk, odds, st in pending:
                ev = scores.get(eid)
                if not ev:
                    continue
                sc_map = {s["name"]: int(re.findall(r"\d+", str(s["score"]))[0]) for s in ev["scores"] if re.findall(r"\d+", str(s.get("score", "")))}
                hs, as_ = sc_map.get(ev.get("home_team")), sc_map.get(ev.get("away_team"))
                if hs is None or as_ is None:
                    continue
                res = eval_outcome(pk, f"{ev.get('home_team')} - {ev.get('away_team')}", hs, as_)
                if res in ("WON", "LOST", "VOID"):
                    prof = round(float(st) * (float(odds) - 1), 2) if res == "WON" else (round(-float(st), 2) if res == "LOST" else 0.0)
                    cur.execute("UPDATE paper_bets SET status=%s, match_score=%s, profit_uah=%s, settled_at=NOW() WHERE id=%s;", (res, f"{hs}:{as_}", prof, bid))
            conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Settle err: {e}")

    try:
        kyiv_now = datetime.now(KYIV_TZ)
        if kyiv_now.hour >= 8:
            cur.execute("SELECT 1 FROM paper_daily_reports WHERE report_date=%s;", (kyiv_now.date(),))
            if not cur.fetchone():
                cur.execute("""
                    SELECT COUNT(*), COUNT(*) FILTER (WHERE status='WON'), COUNT(*) FILTER (WHERE status='LOST'),
                           COUNT(*) FILTER (WHERE status='VOID'), COUNT(*) FILTER (WHERE status='PENDING'),
                           COALESCE(SUM(stake_uah) FILTER (WHERE status IN ('WON','LOST','VOID')),0),
                           COALESCE(SUM(profit_uah) FILTER (WHERE status IN ('WON','LOST','VOID')),0)
                    FROM paper_bets;
                """)
                tot, won, lost, void, pend, turn, net = cur.fetchone()
                fin = round(INITIAL_BANKROLL + float(net), 2)
                roi = round((float(net) / float(turn)) * 100, 2) if float(turn) > 0 else 0.0
                send_tg(
                    f"💼 <b>ЩОДЕННИЙ ЗВІТ PAPER BANK ({kyiv_now.strftime('%d.%m.%Y')})</b>\n\n"
                    f"🏦 Початковий банк: <code>{INITIAL_BANKROLL:,.2f} грн</code>\n"
                    f"💰 Кінцевий банк: <b><code>{fin:,.2f} грн</code></b> (<code>{fin - INITIAL_BANKROLL:+.2f} грн</code>)\n"
                    f"📈 ROI: <b><code>{roi:+.2f}%</code></b>\n\n"
                    f"📊 Всього ставок: <b>{tot}</b> (в грі: {pend})\n"
                    f"✅ Виграшні: <b>{won}</b> | ❌ Програшні: <b>{lost}</b> | 🔄 Повернення: <b>{void}</b>"
                )
                cur.execute("INSERT INTO paper_daily_reports (report_date) VALUES (%s) ON CONFLICT DO NOTHING;", (kyiv_now.date(),))
                conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"Report err: {e}")

def check_alerts_and_notify(sports_map, t_start=None):
    print("4. Перевірка алертів і відправка...")
    conn = get_db()
    cur = conn.cursor()
    ensure_tables(cur, conn)

    # 0. Watchdog Healthcheck (SPEC-09)
    try:
        from sys_watchdog import check_watchdog_before_run
        w_alert = check_watchdog_before_run(cur, conn)
        if w_alert:
            send_tg(w_alert)
    except Exception as e:
        print(f"Watchdog check err: {e}")

    settle_and_report(cur, conn)

    oh_cols = get_cols(cur, "odds_history")
    sc = {
        "event_id": pick(oh_cols, ("event_id", "match_id")),
        "bookmaker": pick(oh_cols, ("bookmaker", "bm")),
        "outcome": pick(oh_cols, ("outcome_name", "outcome", "selection", "name")),
        "point": pick(oh_cols, ("point", "handicap", "line")),
        "price": pick(oh_cols, ("price", "odds", "value")),
        "time": pick(oh_cols, ("recorded_at", "created_at", "timestamp")),
    }
    ai_cols = get_cols(cur, "ai_match_analysis")
    ai_txt = pick(ai_cols, ("verdict_text", "analysis_text", "analysis", "verdict", "text"), "verdict_text")
    ai_tm = pick(ai_cols, ("created_at", "updated_at", "recorded_at"))

    kyiv_now = datetime.now(KYIV_TZ)
    send_tg(f"✅ коеф. {kyiv_now.strftime('%d.%m.%Y')} оновлено в {kyiv_now.strftime('%H:%M')}")

    cur.execute("SELECT * FROM v_odds_alerts;")
    v_cols = [d[0] for d in cur.description]
    items = []
    for r in cur.fetchall():
        d = dict(zip(v_cols, r))
        curr_k = float(pick_v(d, ("current_odds", "curr_odds", "last_odds", "odds", "price"), 0) or 0)
        pt = pick_v(d, ("point", "handicap", "line"))
        out = pick_v(d, ("outcome_name", "outcome", "selection", "side", "name"), "")
        if curr_k < 1.40 or curr_k > 4.00:
            continue
        if pt is not None and abs((float(pt) * 100) % 50) != 0:
            continue
        if re.search(r"\d+\.(?:25|75)\b", str(out)):
            continue
        items.append({
            "event_id": pick_v(d, ("event_id", "id", "match_id"), r[0]),
            "sport": pick_v(d, ("sport", "sport_key"), r[1]),
            "match": pick_v(d, ("match_name", "match"), r[2]),
            "c_time": pick_v(d, ("commence_time", "match_time"), r[3]),
            "bm": pick_v(d, ("bookmaker", "bm"), r[4]),
            "outcome": out,
            "market": pick_v(d, ("market_key", "market")),
            "point": float(pt) if pt is not None else None,
            "start_k": float(pick_v(d, ("start_odds", "initial_odds", "open_odds", "first_odds", "start_price"), 0) or 0),
            "curr_k": curr_k,
            "drop": float(pick_v(d, ("drop_pct", "change_pct", "diff_pct", "drop"), 0) or 0),
            "s_time": pick_v(d, ("start_time", "first_time", "recorded_at")),
        })

    items.sort(key=lambda x: x["drop"])
    grouped = {}
    for it in items[:40]:
        grouped.setdefault(it["event_id"], []).append(it)

    summary_rows = []
    for ev_id, grp in list(grouped.items())[:15]:
        f = grp[0]
        title = sports_map.get(f["sport"], f["sport"])
        c_str = fmt_kyiv(f["c_time"])
        top_pick = format_pick(f["market"], f["outcome"], f["point"], f["match"])

        plain_drops, html_drops = [], []
        for al in grp[:4]:
            lbl = format_pick(al["market"], al["outcome"], al["point"], f["match"])
            plain_drops.append(f"- {lbl} ({al['bm']}): {al['start_k']} -> {al['curr_k']} ({al['drop']}%)")
            html_drops.append(f"📉 <b>{esc(lbl)}</b> | БК: <code>{esc(al['bm'])}</code>\n   <code>{al['start_k']:.3f}</code> ({fmt_kyiv(al['s_time'])}) ➔ <b><code>{al['curr_k']:.3f}</code></b> (<b>{al['drop']}%</b>)")

        cap = f"⚽ <b>{esc(f['match'])}</b>\n🏆 <i>{esc(title)}</i>\n🗓 Початок: <code>{c_str}</code>\n🎯 Головний сигнал: <b>{esc(top_pick)}</b>\n\n" + "\n".join(html_drops)
        buf = build_chart(cur, conn, ev_id, f["bm"], f["outcome"], f["point"], f["match"], title, top_pick, sc)
        send_photo(buf, cap) if buf else send_tg(cap)

        ai_verdict = None
        try:
            q_ai = f"SELECT {ai_txt} FROM ai_match_analysis WHERE event_id=%s" + (f" AND {ai_tm} > NOW() - INTERVAL '12 hours';" if ai_tm else ";")
            cur.execute(q_ai, (ev_id,))
            row_ai = cur.fetchone()
            if row_ai and row_ai[0]:
                ai_verdict = row_ai[0]
        except Exception:
            conn.rollback()

        if not ai_verdict:
            ai_verdict = analyze_gemini(f["match"], title, c_str, "\n".join(plain_drops))
            if ai_verdict:
                try:
                    cur.execute(f"INSERT INTO ai_match_analysis (event_id, {ai_txt}) VALUES (%s, %s) ON CONFLICT (event_id) DO UPDATE SET {ai_txt}=EXCLUDED.{ai_txt};", (ev_id, ai_verdict))
                    conn.commit()
                except Exception:
                    conn.rollback()
                time.sleep(2)

        if ai_verdict:
            send_tg(f"🧠 <b>AI-аналіз: {esc(f['match'])}</b>\n\n{ai_verdict}")

        short_pick = extract_short_pick(ai_verdict, top_pick)
        place_paper_bet(cur, conn, ev_id, f["sport"], f["match"], f["c_time"], short_pick, f["curr_k"])

        dt_sort = f["c_time"] if hasattr(f["c_time"], "tzinfo") and f["c_time"].tzinfo else (f["c_time"].replace(tzinfo=timezone.utc) if hasattr(f["c_time"], "replace") else datetime.now(timezone.utc))
        summary_rows.append({"dt": dt_sort, "time": c_str, "match": f["match"], "title": title, "pick": short_pick, "odds": f"{f['curr_k']:.2f}"})

    print(f"5. Відправка зведення ({len(summary_rows)} подій)...")
    if summary_rows:
        summary_rows.sort(key=lambda x: x["dt"])
        lines = ["📋 <b>ЗВЕДЕННЯ СТАВОК (AI-ВЕРДИКТ)</b>"]
        for i, r in enumerate(summary_rows, 1):
            lines.append(f"<b>{i}. {esc(r['match'])}</b>\n   🕒 <code>{esc(r['time'])}</code> | <i>{esc(r['title'])}</i>\n   🎯 <b>{esc(r['pick'])}</b> — Коеф: <code>{r['odds']}</code>")
        send_tg("\n\n".join(lines))

    # 6. Динамічний розклад контрольних точок (SPEC-08)
    try:
        from scheduler import run_schedule_update
        sched_msg = run_schedule_update(cur, conn)
        if sched_msg:
            send_tg(sched_msg)
    except Exception as e:
        print(f"Помилка динамічного розкладу: {e}")

    # 7. Запис пульсу сервісу (SPEC-09)
    try:
        from sys_watchdog import record_heartbeat, ping_external_watchdog
        elapsed = round(time.time() - (t_start or time.time()), 2)
        record_heartbeat(cur, conn, duration_sec=elapsed, status="OK", metadata={"events_checked": len(summary_rows)})
        ping_external_watchdog()
    except Exception as e:
        print(f"Watchdog record err: {e}")

    cur.close()
    conn.close()

if __name__ == "__main__":
    t_start = time.time()
    s_map = get_sports_map()
    fetch_and_save_odds(s_map)
    check_alerts_and_notify(s_map, t_start=t_start)
