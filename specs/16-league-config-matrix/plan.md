# План реалізації SPEC-16: Multi-Sport & Custom League Configuration Matrix

1. **Створення файлу конфігурації `config/leagues.json`**:
   - 14 цільових ліг (футбол, баскетбол, теніс) з категоріями, назвами, порогами просідання та прапорцями активності `enabled`.
2. **Створення модуля `statmonitor/league_config.py`**:
   - Реалізація `load_leagues_config()`, `get_active_sports_map()`, `get_active_target_sports()`, `get_league_thresholds()`.
   - Вбудована дефолтна матриця для гарантованого fallback при відсутності файлу.
3. **Інтеграція в `statmonitor/config.py` та `statmonitor/pipeline.py`**:
   - Ініціалізація `SPORTS_MAP` та `TARGET_SPORTS` з конфігураційного модуля.
   - Використання індивідуальних порогів `(min_drop, min_odds, max_odds)` у конвеєрі `check_alerts_and_notify()`.
4. **Експорт у `statmonitor/__init__.py`**:
   - Експортувати функції роботи з матрицею ліг.
5. **Тестування (`test_league_config.py`)**:
   - Тестування завантаження файлу JSON.
   - Тестування фільтрації за `enabled: false`.
   - Тестування дефолтного fallback при помилках чи відсутності файлу.
   - Тестування отримання кастомних порогів для різних ліг.
6. **Оновлення документації**:
   - Оновлення `docs/roadmap.md` та `docs/roadmap-diagram.md` (17 з 17 Shipped 🎉).
   - Оновлення `docs/architecture.md` та `README.md`.
7. **Git commit & push**:
   - Зафіксувати та відправити на GitHub.
