import requests
from datetime import datetime, timezone, timedelta
from psycopg2.extras import execute_values

from statmonitor.config import API_KEY, API_KEY_RESERVE, SPORTS_MAP, TARGET_SPORTS
from statmonitor.database import get_db, get_cols, pick, ensure_tables

def check_odds_api_quota(api_key=None, api_key_reserve=None):
    """
    Отримує баланс квоти The Odds API (залишок та використано) для основного та резервного ключів.
    Запит на endpoint /v4/sports/ не споживає квоту (cost = 0).
    """
    key_primary = api_key if api_key is not None else API_KEY
    key_reserve = api_key_reserve if api_key_reserve is not None else API_KEY_RESERVE

    result = {
        "primary": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "total_remaining": 0,
        "total_limit": 1000,
        "active_key": "none",
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    def _mask_key(k):
        if not k or len(k) < 6:
            return "***"
        return f"{k[:3]}...{k[-3:]}"

    total_rem = 0
    total_lim = 0

    # 1. Перевірка основного ключа
    if key_primary:
        result["primary"]["key_masked"] = _mask_key(key_primary)
        try:
            r1 = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": key_primary}, timeout=8)
            if r1.status_code == 200:
                rem1 = r1.headers.get("x-requests-remaining")
                used1 = r1.headers.get("x-requests-used")
                rem_val = int(float(rem1)) if rem1 is not None and str(rem1).replace(".", "").isdigit() else None
                used_val = int(float(used1)) if used1 is not None and str(used1).replace(".", "").isdigit() else None
                result["primary"]["remaining"] = rem_val
                result["primary"]["used"] = used_val
                if rem_val is not None:
                    limit_calc = (rem_val + used_val) if used_val is not None else 500
                    result["primary"]["limit"] = max(500, limit_calc)
                    result["primary"]["status"] = "active" if rem_val > 5 else "exhausted"
                    total_rem += rem_val
                    total_lim += result["primary"]["limit"]
            elif r1.status_code in (401, 402, 429):
                result["primary"]["status"] = "exhausted" if r1.status_code in (402, 429) else "invalid_key"
                result["primary"]["remaining"] = 0
            else:
                result["primary"]["status"] = f"http_{r1.status_code}"
        except Exception as e:
            result["primary"]["status"] = f"error: {str(e)[:30]}"
    else:
        result["primary"]["status"] = "not_configured"

    # 2. Перевірка резервного ключа
    if key_reserve:
        result["reserve"]["key_masked"] = _mask_key(key_reserve)
        try:
            r2 = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": key_reserve}, timeout=8)
            if r2.status_code == 200:
                rem2 = r2.headers.get("x-requests-remaining")
                used2 = r2.headers.get("x-requests-used")
                rem_val = int(float(rem2)) if rem2 is not None and str(rem2).replace(".", "").isdigit() else None
                used_val = int(float(used2)) if used2 is not None and str(used2).replace(".", "").isdigit() else None
                result["reserve"]["remaining"] = rem_val
                result["reserve"]["used"] = used_val
                if rem_val is not None:
                    limit_calc = (rem_val + used_val) if used_val is not None else 500
                    result["reserve"]["limit"] = max(500, limit_calc)
                    result["reserve"]["status"] = "standby" if (result["primary"]["status"] == "active") else ("active" if rem_val > 5 else "exhausted")
                    total_rem += rem_val
                    total_lim += result["reserve"]["limit"]
            elif r2.status_code in (401, 402, 429):
                result["reserve"]["status"] = "exhausted" if r2.status_code in (402, 429) else "invalid_key"
                result["reserve"]["remaining"] = 0
            else:
                result["reserve"]["status"] = f"http_{r2.status_code}"
        except Exception as e:
            result["reserve"]["status"] = f"error: {str(e)[:30]}"
    else:
        result["reserve"]["status"] = "not_configured"

    result["total_remaining"] = total_rem
    result["total_limit"] = total_lim if total_lim > 0 else 1000

    # Визначаємо активний ключ
    if result["primary"]["status"] == "active":
        result["active_key"] = "primary"
    elif result["reserve"]["status"] in ("active", "standby") and (result["reserve"]["remaining"] or 0) > 0:
        result["active_key"] = "reserve"
    else:
        result["active_key"] = "none"

    return result

def get_sports_map():
    for k in [x for x in (API_KEY, API_KEY_RESERVE) if x]:
        try:
            r = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": k}, timeout=12)
            if r.status_code == 200:
                data = r.json()
                res = {}
                for s in data:
                    s_key = s.get("key", "")
                    is_active = s.get("active", False)
                    # Відбираємо ліги з TARGET_SPORTS або будь-який активний тенісний турнір
                    if is_active and (s_key in TARGET_SPORTS or s.get("group") == "Tennis" or s_key.startswith("tennis_")):
                        title = s.get("title")
                        if not title:
                            title = f"Теніс ({s_key.replace('tennis_', '').upper()})" if s_key.startswith("tennis_") else s_key
                        elif s_key.startswith("tennis_") and not title.lower().startswith("теніс") and not title.lower().startswith("tennis"):
                            title = f"Теніс ({title})"
                        res[s_key] = title
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
        if "home_team" in ev_cols and "match_name" in ev_cols:
            execute_values(cur, f"INSERT INTO events ({id_c}, sport, home_team, away_team, match_name, commence_time) VALUES %s ON CONFLICT ({id_c}) DO UPDATE SET commence_time=EXCLUDED.commence_time, match_name=EXCLUDED.match_name;", [(e[0], e[1], e[2], e[3], f"{e[2]} - {e[3]}", e[4]) for e in events_batch])
        elif "home_team" in ev_cols:
            execute_values(cur, f"INSERT INTO events ({id_c}, sport, home_team, away_team, commence_time) VALUES %s ON CONFLICT ({id_c}) DO UPDATE SET commence_time=EXCLUDED.commence_time;", events_batch)
        elif "match_name" in ev_cols:
            execute_values(cur, f"INSERT INTO events ({id_c}, sport, match_name, commence_time) VALUES %s ON CONFLICT ({id_c}) DO UPDATE SET commence_time=EXCLUDED.commence_time;", [(e[0], e[1], f"{e[2]} - {e[3]}", e[4]) for e in events_batch])

    oh_cols = get_cols(cur, "odds_history")
    col_map = []
    if "event_id" in oh_cols: col_map.append(("event_id", "event_id"))
    elif "match_id" in oh_cols: col_map.append(("match_id", "event_id"))

    if "bookmaker" in oh_cols: col_map.append(("bookmaker", "bookmaker"))
    elif "bm" in oh_cols: col_map.append(("bm", "bookmaker"))

    if "market_key" in oh_cols: col_map.append(("market_key", "market"))
    elif "market" in oh_cols: col_map.append(("market", "market"))

    # Підтримуємо обидві назви (outcome_name та legacy outcome)
    if "outcome_name" in oh_cols: col_map.append(("outcome_name", "outcome"))
    if "outcome" in oh_cols: col_map.append(("outcome", "outcome"))

    if "point" in oh_cols: col_map.append(("point", "point"))
    elif "handicap" in oh_cols: col_map.append(("handicap", "point"))

    # Підтримуємо обидві назви (price та legacy odds_value)
    if "price" in oh_cols: col_map.append(("price", "price"))
    if "odds_value" in oh_cols: col_map.append(("odds_value", "price"))
    elif "odds" in oh_cols: col_map.append(("odds", "price"))

    time_col = None
    if "recorded_at" in oh_cols:
        col_map.append(("recorded_at", "time"))
        time_col = "recorded_at"
    elif "created_at" in oh_cols:
        col_map.append(("created_at", "time"))
        time_col = "created_at"

    if odds_raw and col_map:
        cols_sql = ", ".join(c[0] for c in col_map)
        execute_values(cur, f"INSERT INTO odds_history ({cols_sql}) VALUES %s;", [tuple(x[c[1]] for c in col_map) for x in odds_raw])

    if time_col:
        cur.execute(f"DELETE FROM odds_history WHERE {time_col} < NOW() - INTERVAL '4 days';")
    cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '4 days';")
    conn.commit()
    cur.close()
    conn.close()
    print(f"3. Збережено подій: {len(events_batch)}, котирувань: {len(odds_raw)}")
    return len(events_batch), len(odds_raw), rem_credits
