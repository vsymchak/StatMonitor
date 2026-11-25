import re
import time
from datetime import datetime, timezone

from statmonitor.config import KYIV_TZ
from statmonitor.database import get_db, get_cols, pick, pick_v, ensure_tables
from statmonitor.notifier import send_tg, send_photo, esc, fmt_kyiv
from statmonitor.chart import build_chart
from statmonitor.ai import analyze_gemini, extract_short_pick, extract_confidence_score
from statmonitor.paper_trading import (
    format_pick,
    place_paper_bet,
    settle_and_report,
    resolve_alert_from_history,
    get_market_median_odds,
)
from statmonitor.novig import estimate_walkaway_odds

def check_alerts_and_notify(sports_map, t_start=None):
    print("4. Перевірка алертів і відправка (v3.4.1)...")
    conn = get_db()
    if not conn:
        print("Помилка підключення до БД для обробки алертів.")
        return

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
    print(f"ℹ️ [Pipeline] Коефіцієнти оновлено о {kyiv_now.strftime('%d.%m.%Y %H:%M')}")

    from statmonitor.league_config import get_league_thresholds, load_leagues_config
    leagues_cfg = load_leagues_config()

    cur.execute("SELECT * FROM v_odds_alerts;")
    v_cols = [d[0] for d in cur.description]
    items = []
    for r in cur.fetchall():
        d = dict(zip(v_cols, r))
        curr_k = float(pick_v(d, ("current_odds", "curr_odds", "last_odds", "odds", "price"), 0) or 0)
        pt = pick_v(d, ("point", "handicap", "line"))
        out = pick_v(d, ("outcome_name", "outcome", "selection", "side", "name"), "")
        sp_key = pick_v(d, ("sport", "sport_key"), r[1])
        ev_id = pick_v(d, ("event_id", "id", "match_id"), r[0])
        bm = pick_v(d, ("bookmaker", "bm"), r[4])
        mkt = pick_v(d, ("market_key", "market"))

        # 1. Добирати market і point напряму з odds_history (SPEC-18):
        # якщо v_odds_alerts не віддає point, перевіряємо в odds_history за event_id, bookmaker і price
        if pt is None:
            res_mkt, res_pt, res_out, res_price = resolve_alert_from_history(cur, ev_id, bm, curr_k, out)
            if res_pt is not None:
                pt = res_pt
                mkt = res_mkt or "spreads"
                if res_out:
                    out = res_out
                if res_price:
                    curr_k = res_price
            elif res_mkt:
                mkt = res_mkt

        # Динамічні пороги коефіцієнтів та чутливості прогрузу для ліги (SPEC-16 & SPEC-25)
        thresh = get_league_thresholds(sp_key, config=leagues_cfg)
        if not thresh.get("enabled", True):
            continue
        if curr_k < thresh["min_odds"] or curr_k > thresh["max_odds"]:
            continue
        drop_val = abs(float(pick_v(d, ("drop_pct", "change_pct", "diff_pct", "drop"), 0) or 0))
        if drop_val < thresh.get("min_drop_pct", 5.0):
            continue
        if pt is not None and abs((float(pt) * 100) % 50) != 0:
            continue
        if re.search(r"\d+\.(?:25|75)\b", str(out)):
            continue

        match_val = pick_v(d, ("match_name", "match"), r[2] if len(r) > 2 else "")
        if not match_val or str(match_val).strip() in ("", "None"):
            h = pick_v(d, ("home_team", "home"), "")
            a = pick_v(d, ("away_team", "away"), "")
            if h and a:
                match_val = f"{h} - {a}"
            else:
                match_val = str(ev_id)

        items.append({
            "event_id": ev_id,
            "sport": sp_key,
            "match": match_val,
            "c_time": pick_v(d, ("commence_time", "match_time"), r[3]),
            "bm": bm,
            "outcome": out,
            "market": mkt,
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

    # 4. Виключення матчів, на які вже зроблена ставка або які вже аналізувалися (SPEC-27 & SPEC-30 Anti-Spam Pipeline)
    active_events = set()
    try:
        cur.execute("SELECT event_id FROM paper_bets WHERE event_id IS NOT NULL;")
        for r in cur.fetchall():
            if r[0]:
                active_events.add(r[0])
        q_recent_ai = f"SELECT event_id FROM ai_match_analysis WHERE {ai_tm} > NOW() - INTERVAL '24 hours';" if ai_tm else "SELECT event_id FROM ai_match_analysis;"
        cur.execute(q_recent_ai)
        for r in cur.fetchall():
            if r[0]:
                active_events.add(r[0])
    except Exception as e:
        print(f"Помилка отримання активних/оброблених подій: {e}")

    summary_rows = []
    for ev_id, grp in list(grouped.items())[:15]:
        if ev_id in active_events:
            print(f"ℹ️ Пропуск {grp[0].get('match')}: на цей матч уже зафіксовано ставку або нещодавно проведено AI-аналіз (SPEC-30 Anti-Spam).")
            continue

        f = grp[0]
        title = sports_map.get(f["sport"], f["sport"])
        c_str = fmt_kyiv(f["c_time"])
        top_pick = format_pick(f["market"], f["outcome"], f["point"], f["match"])

        plain_drops, html_drops = [], []
        for al in grp[:4]:
            lbl = format_pick(al["market"], al["outcome"], al["point"], f["match"])
            plain_drops.append(f"- {lbl} ({al['bm']}): {al['start_k']} -> {al['curr_k']} ({al['drop']}%)")
            html_drops.append(f"📉 <b>{esc(lbl)}</b> | БК: <code>{esc(al['bm'])}</code>\n   <code>{al['start_k']:.3f}</code> ({fmt_kyiv(al['s_time'])}) ➔ <b><code>{al['curr_k']:.3f}</code></b> (<b>{al['drop']}%</b>)")

        walkaway_k = estimate_walkaway_odds(f["curr_k"], drop_pct=f.get("drop"))
        walkaway_line = f"\n🎯 <b>Ставити, поки коеф ≥ {walkaway_k:.2f}</b>" if walkaway_k else ""

        cap = f"⚽ <b>{esc(f['match'])}</b>\n🏆 <i>{esc(title)}</i>\n🗓 Початок: <code>{c_str}</code>\n🎯 Головний сигнал: <b>{esc(top_pick)}</b>{walkaway_line}\n\n" + "\n".join(html_drops)
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
                    cur.execute(
                        f"INSERT INTO ai_match_analysis (event_id, {ai_txt}, match_name, sport) "
                        f"VALUES (%s, %s, %s, %s) "
                        f"ON CONFLICT (event_id) DO UPDATE SET "
                        f"{ai_txt} = EXCLUDED.{ai_txt}, "
                        f"match_name = COALESCE(EXCLUDED.match_name, ai_match_analysis.match_name), "
                        f"sport = COALESCE(EXCLUDED.sport, ai_match_analysis.sport);",
                        (ev_id, ai_verdict, f["match"], f["sport"])
                    )
                    conn.commit()
                except Exception:
                    try:
                        cur.execute(f"INSERT INTO ai_match_analysis (event_id, {ai_txt}) VALUES (%s, %s) ON CONFLICT (event_id) DO UPDATE SET {ai_txt}=EXCLUDED.{ai_txt};", (ev_id, ai_verdict))
                        conn.commit()
                    except Exception:
                        conn.rollback()
                time.sleep(2)

        # SPEC-30: Текстовий AI-вердикт більше не спамиться окремим довгим повідомленням у Telegram.
        # Він збережений у базі і відображається у Web Dashboard.

        # SPEC-21: Оцінка сили сигналу Gemini (Confidence Score 1-10) та Value Filtering
        conf_score, risk_lvl = extract_confidence_score(ai_verdict)
        if conf_score is not None:
            try:
                cur.execute(
                    "UPDATE ai_match_analysis SET confidence_score=%s, risk_level=%s WHERE event_id=%s;",
                    (conf_score, risk_lvl, ev_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()

        short_pick = extract_short_pick(ai_verdict, top_pick)

        # 2. Розрахунок РЕАЛЬНОГО медіанного коефіцієнта ринку або еталонних БК (SPEC-18)
        real_odds = get_market_median_odds(cur, ev_id, short_pick, f["match"], fallback_odds=f["curr_k"])
        bet_walkaway = estimate_walkaway_odds(real_odds, drop_pct=f.get("drop"), confidence=conf_score)
        placed = place_paper_bet(
            cur, conn, ev_id, f["sport"], f["match"], f["c_time"], short_pick, real_odds,
            drop_pct=f.get("drop"), confidence=conf_score, risk_level=risk_lvl,
            walkaway_odds=bet_walkaway
        )

        if placed:
            dt_sort = f["c_time"] if hasattr(f["c_time"], "tzinfo") and f["c_time"].tzinfo else (f["c_time"].replace(tzinfo=timezone.utc) if hasattr(f["c_time"], "replace") else datetime.now(timezone.utc))
            conf_tag = f" ⭐ {conf_score}/10" if conf_score is not None else ""
            summary_rows.append({
                "dt": dt_sort,
                "time": c_str,
                "match": f["match"],
                "title": title,
                "pick": f"{short_pick}{conf_tag}",
                "odds": f"{real_odds:.2f}",
                "walkaway_odds": f"{bet_walkaway:.2f}" if bet_walkaway else None,
            })

    print(f"5. Відправка зведення ({len(summary_rows)} подій)...")
    if summary_rows:
        summary_rows.sort(key=lambda x: x["dt"])
        lines = ["📋 <b>ЗВЕДЕННЯ СТАВОК (AI-ВЕРДИКТ)</b>"]
        for i, r in enumerate(summary_rows, 1):
            walkaway_str = f" | 🛑 <b>Поріг: ≥ {r['walkaway_odds']}</b>" if r.get("walkaway_odds") else ""
            lines.append(f"<b>{i}. {esc(r['match'])}</b>\n   🕒 <code>{esc(r['time'])}</code> | <i>{esc(r['title'])}</i>\n   🎯 <b>{esc(r['pick'])}</b> — Коеф: <code>{r['odds']}</code>{walkaway_str}")

        # Посилання на гостьовий дашборд (SPEC-30)
        from statmonitor.config import DASHBOARD_URL
        lines.append(
            f"🌐 <b>Деталізована AI-аналітика (лазарет, форма, інсайди):</b>\n"
            f"👉 <a href='{DASHBOARD_URL}'><b>Відкрити гостьовий дашборд</b></a>\n"
            f"<i>(Повні звіти Gemini та динаміка ліній доступні для перегляду у гостьовому режимі)</i>"
        )
        send_tg("\n\n".join(lines))

    # 5b. Автономний стейкінг SX Bet (Web3 Auto-Staking на основі Paper Bets)
    try:
        if not (hasattr(conn, "_mock_return_value") or type(conn).__name__ in ("MagicMock", "Mock")):
            from statmonitor.sx_bet import auto_sync_and_stake_from_paper, sync_sx_positions_to_db
            sync_sx_positions_to_db(conn)
            sx_results = auto_sync_and_stake_from_paper(conn)
            if sx_results:
                print(f"🌐 [SX Bet] Розміщено {len(sx_results)} авто-ставок на біржі через API:")
                for sx_r in sx_results:
                    print(f"   • Paper #{sx_r['paper_bet_id']}: {sx_r['event']} (${sx_r.get('stake_usdc', 1.0):.2f} USDC, {sx_r.get('pct', 0)}%) -> SX Order {sx_r['order_id']}")
    except Exception as sxe:
        print(f"⚠️ [SX Bet] Помилка авто-стейкінгу: {sxe}")

    # 6. Динамічний розклад контрольних точок (SPEC-08)
    try:
        from scheduler import run_schedule_update, mark_checkpoints_executed
        mark_checkpoints_executed(cur, conn)
        run_schedule_update(cur, conn)
    except Exception as e:
        print(f"Помилка динамічного розкладу: {e}")
        try:
            send_tg(f"⚠️ <b>Помилка розкладу:</b> {esc(str(e))}")
        except Exception:
            pass

    # 7. Запис пульсу сервісу (SPEC-09)
    try:
        from sys_watchdog import record_heartbeat, ping_external_watchdog
        elapsed = round(time.time() - (t_start or time.time()), 2)
        hb_meta = {"events_checked": len(summary_rows)}
        try:
            from statmonitor.fetcher import check_odds_api_quota
            hb_meta["odds_quota"] = check_odds_api_quota()
        except Exception as qe:
            print(f"Quota check metadata err: {qe}")
        record_heartbeat(cur, conn, duration_sec=elapsed, status="OK", metadata=hb_meta)
        ping_external_watchdog()
    except Exception as e:
        print(f"Watchdog record err: {e}")

    cur.close()
    conn.close()
