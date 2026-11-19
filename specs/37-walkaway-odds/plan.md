# План реалізації SPEC-37: Walkaway Odds in Telegram Alerts

## Етап 1: Математичне ядро (`statmonitor/novig.py`)
- Додати функцію `estimate_walkaway_odds(odds, drop_pct=None, confidence=None, fair_prob=None, min_edge=0.015)`.
- Додати хелпер форматування `format_walkaway_instruction(walkaway_k)`.

## Етап 2: Міграція БД (`migrations/016_paper_bets_walkaway_odds.sql`)
- Створити міграцію з додаванням колонки `walkaway_odds NUMERIC(6,2)` до `paper_bets`.
- Оновити `place_paper_bet` у `statmonitor/paper_trading.py` для запису `walkaway_odds`.

## Етап 3: Інтеграція в Pipeline та Telegram Alerts
- У `statmonitor/pipeline.py`:
  - Додати розрахунок та відображення рядка `🎯 Ставити, поки коеф ≥ X.XX` у картку алерта з графіком.
  - Додати відображення порогу `🛑 Поріг: ≥ X.XX` у підсумкове зведення AI-вердиктів.
  - Передавати `walkaway_odds` у `place_paper_bet`.

## Етап 4: Інтеграція в Бот та Пакетний Розрахунок
- У `statmonitor/bot.py`:
  - Відображати поріг у виводі `/bets`.
  - У команді `/edit_odds` видавати попередження, якщо новий коефіцієнт став `< walkaway_odds`.
- У `statmonitor/real_bankroll.py`:
  - Включати `walkaway_odds` у пропозиції `prepare_real_stakes_batch`.

## Етап 5: Оновлення Web Dashboard (`dashboard.py`)
- Додати колонку `Поріг (Walkaway)` у таблицю активних ставок (Вкладка 1) та активних реальних ставок (Вкладка 2).
- Відображати поріг у модальному блоці перенесення ставок у реальний банк (`show_real_stake_calc`).

## Етап 6: Автотести та Верифікація
- Написати `test_walkaway_odds.py` (покриття формул, екстремальних значень, інтеграції в пайплайн і бот).
- Запустити повний регресійний набір (має бути >= 190 тестів).
- Оновити документацію та надіслати зміни в репозиторій.
