# План реалізації SPEC-15: Telegram Interactive Bot Commands

1. **Створення модуля `statmonitor/bot.py`**:
   - `is_authorized(chat_id)`: перевірка доступу за `TG_CHAT_ID`.
   - `cmd_start_help()`: текст довідки та клавіатура швидких команд.
   - `cmd_status(cur)`: генерація звіту про пульс, Watchdog, квоти ліг.
   - `cmd_bank(cur)`: генерація фінансового звіту банку, ROI, вінрейту.
   - `cmd_bets(cur)`: генерація списку активних ставок (PENDING).
   - `cmd_today(cur)`: генерація денного звіту закритих ставок.
   - `cmd_schedule(cur)`: найближчі контрольні точки розкладу.
   - `cmd_run_now()`: запуск сканування через вебхук або `trigger_dispatch`.
   - `handle_command(cmd, chat_id, text, cur, conn)`: диспетчер команд.
   - `process_telegram_update(update, cur, conn)`: обробка update з пересилкою відповіді через `send_tg(..., chat_id=chat_id)`.
   - `run_polling(single_iteration=False)`: виклик `getUpdates` та цикл обробки.
2. **Створення CLI-точки запуску `bot_service.py`**:
   - Підтримка звичайного запуску `python bot_service.py` та прапорця `--once`.
3. **Експорт у `statmonitor/__init__.py`**:
   - Додати функції бота до публічного API пакету.
4. **Тестування (`test_bot.py`)**:
   - Тестування авторизації (`is_authorized`).
   - Тестування формування команд `/status`, `/bank`, `/bets`, `/today`, `/schedule`, `/run_now`.
   - Тестування обробки оновлень Telegram.
5. **Оновлення документації**:
   - Оновлення `docs/roadmap.md` та `docs/roadmap-diagram.md` (Крок 15 -> Shipped).
   - Оновлення `docs/architecture.md` та `README.md`.
6. **Git commit & push**:
   - Зафіксувати та відправити на GitHub.
