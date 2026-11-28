"""
Локальний фоновий воркер SX Bet для Windows-ноутбука.

Виконує лише синхронізацію біржі SX Bet та авто-стейкінг активних ставок
з Paper Bank напряму з локальної (не-US) IP-адреси без витрати квот Odds API / Gemini.
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime, timezone

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from statmonitor.config import KYIV_TZ, SUPABASE_DB_URL  # noqa: E402
from statmonitor.database import get_db  # noqa: E402
from statmonitor.sx_bet import (  # noqa: E402
    SXBetClient,
    auto_sync_and_stake_from_paper,
    is_sx_autostake_enabled,
    sync_sx_exchange_full,
)

RUNNING = True


def _handle_stop(signum, frame):
    global RUNNING
    print(f"\n🛑 Отримано сигнал зупинки ({signum}). Завершення локального воркера SX Bet...", flush=True)
    RUNNING = False


def _now_kyiv_str() -> str:
    return datetime.now(timezone.utc).astimezone(KYIV_TZ).strftime("%d.%m.%Y %H:%M:%S")


def run_sx_cycle(sync_only: bool = False) -> dict:
    """
    Виконує один цикл синхронізації SX Bet і розміщення ставок із Paper Bank.
    Повертає словник зі статусом ('ok', 'db_error', 'locked', 'missing_keys', 'disabled').
    """
    if not SUPABASE_DB_URL:
        print("❌ Не задано SUPABASE_DB_URL у .env. Оновіть файл .env перед запуском.", flush=True)
        return {"status": "db_error", "placed": 0}

    sx_client = SXBetClient()
    if not sx_client.api_key or not sx_client.private_key:
        print("❌ У .env відсутні SX_BET_API_KEY або SX_BET_PRIVATE_KEY.", flush=True)
        return {"status": "missing_keys", "placed": 0}

    conn = get_db()
    if not conn:
        print("❌ Не вдалося підключитися до Supabase. Перевірте SUPABASE_DB_URL (новий пароль!) у файлі .env.", flush=True)
        return {"status": "db_error", "placed": 0}

    has_lock = False
    try:
        if hasattr(conn, "server_version"):
            with conn.cursor() as cur_lk:
                cur_lk.execute("SELECT pg_try_advisory_lock(hashtext('sx_local_worker'));")
                row_lk = cur_lk.fetchone()
                if row_lk and row_lk[0] is False:
                    print("⏸️ [SX-Local] Інший екземпляр локального воркера вже працює. Пропуск.", flush=True)
                    return {"status": "locked", "placed": 0}
                has_lock = True

        print(f"\n🔄 [{_now_kyiv_str()}] Синхронізація SX Bet із біржею...", flush=True)
        sync_stats = sync_sx_exchange_full(conn, client=sx_client)
        bal = sync_stats.get("free_balance_usdc")
        bal_str = f"${bal:.2f}" if bal is not None else "RPC N/A"
        print(
            f"   💰 Proxy USDC: {bal_str} | Трейдів: {sync_stats.get('trades_fetched', 0)} | "
            f"Оновлено: {sync_stats.get('updated_bets', 0)} | Розраховано: {sync_stats.get('settled_bets', 0)} | "
            f"Прострочено: {sync_stats.get('expired_cleaned', 0)}",
            flush=True,
        )

        if sync_only:
            return {"status": "ok", "placed": 0, "sync": sync_stats}

        enabled, reason = is_sx_autostake_enabled(conn)
        if not enabled:
            print(f"⏸️ [SX-Local] Авто-стейкінг вимкнено: {reason}", flush=True)
            return {"status": "disabled", "placed": 0, "sync": sync_stats}

        placed = auto_sync_and_stake_from_paper(conn, client=sx_client)
        if placed:
            print(f"🎯 [{_now_kyiv_str()}] Розміщено {len(placed)} ставок на SX Bet:", flush=True)
            for b in placed:
                print(
                    f"   ✅ Paper #{b['paper_bet_id']}: {b['event']} | "
                    f"${b.get('stake_usdc', 1.0):.2f} USDC ({b.get('pct', 0)}%) @ {b.get('odds')} [{b.get('mode')}] -> {b.get('order_id')}",
                    flush=True,
                )
        else:
            print(f"ℹ️ [{_now_kyiv_str()}] Нових відповідних кандидатів із Paper Bank на SX Bet немає.", flush=True)

        return {"status": "ok", "placed": len(placed), "sync": sync_stats}
    finally:
        try:
            if has_lock and hasattr(conn, "server_version") and not getattr(conn, "closed", False):
                with conn.cursor() as cur_ulk:
                    cur_ulk.execute("SELECT pg_advisory_unlock(hashtext('sx_local_worker'));")
        except Exception:
            pass
        try:
            if not getattr(conn, "closed", False):
                conn.close()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="Локальний воркер авто-стейкінгу SX Bet (не-US IP)")
    parser.add_argument("--interval", type=int, default=300, help="Інтервал між перевірками у секундах (за замовч. 300 = 5 хв)")
    parser.add_argument("--once", action="store_true", help="Виконати один цикл і завершити")
    parser.add_argument("--sync-only", action="store_true", help="Тільки синхронізувати позиції без розміщення нових ставок")
    args = parser.parse_args()

    signal.signal(signal.SIGINT, _handle_stop)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_stop)

    print("=" * 68, flush=True)
    print("🌐 StatMonitor Local SX Bet Worker запущено!", flush=True)
    print(f"⏰ Інтервал опитування: {args.interval} сек (~{max(1, round(args.interval / 60))} хв)", flush=True)
    print(f"📂 Каталог: {ROOT_DIR}", flush=True)
    print("🛑 Для зупинки натисніть Ctrl+C або закрийте вікно.", flush=True)
    print("=" * 68, flush=True)

    first_run = True
    while RUNNING:
        try:
            res = run_sx_cycle(sync_only=args.sync_only)
            if first_run and res.get("status") in ("db_error", "missing_keys"):
                return 1
        except Exception as e:
            print(f"⚠️ [{_now_kyiv_str()}] Помилка циклу SX Bet: {e}", flush=True)
            if first_run and not SUPABASE_DB_URL:
                return 1

        first_run = False
        if args.once or not RUNNING:
            break

        next_ts = time.time() + max(30, args.interval)
        next_str = datetime.fromtimestamp(next_ts, tz=timezone.utc).astimezone(KYIV_TZ).strftime("%H:%M:%S")
        print(f"💤 Наступна перевірка о {next_str} (Київ)...", flush=True)

        for _ in range(max(30, args.interval)):
            if not RUNNING:
                break
            time.sleep(1)

    return 0


if __name__ == "__main__":
    sys.exit(main())
