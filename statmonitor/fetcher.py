import requests
from datetime import datetime, timezone, timedelta
from psycopg2.extras import execute_values

from statmonitor.config import (
    API_KEY,
    API_KEY_RESERVE,
    API_KEY_RESERVE1,
    API_KEY_RESERVE2,
    API_KEY_RESERVE3,
    ALL_ODDS_API_KEYS,
    SPORTS_MAP,
    TARGET_SPORTS,
)
from statmonitor.database import get_db, get_cols, pick, ensure_tables

def check_odds_api_quota(
    api_key=None,
    api_key_reserve=None,
    api_key_reserve1=None,
    api_key_reserve2=None,
    api_key_reserve3=None,
):
    """
    Отримує баланс квоти The Odds API (залишок та використано) для основного та всіх резервних ключів (до 5 ключів).
    Запит на endpoint /v4/sports/ не споживає квоту (cost = 0).
    """
    key_primary = api_key if api_key is not None else API_KEY
    key_reserve = api_key_reserve if api_key_reserve is not None else API_KEY_RESERVE
    key_reserve1 = api_key_reserve1 if api_key_reserve1 is not None else API_KEY_RESERVE1
    key_reserve2 = api_key_reserve2 if api_key_reserve2 is not None else API_KEY_RESERVE2
    key_reserve3 = api_key_reserve3 if api_key_reserve3 is not None else API_KEY_RESERVE3

    result = {
        "primary": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve1": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve2": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve3": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "total_remaining": 0,
        "total_limit": 2500,
        "active_key": "none",
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    def _mask_key(k):
        if not k or len(k) < 6:
            return "***"
        return f"{k[:3]}...{k[-3:]}"

    total_rem = 0
    total_lim = 0

    def _check_key(k, slot_name, is_primary=False):
        nonlocal total_rem, total_lim
        if not k:
            result[slot_name]["status"] = "not_configured"
            return
        result[slot_name]["key_masked"] = _mask_key(k)
        try:
            r = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": k}, timeout=8)
            if r.status_code == 200:
                rem = r.headers.get("x-requests-remaining")
                used = r.headers.get("x-requests-used")
                rem_val = int(float(rem)) if rem is not None and str(rem).replace(".", "").isdigit() else None
                used_val = int(float(used)) if used is not None and str(used).replace(".", "").isdigit() else None
                result[slot_name]["remaining"] = rem_val
                result[slot_name]["used"] = used_val
                if rem_val is not None:
                    limit_calc = (rem_val + used_val) if used_val is not None else 500
                    result[slot_name]["limit"] = max(500, limit_calc)
                    result[slot_name]["status"] = "active" if (is_primary and rem_val > 5) else ("active" if rem_val > 5 else "exhausted")
                    total_rem += rem_val
                    total_lim += result[slot_name]["limit"]
            elif r.status_code in (401, 402, 429):
                result[slot_name]["status"] = "exhausted" if r.status_code in (402, 429) else "invalid_key"
                result[slot_name]["remaining"] = 0
            else:
                result[slot_name]["status"] = f"http_{r.status_code}"
        except Exception as e:
            result[slot_name]["status"] = f"error: {str(e)[:30]}"

    # Перевіряємо всі 5 ключів
    _check_key(key_primary, "primary", is_primary=True)
    _check_key(key_reserve, "reserve", is_primary=False)
    _check_key(key_reserve1, "reserve1", is_primary=False)
    _check_key(key_reserve2, "reserve2", is_primary=False)
    _check_key(key_reserve3, "reserve3", is_primary=False)

    slot_keys = ["primary", "reserve", "reserve1", "reserve2", "reserve3"]

    # Статуси черги резервів (standby, якщо попередній ключ ще має ресурси)
    seen_active = False
    for slot in slot_keys:
        if seen_active:
            if result[slot]["status"] == "active":
                result[slot]["status"] = "standby"
        else:
            if result[slot]["status"] == "active":
                seen_active = True

    result["total_remaining"] = total_rem
    result["total_limit"] = total_lim if total_lim > 0 else 2500

    # Визначаємо активний ключ
    active_k = "none"
    for slot in slot_keys:
        if result[slot]["status"] == "active":
            active_k = slot
            break
        elif (result[slot]["remaining"] or 0) > 5 and result[slot]["status"] in ("active", "standby"):
            active_k = slot
            break
    result["active_key"] = active_k

    return result

def get_sports_map():
    for k in [x for x in (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3) if x]:
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
    polled_sports_success = []
    keys_pool = [k for k in (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3) if k]
    cur_key_idx = 0
    cur_key = keys_pool[0] if keys_pool else None
    rem_credits = "?"

    for sp in selected_sports:
        if not cur_key:
            break
        try:
            from statmonitor.league_config import get_league_thresholds
            league_thresh = get_league_thresholds(sp)
            mkt_list = league_thresh.get("markets", ["h2h", "totals", "spreads"])
        except Exception:
            mkt_list = ["h2h", "totals", "spreads"]
        
        # The Odds API bulk /odds endpoint accepts only featured markets: h2h, totals, spreads, outrights
        # Non-featured markets like 'btts' cause HTTP 422 error on bulk /odds endpoint
        valid_bulk_markets = ("h2h", "totals", "spreads", "outrights")
        bulk_mkt_list = [m for m in mkt_list if m in valid_bulk_markets]
        if not bulk_mkt_list:
            bulk_mkt_list = ["h2h", "totals", "spreads"]
        mkt_str = ",".join(bulk_mkt_list)

        url = f"https://api.the-odds-api.com/v4/sports/{sp}/odds/"
        params = {"apiKey": cur_key, "regions": "eu", "markets": mkt_str, "commenceTimeTo": to_str}
        try:
            r = requests.get(url, params=params, timeout=12)
            rem_credits = r.headers.get("x-requests-remaining", rem_credits)
            rem_int = int(float(rem_credits)) if str(rem_credits).replace(".", "").isdigit() else 999
            
            # Якщо ключ вичерпано або статус помилки — ротація на наступний ключ (RESERVE -> RESERVE1)
            while (r.status_code in (401, 402, 429) or rem_int <= 1) and (cur_key_idx + 1 < len(keys_pool)):
                cur_key_idx += 1
                cur_key = keys_pool[cur_key_idx]
                params["apiKey"] = cur_key
                print(f"🔄 Ротація The Odds API: перемикання на резервний ключ #{cur_key_idx}...")
                r = requests.get(url, params=params, timeout=12)
                rem_credits = r.headers.get("x-requests-remaining", rem_credits)
                rem_int = int(float(rem_credits)) if str(rem_credits).replace(".", "").isdigit() else 999

            if r.status_code != 200:
                err_msg = f"The Odds API повернув помилку для {sp} [HTTP {r.status_code}]: {r.text[:150]}"
                print(f"⚠️ {err_msg}")
                if conn and cur:
                    try:
                        from statmonitor.database import log_system_error
                        log_system_error(cur, "odds_api", err_msg, severity="ERROR", error_code=f"HTTP_{r.status_code}", details={"sport": sp, "status": r.status_code, "text": r.text[:200]})
                    except Exception:
                        pass
                continue
            polled_sports_success.append(sp)
            for ev in r.json():
                events_batch.append((ev["id"], sp, ev.get("home_team", ""), ev.get("away_team", ""), ev["commence_time"]))
                for bm in ev.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        mkt_key = mkt.get("key", "")
                        for out in mkt.get("outcomes", []):
                            if out.get("price") is not None:
                                pt_val = out.get("point")
                                # SPEC-23: Clean Totals Filtering (відсікання азіатських четвертних тоталів .25 / .75)
                                if mkt_key == "totals" and pt_val is not None:
                                    try:
                                        if round(abs(float(pt_val) * 100)) % 50 != 0:
                                            continue
                                    except (ValueError, TypeError):
                                        pass
                                odds_raw.append({
                                    "event_id": ev["id"], "bookmaker": bm["key"], "market": mkt_key,
                                    "outcome": out.get("name", ""), "point": pt_val,
                                    "price": out["price"], "time": now_utc
                                })
        except Exception as e:
            err_msg = f"Помилка запиту котирувань для {sp}: {e}"
            print(f"API err {sp}: {e}")
            if conn and cur:
                try:
                    from statmonitor.database import log_system_error
                    log_system_error(cur, "odds_api", err_msg, severity="ERROR", error_code="FETCH_ERROR", details={"sport": sp, "error": str(e)})
                except Exception:
                    pass

    print(f"2. Залишок кредитів: {rem_credits}")
    if not conn or not cur:
        print("Помилка підключення до БД для збереження котирувань.")
        return len(events_batch), len(odds_raw), rem_credits

    # Фіксуємо успішне опитування ліг у rate limiter
    try:
        from statmonitor.limiter import record_poll_success
        record_poll_success(cur, conn, polled_sports_success, tiers=tiers, now_utc=now_utc)
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

    # SPEC-39: Холодний архів Parquet (Cloudflare R2 / S3) перед 4-денною ротацією
    if time_col:
        try:
            from statmonitor.cold_archive import archive_cold_odds
            res_arch = archive_cold_odds(cur, conn, min_age_days=3.5)
            if res_arch.get("files_created", 0) > 0:
                print(f"📦 [Cold Archive] Збережено {res_arch['total_records']} котирувань у {res_arch['files_created']} Parquet-файлів перед ротацією.")
        except Exception as arch_err:
            print(f"⚠️ [Cold Archive] Помилка архівації перед ротацією: {arch_err}")

        cur.execute(f"DELETE FROM odds_history WHERE {time_col} < NOW() - INTERVAL '4 days';")
    cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '4 days';")
    conn.commit()
    cur.close()
    conn.close()
    print(f"3. Збережено подій: {len(events_batch)}, котирувань: {len(odds_raw)}")
    return len(events_batch), len(odds_raw), rem_credits
