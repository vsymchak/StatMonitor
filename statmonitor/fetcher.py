import requests
from datetime import datetime, timezone, timedelta
from psycopg2.extras import execute_values

from statmonitor.config import (
    PROPLINE_API_KEY,
    PROPLINE_BASE_URL,
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


def _extract_api_items(payload):
    """Нормалізує JSON-відповідь (список або словник із ключами data/events/sports)."""
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for k in ("data", "events", "sports", "items"):
            val = payload.get(k)
            if isinstance(val, list):
                return val
    return []


def _parse_header_int(headers, candidate_keys):
    """Повертає ціле значення з першого наявного заголовка квоти або None."""
    if not headers:
        return None
    lower_hdrs = {str(k).lower(): v for k, v in headers.items()}
    for hk in candidate_keys:
        raw = lower_hdrs.get(hk.lower())
        if raw is not None:
            try:
                return int(float(str(raw).strip()))
            except (ValueError, TypeError):
                pass
    return None


def _mask_key(k):
    if not k or len(k) < 6:
        return "***"
    return f"{k[:3]}...{k[-3:]}"


def check_odds_api_quota(
    api_key=None,
    api_key_reserve=None,
    api_key_reserve1=None,
    api_key_reserve2=None,
    api_key_reserve3=None,
    propline_api_key=None,
):
    """
    Отримує баланс квоти PropLine API (пріоритетний) та The Odds API (основний + до 4 резервних ключів).
    """
    key_propline = propline_api_key if propline_api_key is not None else PROPLINE_API_KEY
    key_primary = api_key if api_key is not None else API_KEY
    key_reserve = api_key_reserve if api_key_reserve is not None else API_KEY_RESERVE
    key_reserve1 = api_key_reserve1 if api_key_reserve1 is not None else API_KEY_RESERVE1
    key_reserve2 = api_key_reserve2 if api_key_reserve2 is not None else API_KEY_RESERVE2
    key_reserve3 = api_key_reserve3 if api_key_reserve3 is not None else API_KEY_RESERVE3

    result = {
        "propline": {"key_masked": None, "remaining": None, "used": None, "limit": 1000, "status": "not_configured"},
        "primary": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve1": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve2": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "reserve3": {"key_masked": None, "remaining": None, "used": None, "limit": 500, "status": "not_configured"},
        "total_remaining": 0,
        "total_limit": 2500,
        "active_key": "none",
        "preferred_source": "the_odds_api",
        "last_checked": datetime.now(timezone.utc).isoformat(),
    }

    if key_propline:
        result["propline"]["key_masked"] = _mask_key(key_propline)
        try:
            r_pl = requests.get(
                f"{PROPLINE_BASE_URL}/sports",
                headers={"X-API-Key": key_propline},
                timeout=8,
            )
            if r_pl.status_code == 200:
                lim_pl = _parse_header_int(r_pl.headers, ("x-ratelimit-limit", "ratelimit-limit", "x-daily-limit")) or 1000
                rem_pl = _parse_header_int(r_pl.headers, ("x-ratelimit-remaining", "ratelimit-remaining", "x-daily-remaining", "x-requests-remaining"))
                used_pl = (lim_pl - rem_pl) if (rem_pl is not None and lim_pl >= rem_pl) else None
                result["propline"]["limit"] = lim_pl
                result["propline"]["remaining"] = rem_pl
                result["propline"]["used"] = used_pl
                result["propline"]["status"] = "active" if (rem_pl is None or rem_pl > 1) else "exhausted"
            elif r_pl.status_code in (402, 429):
                result["propline"]["status"] = "exhausted"
                result["propline"]["remaining"] = 0
            elif r_pl.status_code in (401, 403):
                result["propline"]["status"] = "invalid_key"
                result["propline"]["remaining"] = 0
            else:
                result["propline"]["status"] = f"http_{r_pl.status_code}"
        except Exception as e:
            result["propline"]["status"] = f"error: {str(e)[:30]}"

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

    # Перевіряємо всі 5 ключів The Odds API
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

    # Визначаємо активний ключ The Odds API
    active_k = "none"
    for slot in slot_keys:
        if result[slot]["status"] == "active":
            active_k = slot
            break
        elif (result[slot]["remaining"] or 0) > 5 and result[slot]["status"] in ("active", "standby"):
            active_k = slot
            break
    result["active_key"] = active_k
    result["preferred_source"] = "propline" if result["propline"]["status"] == "active" else "the_odds_api"

    return result


# Співставлення канонічних ключів The Odds API <-> ключів PropLine API
ODDS_TO_PROPLINE_ALIASES = {
    "soccer_uefa_champs_league": ("soccer_uefa_champions_league", "soccer_uefa_champs_league"),
    "soccer_uefa_europa_conference_league": ("soccer_uefa_conference_league", "soccer_uefa_europa_conference_league"),
    "soccer_usa_mls": ("soccer_usa_mls", "soccer_mls"),
    "icehockey_nhl": ("icehockey_nhl", "hockey_nhl"),
    "americanfootball_nfl": ("americanfootball_nfl", "football_nfl"),
    "tennis_atp": ("tennis", "tennis_atp"),
    "tennis_wta": ("tennis", "tennis_wta"),
    "tennis_davis_cup": ("tennis", "tennis_davis_cup"),
}

PROPLINE_TO_ODDS_CANONICAL = {
    "soccer_uefa_champions_league": "soccer_uefa_champs_league",
    "hockey_nhl": "icehockey_nhl",
    "football_nfl": "americanfootball_nfl",
    "soccer_mls": "soccer_usa_mls",
}


def get_propline_candidate_keys(canonical_key):
    """Повертає кортеж можливих ключів PropLine API для канонічного ключа The Odds API."""
    if canonical_key in ODDS_TO_PROPLINE_ALIASES:
        return ODDS_TO_PROPLINE_ALIASES[canonical_key]
    if str(canonical_key).startswith("tennis_"):
        return (canonical_key, "tennis")
    return (canonical_key,)


def resolve_propline_sport_key(canonical_key, propline_live_keys=None):
    """Обирає найкращий ключ PropLine для канонічного ключа ліги."""
    candidates = get_propline_candidate_keys(canonical_key)
    if propline_live_keys:
        for cand in candidates:
            if cand in propline_live_keys:
                return cand
    return candidates[0]


def get_common_supported_sports(propline_api_key=None, odds_api_keys=None):
    """
    Визначає перетин (спільні ліги) між PropLine API (/v1/sports) та The Odds API (/v4/sports/)
    із урахуванням співставлення ключів (наприклад soccer_uefa_champs_league <-> soccer_uefa_champions_league).
    """
    pl_key = propline_api_key if propline_api_key is not None else PROPLINE_API_KEY
    odds_pool = [k for k in (odds_api_keys or (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3)) if k]

    pl_live_keys = set()
    pl_ok = False
    if pl_key:
        try:
            r_pl = requests.get(f"{PROPLINE_BASE_URL}/sports", headers={"X-API-Key": pl_key}, timeout=12)
            if r_pl.status_code == 200:
                for item in _extract_api_items(r_pl.json()):
                    if isinstance(item, dict) and item.get("active", True):
                        sk = item.get("key") or item.get("sport_key")
                        if sk:
                            pl_live_keys.add(str(sk))
                pl_ok = len(pl_live_keys) > 0
        except Exception:
            pass

    odds_live_keys = set()
    odds_ok = False
    for k in odds_pool:
        try:
            r = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": k}, timeout=12)
            if r.status_code == 200:
                for item in _extract_api_items(r.json()):
                    if isinstance(item, dict) and item.get("active", True):
                        sk = item.get("key") or item.get("sport_key")
                        if sk:
                            odds_live_keys.add(str(sk))
                odds_ok = len(odds_live_keys) > 0
                if odds_ok:
                    break
        except Exception:
            pass

    from statmonitor.league_config import load_leagues_config
    all_cfg_keys = [lg["key"] for lg in load_leagues_config().get("leagues", []) if lg.get("key")]

    common_keys = set()
    mapping = {}
    for ck in all_cfg_keys:
        cands = get_propline_candidate_keys(ck)
        in_pl = any(c in pl_live_keys for c in cands) if pl_ok else any(c in ODDS_TO_PROPLINE_ALIASES or True for c in cands)
        in_odds = (ck in odds_live_keys) if odds_ok else True
        if pl_ok and odds_ok:
            if in_pl and in_odds:
                common_keys.add(ck)
                mapping[ck] = resolve_propline_sport_key(ck, pl_live_keys)
        elif pl_ok:
            if in_pl:
                common_keys.add(ck)
                mapping[ck] = resolve_propline_sport_key(ck, pl_live_keys)
        elif odds_ok:
            if in_odds:
                common_keys.add(ck)
                mapping[ck] = resolve_propline_sport_key(ck)

    return {
        "common_keys": common_keys,
        "propline_keys": pl_live_keys,
        "odds_keys": odds_live_keys,
        "mapping": mapping,
        "propline_ok": pl_ok,
        "odds_ok": odds_ok,
    }


def _parse_sports_list(data, map_propline=False, active_targets=None):
    if active_targets is None:
        try:
            from statmonitor.league_config import load_leagues_config, get_active_target_sports
            dyn_targets = set(get_active_target_sports(load_leagues_config()))
            active_targets = dyn_targets if dyn_targets else set(TARGET_SPORTS)
        except Exception:
            active_targets = set(TARGET_SPORTS)
    res = {}
    for s in _extract_api_items(data):
        if not isinstance(s, dict):
            continue
        raw_key = s.get("key") or s.get("sport_key") or ""
        s_key = PROPLINE_TO_ODDS_CANONICAL.get(raw_key, raw_key) if map_propline else raw_key
        is_active = s.get("active", True)
        grp_lower = str(s.get("group") or "").lower()
        is_tennis = (
            s_key == "tennis"
            or s_key.startswith("tennis_")
            or grp_lower == "tennis"
            or "davis" in s_key
            or "atp" in s_key
            or "wta" in s_key
        )
        if is_active and (s_key in active_targets or s_key in TARGET_SPORTS or is_tennis):
            title = s.get("title")
            if not title:
                title = f"Теніс ({s_key.replace('tennis_', '').upper()})" if s_key.startswith("tennis_") else s_key
            elif is_tennis and not title.lower().startswith("теніс") and not title.lower().startswith("tennis"):
                title = f"Теніс ({title})"
            res[s_key] = title
    return res


def get_sports_map():
    res_pl = {}
    # 1. Пріоритет: PropLine API (зі співставленням ключів до канонічних The Odds API)
    if PROPLINE_API_KEY:
        try:
            r_pl = requests.get(
                f"{PROPLINE_BASE_URL}/sports",
                headers={"X-API-Key": PROPLINE_API_KEY},
                timeout=12,
            )
            if r_pl.status_code == 200:
                res_pl = _parse_sports_list(r_pl.json(), map_propline=True)
        except Exception:
            pass

    # 2. Доповнення/Fallback: The Odds API /v4/sports/ (0 витрат квоти), щоб не втратити ЛЧ, топ-ліги Європи та теніс
    res_odds = {}
    for k in [x for x in (API_KEY, API_KEY_RESERVE, API_KEY_RESERVE1, API_KEY_RESERVE2, API_KEY_RESERVE3) if x]:
        try:
            r = requests.get("https://api.the-odds-api.com/v4/sports/", params={"apiKey": k}, timeout=12)
            if r.status_code == 200:
                res_odds = _parse_sports_list(r.json(), map_propline=False)
                if res_odds:
                    break
        except Exception:
            pass

    merged = {**res_odds, **res_pl}
    if merged:
        return merged
    return dict(SPORTS_MAP) if SPORTS_MAP else {k: k for k in TARGET_SPORTS}


def _append_events_and_odds(events_list, sp, now_utc, events_batch, odds_raw, max_commence_utc=None):
    """Парсить події та коефіцієнти у спільному форматі PropLine / The Odds API."""
    for ev in events_list:
        if not isinstance(ev, dict):
            continue
        ev_id = ev.get("id") or ev.get("event_id")
        commence_time = ev.get("commence_time")
        if not ev_id or not commence_time:
            continue
        if max_commence_utc is not None:
            try:
                ev_dt = datetime.fromisoformat(str(commence_time).replace("Z", "+00:00"))
                if ev_dt.tzinfo is None:
                    ev_dt = ev_dt.replace(tzinfo=timezone.utc)
                if ev_dt > max_commence_utc:
                    continue
            except Exception:
                pass
        events_batch.append((ev_id, sp, ev.get("home_team", ""), ev.get("away_team", ""), commence_time))
        dedup_map = {}
        for bm in ev.get("bookmakers", []):
            bm_key = bm.get("key") or bm.get("title") or "unknown"
            for mkt in bm.get("markets", []):
                mkt_key = mkt.get("key", "")
                mkt_meta = " ".join(
                    str(mkt.get(k) or "") for k in ("description", "label", "period", "name")
                ).lower()
                if any(w in mkt_meta for w in ("team", "half", "quarter", "period", "1h", "2h")):
                    continue
                for out in mkt.get("outcomes", []):
                    out_desc = str(out.get("description") or "").lower()
                    if any(w in out_desc for w in ("team", "half", "quarter", "period", "1h", "2h")):
                        continue
                    raw_price = out.get("price")
                    if raw_price is not None:
                        try:
                            price_val = float(raw_price)
                        except (ValueError, TypeError):
                            continue
                        # Конвертація випадкових американських коефіцієнтів (-110 -> 1.909, +120 -> 2.20)
                        if price_val < 0:
                            price_val = 1.0 + (100.0 / abs(price_val))
                        elif 100.0 <= price_val < 1000.0:
                            price_val = 1.0 + (price_val / 100.0)
                        # Захист від overflow у PostgreSQL NUMERIC(6,3) (< 1000.0) та некоректних викидів
                        if price_val <= 1.0 or price_val >= 50.0:
                            continue
                        price_val = round(price_val, 3)

                        pt_val = out.get("point")
                        if pt_val is not None:
                            try:
                                pt_f = float(pt_val)
                                if abs(pt_f) >= 1000.0:
                                    continue
                                # SPEC-23: Clean Totals Filtering (відсікання азіатських четвертних тоталів .25 / .75)
                                if mkt_key == "totals" and round(abs(pt_f * 100)) % 50 != 0:
                                    continue
                                # Хокей (NHL тощо): відсікаємо командні/періодні тотали < 4.0 (0.5..3.5, включно з 2.5)
                                if str(sp or "").lower().startswith("icehockey") and mkt_key == "totals" and pt_f < 4.0:
                                    continue
                                # Баскетбол (NBA тощо): відсікаємо командні/половинові тотали < 150.0
                                if str(sp or "").lower().startswith("basketball") and mkt_key == "totals" and pt_f < 150.0:
                                    continue
                                pt_val = round(pt_f, 2)
                            except (ValueError, TypeError):
                                pt_val = None
                        out_name = out.get("name", "")
                        dedup_key = (ev_id, bm_key, mkt_key, out_name, pt_val)
                        row_obj = {
                            "event_id": ev_id, "bookmaker": bm_key, "market": mkt_key,
                            "outcome": out_name, "point": pt_val,
                            "price": price_val, "time": now_utc
                        }
                        if dedup_key in dedup_map:
                            if mkt_key == "totals":
                                on_l = out_name.lower()
                                # Для Full-Match totals: Over завжди має MIN ціну, Under — MAX ціну серед однакових тоталів
                                if "over" in on_l and price_val < dedup_map[dedup_key]["price"]:
                                    dedup_map[dedup_key] = row_obj
                                elif "under" in on_l and price_val > dedup_map[dedup_key]["price"]:
                                    dedup_map[dedup_key] = row_obj
                            continue
                        dedup_map[dedup_key] = row_obj
        odds_raw.extend(dedup_map.values())

def fetch_and_save_odds(sports_map=None):
    now_utc = datetime.now(timezone.utc)
    max_commence_utc = now_utc + timedelta(days=5)
    to_str = max_commence_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    conn = get_db()
    cur = conn.cursor() if conn else None
    if conn and cur:
        ensure_tables(cur, conn)
        try:
            from statmonitor.league_config import auto_enable_tennis_tournaments, load_leagues_config, get_active_sports_map
            if sports_map is not None:
                auto_enable_tennis_tournaments(cur, conn, sports_map)
            live_cfg = load_leagues_config(cur=cur)
            if sports_map is None:
                sports_map = get_active_sports_map(config=live_cfg)
            else:
                disabled_keys = {
                    lg.get("key")
                    for lg in live_cfg.get("leagues", [])
                    if lg.get("enabled") is False and lg.get("key")
                }
                if disabled_keys:
                    sports_map = {k: v for k, v in sports_map.items() if k not in disabled_keys}
        except Exception as te:
            print(f"Dynamic league config / tennis auto-enable err: {te}")
            if sports_map is None:
                sports_map = SPORTS_MAP
    elif sports_map is None:
        sports_map = SPORTS_MAP

    # 1. Smart Rate-Limiter (SPEC-10)
    selected_sports = sports_map
    mode = "NORMAL"
    tiers = {}
    if conn and cur:
        try:
            from statmonitor.limiter import filter_sports_to_poll, record_poll_success
            rem_from_hb = None
            try:
                cur.execute(
                    "SELECT metadata->'odds_quota' FROM system_heartbeat WHERE service_name IN ('StatMonitor', 'scheduler_run') ORDER BY last_ping_at DESC LIMIT 1;"
                )
                hb_r = cur.fetchone()
                if hb_r and isinstance(hb_r[0], dict):
                    q_meta = hb_r[0]
                    pref = q_meta.get("preferred_source")
                    if pref == "propline" and isinstance(q_meta.get("propline"), dict) and q_meta["propline"].get("remaining") is not None:
                        rem_from_hb = int(float(q_meta["propline"]["remaining"]))
                    elif q_meta.get("total_remaining") is not None:
                        rem_from_hb = int(float(q_meta["total_remaining"]))
            except Exception:
                pass
            selected_sports, mode, tiers = filter_sports_to_poll(
                cur, conn, sports_map, remaining_credits=rem_from_hb, now_utc=now_utc
            )
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
    propline_key = PROPLINE_API_KEY
    propline_exhausted = not bool(propline_key)
    propline_rem = "?"
    propline_polled = 0
    odds_api_polled = 0
    seen_pl_sports = set()

    for sp in selected_sports:
        try:
            from statmonitor.league_config import get_league_thresholds
            league_thresh = get_league_thresholds(sp)
            mkt_list = league_thresh.get("markets", ["h2h", "totals", "spreads"])
        except Exception:
            mkt_list = ["h2h", "totals", "spreads"]

        valid_bulk_markets = ("h2h", "totals", "spreads", "outrights")
        bulk_mkt_list = [m for m in mkt_list if m in valid_bulk_markets]
        if not bulk_mkt_list:
            bulk_mkt_list = ["h2h", "totals", "spreads"]
        mkt_str = ",".join(bulk_mkt_list)

        # 1. Пріоритетне джерело: PropLine API (з урахуванням аліасів ключів)
        if propline_key and not propline_exhausted:
            pl_sp = resolve_propline_sport_key(sp)
            if pl_sp in seen_pl_sports:
                polled_sports_success.append(sp)
                continue
            pl_url = f"{PROPLINE_BASE_URL}/sports/{pl_sp}/odds"
            pl_params = {"regions": "eu", "markets": mkt_str, "oddsFormat": "decimal", "commenceTimeTo": to_str}
            try:
                r_pl = requests.get(
                    pl_url,
                    headers={"X-API-Key": propline_key},
                    params=pl_params,
                    timeout=12,
                )
                pl_rem_val = _parse_header_int(
                    r_pl.headers,
                    ("x-ratelimit-remaining", "ratelimit-remaining", "x-daily-remaining", "x-requests-remaining"),
                )
                if pl_rem_val is not None:
                    propline_rem = pl_rem_val

                if r_pl.status_code in (400, 422) and str(sp).startswith("tennis") and mkt_str != "h2h":
                    # Деякі провайдери для тенісу підтримують лише h2h без totals/spreads
                    r_pl = requests.get(
                        pl_url,
                        headers={"X-API-Key": propline_key},
                        params={"regions": "eu", "markets": "h2h", "oddsFormat": "decimal", "commenceTimeTo": to_str},
                        timeout=12,
                    )

                if r_pl.status_code == 200:
                    pl_events = _extract_api_items(r_pl.json())
                    if pl_rem_val is not None and pl_rem_val <= 1:
                        propline_exhausted = True
                        print("⚠️ PropLine API: денний ліміт майже вичерпано, перемикання залишку на The Odds API...")
                    is_tennis_sp = str(sp).startswith("tennis")
                    if len(pl_events) == 0 and (tiers.get(sp) in ("HOT", "WARM") or is_tennis_sp) and cur_key:
                        print(f"ℹ️ PropLine API повернув 0 подій для {sp} ({tiers.get(sp)}): fallback на The Odds API...")
                    else:
                        _append_events_and_odds(pl_events, sp, now_utc, events_batch, odds_raw, max_commence_utc=max_commence_utc)
                        seen_pl_sports.add(pl_sp)
                        polled_sports_success.append(sp)
                        propline_polled += 1
                        continue
                elif r_pl.status_code in (401, 402, 429):
                    propline_exhausted = True
                    print(f"⚠️ PropLine API [HTTP {r_pl.status_code}]: перемикання на резерв The Odds API...")
                else:
                    print(f"ℹ️ PropLine API для {sp} [HTTP {r_pl.status_code}]: fallback на The Odds API...")
            except Exception as pl_err:
                print(f"ℹ️ PropLine API err {sp}: {pl_err} (fallback на The Odds API)")

        # 2. Fallback: The Odds API (пул 5 ключів)
        if not cur_key:
            continue

        url = f"https://api.the-odds-api.com/v4/sports/{sp}/odds/"
        params = {"apiKey": cur_key, "regions": "eu", "markets": mkt_str, "oddsFormat": "decimal", "commenceTimeTo": to_str}
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
            odds_api_polled += 1
            _append_events_and_odds(_extract_api_items(r.json()), sp, now_utc, events_batch, odds_raw, max_commence_utc=max_commence_utc)
        except Exception as e:
            err_msg = f"Помилка запиту котирувань для {sp}: {e}"
            print(f"API err {sp}: {e}")
            if conn and cur:
                try:
                    from statmonitor.database import log_system_error
                    log_system_error(cur, "odds_api", err_msg, severity="ERROR", error_code="FETCH_ERROR", details={"sport": sp, "error": str(e)})
                except Exception:
                    pass

    print(f"2. Джерела котирувань: PropLine={propline_polled} ліг (залишок {propline_rem}) | OddsAPI={odds_api_polled} ліг (залишок {rem_credits})")
    rem_summary = f"PropLine:{propline_rem}" if propline_polled > 0 and odds_api_polled == 0 else rem_credits
    if not conn or not cur:
        print("Помилка підключення до БД для збереження котирувань.")
        return len(events_batch), len(odds_raw), rem_summary

    # Фіксуємо успішне опитування ліг у rate limiter
    try:
        from statmonitor.limiter import record_poll_success
        record_poll_success(cur, conn, polled_sports_success, tiers=tiers, now_utc=now_utc)
    except Exception as e:
        print(f"Rate-limiter record err: {e}")
    ensure_tables(cur, conn)

    ev_cols = get_cols(cur, "events")
    if events_batch:
        # Дедуплікація за id, щоб ON CONFLICT DO UPDATE не падав з CardinalityViolation
        events_batch = list({e[0]: e for e in events_batch}.values())
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
        arch_ok = True
        try:
            from statmonitor.cold_archive import archive_cold_odds
            total_arch_rec = 0
            total_arch_files = 0
            for _ in range(5):
                res_arch = archive_cold_odds(cur, conn, min_age_days=3.5, batch_limit=50000)
                if not res_arch.get("success"):
                    arch_ok = False
                    break
                total_arch_rec += int(res_arch.get("total_records", 0) or 0)
                total_arch_files += int(res_arch.get("files_created", 0) or 0)
                if int(res_arch.get("total_records", 0) or 0) < 50000:
                    break
            if total_arch_files > 0:
                print(f"📦 [Cold Archive] Збережено {total_arch_rec} котирувань у {total_arch_files} Parquet-файлів перед ротацією.")
        except Exception as arch_err:
            arch_ok = False
            print(f"⚠️ [Cold Archive] Помилка архівації перед ротацією: {arch_err}")

        if arch_ok:
            cur.execute(f"DELETE FROM odds_history WHERE {time_col} < NOW() - INTERVAL '4 days';")
        else:
            print("⚠️ [Cold Archive] Пропущено видалення старих котирувань через незавершену архівацію.")
    cur.execute("DELETE FROM events WHERE commence_time < NOW() - INTERVAL '4 days';")
    conn.commit()
    cur.close()
    conn.close()
    print(f"3. Збережено подій: {len(events_batch)}, котирувань: {len(odds_raw)}")
    return len(events_batch), len(odds_raw), rem_credits
