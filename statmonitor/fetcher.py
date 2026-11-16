import requests
from datetime import datetime, timezone, timedelta
from psycopg2.extras import execute_values

from statmonitor.config import API_KEY, API_KEY_RESERVE, SPORTS_MAP, TARGET_SPORTS
from statmonitor.database import get_db, get_cols, pick, ensure_tables

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

def fetch_and_save_odds(sports_map=None):
    if sports_map is None:
        sports_map = SPORTS_MAP

    now_utc = datetime.now(timezone.utc)
    to_str = (now_utc + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_db()
    cur = conn.cursor() if conn else None
    if conn and cur:
        ensure_tables(cur, conn)

    # 1. Smart Rate-Limiter (SPEC-10)
    selected_sports = sports_map
    mode = "NORMAL"
    tiers = {}
    if conn and cur:
        try:
            from statmonitor.limiter import filter_sports_to_poll, record_poll_success
            selected_sports, mode, tiers = filter_sports_to_poll(cur, conn, sports_map, now_utc=now_utc)
            print(f"1. Smart Rate-Limiter [{mode}]: до опитування відібрано {len(selected_sports)} з {len(sports_map)} ліг: {list(selected_sports.keys())}")
        except Exception as e:
            print(f"Rate-limiter filter err: {e}")
            selected_sports = sports_map
    else:
        print(f"1. Турніри ({len(sports_map)}): {list(sports_map.keys())}")

    if not selected_sports:
        print("1. Smart Rate-Limiter: всі ліги нещодавно опитані, пропускаємо запити до API для економії квоти.")
        if cur: cur.close()
        if conn: conn.close()
        return 0, 0, "cached"

    events_batch, odds_raw = [], []
    rem_credits, cur_key, using_res = "?", (API_KEY or API_KEY_RESERVE), (not API_KEY and bool(API_KEY_RESERVE))

    for sp in selected_sports:
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
    if not conn or not cur:
        print("Помилка підключення до БД для збереження котирувань.")
        return len(events_batch), len(odds_raw), rem_credits

    # Фіксуємо успішне опитування ліг у rate limiter
    try:
        from statmonitor.limiter import record_poll_success
        record_poll_success(cur, conn, list(selected_sports.keys()), tiers=tiers, now_utc=now_utc)
    except Exception as e:
        print(f"Rate-limiter record err: {e}")
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
    return len(events_batch), len(odds_raw), rem_credits
