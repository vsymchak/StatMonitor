import re
import time
import requests
from datetime import datetime, timezone, timedelta

from statmonitor.config import (
    TG_BOT_TOKEN,
    TG_CHAT_ID,
    INITIAL_BANKROLL,
    KYIV_TZ,
)
from statmonitor.database import get_db
from statmonitor.notifier import send_tg, esc, fmt_kyiv

DEFAULT_KEYBOARD = {
    "keyboard": [
        [{"text": "/status"}, {"text": "/bank"}],
        [{"text": "/bets"}, {"text": "/schedule"}],
        [{"text": "/today"}, {"text": "/run_now"}],
    ],
    "resize_keyboard": True,
    "one_time_keyboard": False,
}

def is_authorized(chat_id):
    """Перевіряє, чи має користувач доступ до бота (захист від сторонніх запитів)."""
    if not TG_CHAT_ID:
        return True
    return str(chat_id).strip() == str(TG_CHAT_ID).strip()

def cmd_start_help():
    return (
        "🤖 <b>StatMonitor AI Assistant</b>\n\n"
        "Ваш персональний бот моніторингу коефіцієнтів, Smart Money та віртуального трейдингу.\n\n"
        "📋 <b>Доступні команди:</b>\n"
        "  • <b>/status</b> — Стан сервісу, пульс Watchdog, квоти ліг\n"
        "  • <b>/bank</b> — Фінансовий баланс, вільний капітал, ROI\n"
        "  • <b>/bets</b> — Активні ставки у грі (PENDING) з їхніми ID\n"
        "  • <b>/edit_odds &lt;ID&gt; &lt;коеф&gt;</b> — Змінити коефіцієнт нерозрахованої ставки\n"
        "  • <b>/today</b> — Результати розрахованих ставок за день\n"
        "  • <b>/schedule</b> — Контрольні точки найближчих перевірок\n"
        "  • <b>/run_now</b> — Негайний позачерговий запуск сканування\n"
        "  • <b>/help</b> — Показати це меню підказки"
    )

def cmd_status(cur):
    lines = ["🖥️ <b>СТАТУС СИСТЕМИ STATMONITOR</b>\n"]

    # 1. Пульс Watchdog
    cur.execute("SELECT last_ping_at, last_status, last_duration_sec, metadata FROM system_heartbeat WHERE service_name='StatMonitor' LIMIT 1;")
    row_hb = cur.fetchone()
    if row_hb:
        t_ping = row_hb[0]
        st_icon = "🟢" if row_hb[1] == "OK" or row_hb[1] == "ONLINE" else "🟡"
        lines.append(f"{st_icon} <b>Пульс:</b> <code>{row_hb[1]}</code> ({fmt_kyiv(t_ping)})")
        lines.append(f"⏱ <b>Тривалість останнього циклу:</b> <code>{row_hb[2]} с</code>")
    else:
        lines.append("⚪ <b>Пульс:</b> Записів у системі ще немає")

    # 2. Smart Rate-Limiter (категорії ліг)
    cur.execute("SELECT tier, COUNT(*) FROM sports_poll_log GROUP BY tier;")
    tiers_count = dict(cur.fetchall())
    hot_c = tiers_count.get("HOT", 0)
    warm_c = tiers_count.get("WARM", 0)
    cold_c = tiers_count.get("COLD", 0)
    lines.append(f"\n🚦 <b>Smart Rate-Limiter:</b>")
    lines.append(f"  🔥 HOT (< 6 год): <b>{hot_c}</b> | 🌤 WARM: <b>{warm_c}</b> | ❄️ COLD: <b>{cold_c}</b>")

    # 3. Найближча точка планувальника
    cur.execute("SELECT target_time, trigger_type, description FROM scheduler_plan WHERE status='PLANNED' AND target_time > NOW() ORDER BY target_time ASC LIMIT 1;")
    row_sched = cur.fetchone()
    if row_sched:
        t_sc = fmt_kyiv(row_sched[0])
        lines.append(f"\n⏰ <b>Наступна перевірка:</b> <code>{t_sc}</code>\n   🎯 {esc(row_sched[2])}")
    else:
        lines.append("\n⏰ <b>Наступна перевірка:</b> За розкладом крону")

    return "\n".join(lines)

def cmd_bank(cur):
    try:
        cur.execute("SELECT status, stake_uah, profit_uah, odds, closing_odds, clv_pct, beat_closing_line FROM paper_bets;")
        rows = cur.fetchall()
    except Exception:
        cur.execute("SELECT status, stake_uah, profit_uah FROM paper_bets;")
        rows = cur.fetchall()

    won, lost, void, pending = 0, 0, 0, 0
    net_profit = 0.0
    locked_pending = 0.0
    turnover = 0.0
    clv_records = []

    for r in rows:
        st = r[0]
        stake = r[1]
        prof = r[2]
        stk = float(stake or 0)
        p = float(prof or 0)
        if st == "WON":
            won += 1
            net_profit += p
            turnover += stk
        elif st == "LOST":
            lost += 1
            net_profit += p
            turnover += stk
        elif st == "VOID":
            void += 1
            turnover += stk
        elif st == "PENDING":
            pending += 1
            locked_pending += stk

        if len(r) >= 7 and (r[4] is not None or r[5] is not None):
            clv_records.append({
                "odds": r[3],
                "closing_odds": r[4],
                "clv_pct": r[5],
                "beat_closing_line": r[6],
            })

    curr_bank = round(INITIAL_BANKROLL + net_profit, 2)
    avail_bank = round(max(0.0, curr_bank - locked_pending), 2)
    roi = round((net_profit / turnover * 100), 2) if turnover > 0 else 0.0
    settled_count = won + lost
    win_rate = round((won / settled_count * 100), 1) if settled_count > 0 else 0.0
    p_sign = "+" if net_profit > 0 else ""

    from statmonitor.analytics import calculate_clv_metrics
    clv_m = calculate_clv_metrics(clv_records) if clv_records else None

    lines = [
        "💰 <b>ФІНАНСОВИЙ ЗВІТ (PAPER BANK)</b>\n",
        f"🏦 <b>Поточний капітал:</b> <code>{curr_bank:,.2f} грн</code>",
        f"💵 <b>Вільні кошти:</b> <code>{avail_bank:,.2f} грн</code>",
        f"🔒 <b>Заблоковано в ставках:</b> <code>{locked_pending:,.2f} грн</code>\n",
        f"📈 <b>Чистий прибуток:</b> <b><code>{p_sign}{net_profit:,.2f} грн</code></b>",
        f"📊 <b>ROI:</b> <b><code>{p_sign}{roi}%</code></b> | <b>Вінрейт:</b> <code>{win_rate}%</code>",
        f"🔄 <b>Оборот:</b> <code>{turnover:,.2f} грн</code>",
    ]
    if clv_m and clv_m.get("total_with_clv", 0) > 0:
        lines.append(f"🎯 <b>Beat the Closing Line:</b> <code>{clv_m['beat_line_pct']}%</code> | <b>Сер. CLV:</b> <code>{clv_m['avg_clv_pct']:+.2f}%</code>")

    lines.extend([
        f"\n🎯 <b>Статистика ставок ({len(rows)}):</b>",
        f"  🟢 Виграно: <b>{won}</b> | 🔴 Програно: <b>{lost}</b>",
        f"  ⚪ Повернень: <b>{void}</b> | ⏳ В грі: <b>{pending}</b>",
    ])
    return "\n".join(lines)

def cmd_bets(cur):
    try:
        cur.execute("SELECT COALESCE(SUM(profit_uah), 0) FROM paper_bets WHERE status IN ('WON', 'LOST', 'VOID');")
        net_p = float(cur.fetchone()[0] or 0)
    except Exception:
        net_p = 0.0
    current_bank = max(100.0, INITIAL_BANKROLL + net_p)

    try:
        cur.execute("""
            SELECT id, match_name, sport, pick_label, odds, stake_uah, commence_time, kelly_pct 
            FROM paper_bets 
            WHERE status='PENDING' 
            ORDER BY commence_time ASC;
        """)
        rows = cur.fetchall()
    except Exception:
        try:
            cur.execute("""
                SELECT id, match_name, sport, pick_label, odds, stake_uah, commence_time 
                FROM paper_bets 
                WHERE status='PENDING' 
                ORDER BY commence_time ASC;
            """)
            rows = cur.fetchall()
        except Exception:
            rows = []

    if not rows:
        return "ℹ️ <b>Наразі немає активних ставок у грі.</b>\nВсі попередні парі розраховано або очікується новий сигнал."

    lines = [f"🎯 <b>АКТИВНІ СТАВКИ В ГРІ ({len(rows)}):</b>\n"]
    for i, r in enumerate(rows, 1):
        if len(r) >= 8:
            bid, m_name, sport, pick_lbl, odds, stake, c_time, k_pct = r[:8]
            id_prefix = f"[ID #{bid}] "
        elif len(r) >= 7:
            bid, m_name, sport, pick_lbl, odds, stake, c_time = r[:7]
            k_pct = None
            id_prefix = f"[ID #{bid}] "
        else:
            m_name, sport, pick_lbl, odds, stake, c_time = r[:6]
            k_pct = None
            id_prefix = ""
        c_str = fmt_kyiv(c_time)

        pct_val = None
        if k_pct is not None:
            pct_val = float(k_pct)
        elif current_bank > 0 and float(stake) > 0:
            pct_val = round((float(stake) / current_bank) * 100, 1)

        pct_badge = f" (<b>{pct_val:.1f}%</b> банку за Келлі)" if pct_val is not None else ""
        lines.append(
            f"<b>{i}. {id_prefix}{esc(m_name)}</b>\n"
            f"   🕒 Старт (Київ): <code>{c_str}</code>\n"
            f"   🎯 Вибір: <b>{esc(pick_lbl)}</b> (Коеф: <code>{float(odds):.2f}</code>)\n"
            f"   💵 Ставка: <code>{float(stake):.2f} грн</code>{pct_badge}\n"
        )
    lines.append("✏️ <i>Щоб змінити коефіцієнт ставки:</i> <code>/edit_odds &lt;ID&gt; &lt;новий_коеф&gt;</code>")
    return "\n".join(lines)

def cmd_today(cur):
    cur.execute("""
        SELECT match_name, pick_label, odds, stake_uah, status, profit_uah, match_score, settled_at 
        FROM paper_bets 
        WHERE status IN ('WON', 'LOST', 'VOID') 
          AND settled_at >= NOW() - INTERVAL '24 hours'
        ORDER BY settled_at DESC;
    """)
    rows = cur.fetchall()
    if not rows:
        return "ℹ️ <b>За останні 24 години немає розрахованих ставок.</b>"

    day_profit = sum(float(r[5] or 0) for r in rows)
    p_sign = "+" if day_profit > 0 else ""
    won_c = sum(1 for r in rows if r[4] == "WON")
    lost_c = sum(1 for r in rows if r[4] == "LOST")

    lines = [
        f"📅 <b>РЕЗУЛЬТАТИ ЗА ДОБУ (Розраховано: {len(rows)}):</b>",
        f"Прибуток: <b><code>{p_sign}{day_profit:,.2f} грн</code></b> (🟢 {won_c} / 🔴 {lost_c})\n",
    ]
    for r in rows[:10]:
        m_name, pick_lbl, odds, stake, st, prof, sc, s_time = r
        icon = "🟢" if st == "WON" else ("🔴" if st == "LOST" else "⚪")
        p_val = f"+{float(prof):.2f}" if float(prof) > 0 else f"{float(prof):.2f}"
        sc_str = f" [Рахунок: {sc}]" if sc else ""
        lines.append(f"{icon} <b>{esc(m_name)}</b>{esc(sc_str)}\n   🎯 {esc(pick_lbl)} | {p_val} грн ({st})")

    return "\n".join(lines)

def cmd_schedule(cur):
    cur.execute("""
        SELECT target_time, trigger_type, description 
        FROM scheduler_plan 
        WHERE status='PLANNED' AND target_time > NOW() - INTERVAL '10 minutes'
        ORDER BY target_time ASC 
        LIMIT 6;
    """)
    rows = cur.fetchall()
    if not rows:
        return "⏰ <b>Найближчих контрольних точок не заплановано.</b>\nСистема використовує стандартний інтервальний розклад."

    lines = ["⏰ <b>НАЙБЛИЖЧІ КОНТРОЛЬНІ ТОЧКИ РОЗКЛАДУ:</b>\n"]
    for r in rows:
        t_str = fmt_kyiv(r[0])
        icon = "🎯" if r[1] == "PRE_MATCH" else "⚖️"
        lines.append(f"  {icon} <code>{t_str}</code> — {esc(r[2])}")
    return "\n".join(lines)

def cmd_run_now():
    try:
        from trigger_dispatch import trigger_via_webhook
        ok, msg = trigger_via_webhook(secret="ALTECsrs1989_", source="telegram_bot")
        if ok:
            return "🚀 <b>Запуск моніторингу ініційовано!</b>\nВоркфлоу активовано через Cloudflare Webhook. Очікуйте оновлення котирувань найближчим часом."
        return f"⚠️ <b>Помилка активації вебхука:</b>\n<code>{esc(msg)}</code>"
    except Exception as e:
        return f"⚠️ <b>Не вдалося відправити тригер:</b> {esc(e)}"

def handle_command(cmd_text, chat_id, cur, conn):
    """
    Головний диспетчер команд бота.
    Повертає кортеж: (response_text, reply_markup)
    """
    if not is_authorized(chat_id):
        return (
            "⛔ <b>Доступ обмежено.</b>\n"
            "Цей бот є приватним асистентом системи StatMonitor.",
            None,
        )

    # Очищуємо команду від зайвих пробілів та @bot_name
    parts = cmd_text.strip().split() if cmd_text else []
    raw = parts[0].lower() if parts else ""
    cmd = raw.split("@")[0].lstrip("/")

    if cmd in ("start", "help", ""):
        return cmd_start_help(), DEFAULT_KEYBOARD
    elif cmd == "status":
        return cmd_status(cur), DEFAULT_KEYBOARD
    elif cmd == "bank":
        return cmd_bank(cur), DEFAULT_KEYBOARD
    elif cmd == "bets":
        return cmd_bets(cur), DEFAULT_KEYBOARD
    elif cmd in ("edit_odds", "edit_bet", "set_odds"):
        if len(parts) < 3:
            return (
                "ℹ️ <b>Формат команди редагування коефіцієнта:</b>\n"
                "<code>/edit_odds &lt;ID_ставки&gt; &lt;новий_коефіцієнт&gt;</code>\n\n"
                "<i>Приклад:</i> <code>/edit_odds 28 1.58</code>\n\n"
                "💡 <i>Введіть /bets, щоб переглянути список активних ставок та їхні ID.</i>",
                DEFAULT_KEYBOARD,
            )
        try:
            bet_id = int(parts[1])
            new_k = float(parts[2].replace(",", "."))
        except ValueError:
            return (
                "⚠️ <b>Помилка аргументів:</b> ID ставки має бути цілим числом, а коефіцієнт — числом (наприклад: <code>/edit_odds 28 1.58</code>).",
                DEFAULT_KEYBOARD,
            )
        from statmonitor.paper_trading import update_pending_bet_odds
        ok, msg, old_k = update_pending_bet_odds(cur, conn, bet_id, new_k)
        if ok:
            cur.execute("SELECT match_name, pick_label, stake_uah, odds FROM paper_bets WHERE id=%s;", (bet_id,))
            row = cur.fetchone()
            m_name, pk, stk, k = row
            pot_prof = round(float(stk) * (float(k) - 1.0), 2)
            resp = (
                "✅ <b>Коефіцієнт успішно змінено!</b>\n\n"
                f"⚽ <b>Матч:</b> {esc(m_name)}\n"
                f"🎯 <b>Вибір:</b> <code>{esc(pk)}</code>\n"
                f"💰 <b>Ставка:</b> <code>{float(stk):.2f} грн</code>\n"
                f"📉 <b>Коефіцієнт:</b> <code>{old_k:.2f}</code> ➔ <b><code>{float(k):.2f}</code></b>\n"
                f"💵 <b>Очікуваний виграш:</b> <b><code>+{pot_prof:.2f} грн</code></b>"
            )
            return resp, DEFAULT_KEYBOARD
        else:
            return f"❌ <b>Помилка оновлення:</b>\n{esc(msg)}", DEFAULT_KEYBOARD
    elif cmd == "today":
        return cmd_today(cur), DEFAULT_KEYBOARD
    elif cmd == "schedule":
        return cmd_schedule(cur), DEFAULT_KEYBOARD
    elif cmd == "run_now":
        return cmd_run_now(), DEFAULT_KEYBOARD
    else:
        return (
            f"❓ <b>Невідома команда:</b> <code>/{esc(cmd)}</code>\n"
            f"Натисніть /help, щоб переглянути список доступних команд.",
            DEFAULT_KEYBOARD,
        )

def process_telegram_update(update, cur, conn):
    """Обробляє один Update-об'єкт від Telegram API."""
    msg = update.get("message") or update.get("edited_message")
    if not msg:
        return None

    chat_id = msg.get("chat", {}).get("id")
    text = msg.get("text")
    if not chat_id or not text:
        return None

    resp_text, markup = handle_command(text, chat_id, cur, conn)
    send_tg(resp_text, chat_id=chat_id, reply_markup=markup)
    return resp_text

def poll_updates(offset=None, limit=25, timeout=8):
    """Отримує нові повідомлення з Telegram Bot API через getUpdates."""
    if not TG_BOT_TOKEN:
        return []
    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates"
    params = {"limit": limit, "timeout": timeout}
    if offset is not None:
        params["offset"] = offset

    try:
        r = requests.get(url, params=params, timeout=timeout + 5)
        if r.status_code == 200:
            return r.json().get("result", [])
    except Exception as e:
        print(f"poll_updates err: {e}")
    return []

def run_bot_worker(single_iteration=False):
    """
    Запуск бота в режимі Polling:
    - single_iteration=True: обробляє накопичену чергу і завершує роботу (для cron).
    - single_iteration=False: безперервний фоновий цикл.
    """
    if not TG_BOT_TOKEN:
        print("Помилка: TG_BOT_TOKEN не задано.")
        return

    conn = get_db()
    if not conn:
        print("Помилка: Немає підключення до БД.")
        return
    cur = conn.cursor()

    print("🤖 StatMonitor Telegram Bot запущено. Очікування команд...")
    offset = None

    try:
        while True:
            updates = poll_updates(offset=offset)
            for u in updates:
                offset = u["update_id"] + 1
                try:
                    process_telegram_update(u, cur, conn)
                except Exception as ex:
                    print(f"Помилка обробки оновлення {u.get('update_id')}: {ex}")

            if single_iteration:
                break
            time.sleep(1)
    finally:
        cur.close()
        conn.close()
