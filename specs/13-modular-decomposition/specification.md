# Специфікація: Модульна декомпозиція ядра StatMonitor (SPEC-13)

## 1. Контекст та мета
Наразі файл `main.py` є монолітом обсягом $\sim 570$ рядків, де змішані:
* Робота з конфігурацією та змінними середовища.
* Низькорівнева взаємодія з базою даних PostgreSQL/Supabase.
* Мережеві запити до The Odds API з ротацією ключів.
* Генерація графіків у пам'яті через Matplotlib.
* Інтеграція з Google Gemini API та парсинг вердиктів.
* Двигунець віртуального трейдингу (Paper Bank: стейкінг, перевірка рахунків, розрахунок прибутку/збитку).
* Відправка повідомлень та фотографій у Telegram Bot API.
* Оркестрація циклу виконання.

**Мета SPEC-13**:
Рефакторинг монолітного `main.py` у чистий, масштабований Python-пакет `statmonitor/` зі збереженням 100% зворотної сумісності для GitHub Actions та зовнішніх скриптів.

---

## 2. Цільова модульна архітектура

```
StatMonitor/
├── statmonitor/
│   ├── __init__.py           # Експорт публічного API пакету
│   ├── config.py             # Змінні середовища, таймзона Kyiv, мапінг ліг, ліміти
│   ├── database.py           # Підключення до БД, адаптація колонок, міграції
│   ├── notifier.py           # Telegram API: чанкінг, екранування, send_tg, send_photo
│   ├── fetcher.py            # The Odds API: збір котирувань, ротація ключів, збереження
│   ├── chart.py              # Matplotlib: побудова графіків просідання у BytesIO
│   ├── ai.py                 # Gemini API: каскадні моделі, Search Grounding, аналіз
│   └── paper_trading.py      # Paper Bank: стейкінг 2-4%, валідація, розрахунок ставок, звіт
├── main.py                   # Легковажний оркестратор (~70 рядків)
```

---

## 3. Обов'язки модулів

| Модуль | Відповідальність | Ключові функції |
| :--- | :--- | :--- |
| `statmonitor.config` | Завантаження env, константи, списки ліг, початковий банкрол | `INITIAL_BANKROLL`, `KYIV_TZ`, `SPORTS_MAP` |
| `statmonitor.database` | Пул з'єднань, інспекція схеми, міграції | `get_db()`, `get_cols()`, `pick()`, `pick_v()` |
| `statmonitor.notifier` | Доставка в Telegram, безпечне форматування | `send_tg()`, `send_photo()`, `esc()`, `fmt_kyiv()` |
| `statmonitor.fetcher` | Запити до The Odds API, ротація ключів | `fetch_and_save_odds()` |
| `statmonitor.chart` | Візуалізація коливань котирувань | `build_chart()` |
| `statmonitor.ai` | Інтеграція Gemini, парсинг ставок | `analyze_gemini()`, `extract_short_pick()` |
| `statmonitor.paper_trading` | Облік балансу, розрахунок матчів | `place_paper_bet()`, `settle_pending_bets()`, `send_daily_summary()`, `format_pick()` |

---

## 4. Зворотна сумісність та критерії приймання

- **AC-1**: `main.py` імпортує необхідні модулі з `statmonitor` та виконує повний цикл моніторингу без зміни поведінки.
- **AC-2**: Запуск `python -u main.py` працює без додаткових параметрів у GitHub Actions.
- **AC-3**: Скрипти `scheduler.py`, `sys_watchdog.py`, `dashboard.py` залишаються працездатними.
- **AC-4**: Створено модульні тести `test_modules.py` для перевірки ізольованої роботи кожного підмодуля.
- **AC-5**: Всі наявні тести (`test_dashboard.py`, `test_scheduler.py`, `test_watchdog.py`, `test_trigger_dispatch.py`, `test_migrate.py`) проходять успішно.
