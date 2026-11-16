import re
import requests
from datetime import datetime
from statmonitor.config import INITIAL_BANKROLL, API_KEY, API_KEY_RESERVE, KYIV_TZ
from statmonitor.notifier import send_tg

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

def place_paper_bet(cur, conn, ev_id, sport, match, c_time, pick_lbl, odds):
    try:
        if any(w in pick_lbl.lower() for w in ("пропустити", "утриматися")):
            return False
        cur.execute("SELECT 1 FROM paper_bets WHERE event_id=%s;", (ev_id,))
        if cur.fetchone():
            return False
        cur.execute("SELECT COALESCE(SUM(profit_uah),0), COALESCE(SUM(CASE WHEN status='PENDING' THEN stake_uah ELSE 0 END),0) FROM paper_bets;")
        prof, locked = cur.fetchone()
        avail = round(max(0.0, INITIAL_BANKROLL + float(prof) - float(locked)), 2)
        if avail < 50:
            return False
        k = float(odds)
        pct = 0.04 if k <= 1.75 else (0.03 if k <= 2.35 else 0.02)
        stake = min(round(avail * pct, 2), avail)
        cur.execute(
            "INSERT INTO paper_bets (event_id, sport, match_name, commence_time, pick_label, odds, stake_uah) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;",
            (ev_id, sport, match, c_time, pick_lbl, k, stake),
        )
        conn.commit()
        return True
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Place bet err: {e}")
        return False

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
        if conn:
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
        if conn:
            conn.rollback()
        print(f"Daily summary err: {e}")
