"""
StatMonitor Daemon (Серверний фоновий процес)
Автономне періодичне опитування коефіцієнтів, аналіз Gemini AI,
автоматичний стейкінг SX Bet та розрахунок завершених ставок.

Використання:
    python daemon.py                 # Запуск демона кожні 30 хвилин
    python daemon.py --interval 15   # Запуск кожні 15 хвилин
    python daemon.py --once          # Одноразовий запуск пайплайну і вихід
    python daemon.py --force         # Примусовий запуск ігноруючи планувальник
"""

import os
import sys
import time
import signal
import argparse
from datetime import datetime, timezone

def load_dotenv_fallback(env_path=".env"):
    """Завантажує змінні з .env без зовнішніх залежностей."""
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'").strip('"')
                if k not in os.environ:
                    os.environ[k] = v
    except Exception as e:
        print(f"⚠️ Не вдалося прочитати .env: {e}")

load_dotenv_fallback()

from main import run_pipeline

RUNNING = True

def handle_exit(signum, frame):
    global RUNNING
    print(f"\n🛑 Отримано сигнал зупинки ({signum}). Завершення роботи демона...")
    RUNNING = False

def run_daemon(interval_minutes: int = 30, force: bool = False, once: bool = False):
    global RUNNING
    signal.signal(signal.SIGINT, handle_exit)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, handle_exit)

    print("=" * 65)
    print("🤖 StatMonitor Server Daemon запущено!")
    print(f"⏰ Інтервал опитування: {interval_minutes} хв")
    print(f"📂 Робоча директорія: {os.getcwd()}")
    print(f"📅 Час старту: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 65)

    iteration = 0
    while RUNNING:
        iteration += 1
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        print(f"\n▶ [{iteration}] Запуск пайплайну о {now_str}...")

        try:
            os.environ.setdefault("TRIGGER_SOURCE", "daemon")
            run_pipeline(force=force)
            print(f"✅ [{iteration}] Пайплайн завершено успішно.")
        except Exception as e:
            print(f"❌ [{iteration}] Помилка виконання пайплайну: {e}")
            try:
                from statmonitor.database import log_system_error, get_db
                conn = get_db()
                if conn:
                    log_system_error(conn, "daemon", f"Помилка ітерації {iteration}: {e}", severity="ERROR", error_code="DAEMON_LOOP_ERR")
                    conn.close()
            except Exception:
                pass

        if once or not RUNNING:
            break

        sleep_seconds = interval_minutes * 60
        next_run_ts = time.time() + sleep_seconds
        next_run_str = datetime.fromtimestamp(next_run_ts, tz=timezone.utc).strftime("%H:%M:%S UTC")
        print(f"💤 Очікування {interval_minutes} хв (наступний запуск о {next_run_str})...")

        # Сегментований сон для швидкої реакції на Ctrl+C / SIGTERM
        for _ in range(sleep_seconds):
            if not RUNNING:
                break
            time.sleep(1)

    print("👋 Демон StatMonitor успішно зупинено.")

def main():
    parser = argparse.ArgumentParser(description="StatMonitor Server Daemon")
    parser.add_argument(
        "--interval",
        type=int,
        default=30,
        help="Інтервал між циклами в хвилинах (за замовчуванням: 30)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Виконати 1 ітерацію та вийти",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Примусово запускати всі модулі без очікування точок розкладу",
    )
    args = parser.parse_args()

    run_daemon(interval_minutes=args.interval, force=args.force, once=args.once)

if __name__ == "__main__":
    main()
