import json
from datetime import datetime, timezone, timedelta
from statmonitor.config import KYIV_TZ, DASHBOARD_URL
from statmonitor.notifier import send_photo, send_tg, esc
from statmonitor.chart import build_weekly_equity_chart
from statmonitor.analytics import calculate_clv_metrics

def generate_weekly_digest(cur, conn, force=False, days=7, send_telegram=True):
    """
    Генерує щотижневий графічний та фінансовий дайджест ефективності ставок.
    Відправляє графік капіталу (Matplotlib PNG) та аналітичний звіт у Telegram.
    Захищений від дублювання відправки за тижневим ключем (YYYY-WW).
    """
    kyiv_now = datetime.now(KYIV_TZ)
    # Тижневий ключ у форматі YYYY-WW (наприклад, 2026-W46)
    week_key = kyiv_now.strftime("%Y-W%W")

    # Перевірка на дублювання, якщо не вказано force=True
    if not force:
        try:
            cur.execute("SELECT status FROM weekly_digests WHERE week_key = %s;", (week_key,))
            row = cur.fetchone()
            if row and row[0] == "SENT":
                return {"status": "SKIPPED_ALREADY_SENT", "week_key": week_key}
        except Exception as e:
            if conn:
                conn.rollback()

    # Отримуємо всі розраховані ставки з бази
    cur.execute("""
        SELECT id, match_name, sport, pick_label, odds, stake_uah, status, profit_uah, settled_at, created_at, closing_odds, clv_pct, beat_closing_line
        FROM paper_bets
        WHERE status IN ('WON', 'LOST', 'VOID')
        ORDER BY COALESCE(settled_at, created_at) ASC;
    """)
    cols = [d[0] for d in cur.description]
    all_rows = [dict(zip(cols, r)) for r in cur.fetchall()]

    if not all_rows:
        return {"status": "NO_BETS", "week_key": week_key}

    # Фільтруємо ставки за вказаний період (за замовчуванням 7 днів)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    period_rows = []
    for r in all_rows:
        dt = r.get("settled_at") or r.get("created_at")
        if dt:
            if not hasattr(dt, "tzinfo") or not dt.tzinfo:
                dt = dt.replace(tzinfo=timezone.utc)
            if dt >= cutoff:
                period_rows.append(r)

    # Якщо за тиждень мало розрахованих ставок (< 2), беремо всі доступні для повноти звіту
    target_rows = period_rows if len(period_rows) >= 2 else all_rows

    total_bets = len(target_rows)
    won = sum(1 for r in target_rows if r.get("status") == "WON")
    lost = sum(1 for r in target_rows if r.get("status") == "LOST")
    void = sum(1 for r in target_rows if r.get("status") == "VOID")

    turnover = sum(float(r.get("stake_uah") or 0.0) for r in target_rows)
    net_profit = sum(float(r.get("profit_uah") or 0.0) for r in target_rows)
    roi_pct = (net_profit / turnover * 100.0) if turnover > 0 else 0.0
    win_rate = (won / (won + lost) * 100.0) if (won + lost) > 0 else 0.0

    # Загальний баланс за весь час
    all_net_profit = sum(float(r.get("profit_uah") or 0.0) for r in all_rows)
    initial_bank = 10000.0
    current_bank = initial_bank + all_net_profit

    # CLV аналітика
    clv_metrics = calculate_clv_metrics(target_rows)

    # Топ-3 найприбутковіші ставки
    won_bets = [r for r in target_rows if r.get("status") == "WON"]
    won_bets.sort(key=lambda x: float(x.get("profit_uah") or 0.0), reverse=True)
    top_3 = won_bets[:3]

    # Побудова точок історії капіталу для графіка
    history_points = []
    cum_bal = initial_bank
    for r in all_rows:
        dt = r.get("settled_at") or r.get("created_at")
        p = float(r.get("profit_uah") or 0.0)
        cum_bal += p
        if dt:
            history_points.append((dt, cum_bal))

    if not history_points:
        history_points.append((datetime.now(timezone.utc), current_bank))

    # Генерація PNG-графіка в пам'яті
    chart_buf = build_weekly_equity_chart(
        history_points=history_points,
        start_bank=initial_bank,
        end_bank=current_bank,
        title="Тижнева динаміка капіталу (Paper Bankroll)",
    )

    # Форматування текстового звіту
    sign = "+" if net_profit >= 0 else ""
    roi_sign = "+" if roi_pct >= 0 else ""
    p_start = (kyiv_now - timedelta(days=days)).strftime("%d.%m")
    p_end = kyiv_now.strftime("%d.%m")

    caption_lines = [
        "📊 <b>ТИЖНЕВИЙ ДАЙДЖЕСТ STATMONITOR</b>",
        f"🗓 <b>Період:</b> {p_start} – {p_end} (Тиждень #{kyiv_now.strftime('%W')})",
        "",
        "💰 <b>Фінансові результати:</b>",
        f"• Чистий прибуток: <b>{sign}{net_profit:,.2f} ₴</b>",
        f"• ROI: <b>{roi_sign}{roi_pct:.1f}%</b>",
        f"• Оборот: <b>{turnover:,.2f} ₴</b>",
        f"• Поточний банк: <b>{current_bank:,.2f} ₴</b>",
        "",
        "🎯 <b>Ефективність ставок:</b>",
        f"• Ставок: <b>{total_bets}</b> (В: {won} | П: {lost} | ПОВ: {void})",
        f"• Win Rate: <b>{win_rate:.1f}%</b>",
    ]

    if clv_metrics.get("clv_tracked_count", 0) > 0:
        clv_sign = "+" if clv_metrics["avg_clv_pct"] >= 0 else ""
        caption_lines.append(
            f"• Сер. CLV: <b>{clv_sign}{clv_metrics['avg_clv_pct']:.1f}%</b> | Beat Line: <b>{clv_metrics['beat_closing_line_pct']:.1f}%</b>"
        )

    if top_3:
        caption_lines.append("")
        caption_lines.append("🏆 <b>Топ найприбутковіших ставок:</b>")
        for i, b in enumerate(top_3, 1):
            m = esc(b.get("match_name") or "Матч")
            pick = esc(b.get("pick_label") or "")
            odds = float(b.get("odds") or 0.0)
            prof = float(b.get("profit_uah") or 0.0)
            sp = str(b.get("sport") or "")
            icon = "⚽" if "soccer" in sp else ("🎾" if "tennis" in sp else ("🏀" if "basket" in sp else "🎯"))
            caption_lines.append(f"{i}. {icon} {m} ({pick}) @ {odds:.2f} ➔ <b>+{prof:,.2f} ₴</b>")

    caption_lines.append("")
    caption_lines.append(f"🌐 <a href=\"{DASHBOARD_URL}\">Детальна аналітика на дашборді</a>")

    caption_text = "\n".join(caption_lines)

    # Відправка у Telegram
    send_status = "NOT_SENT"
    if send_telegram:
        if chart_buf:
            try:
                send_photo(chart_buf, caption=caption_text)
                send_status = "SENT"
            except Exception as e:
                print(f"Помилка відправки фото дайджесту: {e}")
                send_tg(caption_text)
                send_status = "SENT_TEXT_ONLY"
        else:
            send_tg(caption_text)
            send_status = "SENT_TEXT_ONLY"

    # Запис у БД логу відправлених дайджестів
    metrics_summary = {
        "period": f"{p_start} - {p_end}",
        "total_bets": total_bets,
        "won": won,
        "lost": lost,
        "void": void,
        "net_profit": round(net_profit, 2),
        "roi_pct": round(roi_pct, 2),
        "turnover": round(turnover, 2),
        "current_bank": round(current_bank, 2),
        "clv_metrics": clv_metrics,
        "has_chart": chart_buf is not None,
    }

    try:
        cur.execute("""
            INSERT INTO weekly_digests (week_key, sent_at, metrics_json, status)
            VALUES (%s, NOW(), %s, %s)
            ON CONFLICT (week_key) DO UPDATE
            SET sent_at = NOW(), metrics_json = EXCLUDED.metrics_json, status = EXCLUDED.status;
        """, (week_key, json.dumps(metrics_summary, ensure_ascii=False), send_status))
        if conn:
            conn.commit()
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Помилка збереження weekly_digests: {e}")

    return {
        "status": send_status,
        "week_key": week_key,
        "metrics": metrics_summary,
        "caption": caption_text,
    }
