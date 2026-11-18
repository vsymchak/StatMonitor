# План впровадження SPEC-21: AI Confidence Score & Value Filtering

## Фази реалізації:

- [x] **Фаза 1: Схема бази даних та міграції**
  - Створено міграцію `migrations/010_ai_confidence_score.sql`
  - Додано колонки `confidence_score` та `risk_level` до `paper_bets` і `ai_match_analysis` у `statmonitor/database.py`

- [x] **Фаза 2: Парсер оцінки впевненості у Gemini AI**
  - Оновлено промпт `analyze_gemini` у `statmonitor/ai.py`
  - Створено функцію `extract_confidence_score(ai_verdict)`
  - Експортовано в `statmonitor/__init__.py`

- [x] **Фаза 3: Value Filtering та модуляція Келлі**
  - Оновлено `calculate_kelly_fraction` з урахуванням `confidence`
  - Впроваджено фільтр відхилення ставок з оцінкою $< 7/10$ у `place_paper_bet`
  - Інтегровано виклик у `statmonitor/pipeline.py`

- [x] **Фаза 4: Відображення в інтерфейсах (TG & Dashboard)**
  - Додано виведення оцінки та ризику в команді `/bets` у `statmonitor/bot.py`
  - Додано стовпчик `ШІ Сигнал` у таблиці активних ставок і списку вердиктів у `dashboard.py`

- [x] **Фаза 5: Тестування та верифікація**
  - Створено набір тестів `test_confidence.py` (7 тестів)
  - Усі 118 тестів проходять успішно
