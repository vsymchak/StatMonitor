"""
CLI-сервіс запуску інтерактивного Telegram-бота StatMonitor (SPEC-15).

Використання:
    python bot_service.py           # Запуск безперервного демона
    python bot_service.py --once    # Одноразова обробка черги повідомлень і вихід
"""

import sys
import argparse
from statmonitor.bot import run_bot_worker

def main():
    parser = argparse.ArgumentParser(description="StatMonitor Interactive Telegram Bot")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Обробити всі наявні повідомлення з черги та завершити роботу",
    )
    args = parser.parse_args()

    try:
        run_bot_worker(single_iteration=args.once)
    except KeyboardInterrupt:
        print("\n👋 Роботу бота зупинено користувачем.")
        sys.exit(0)

if __name__ == "__main__":
    main()
