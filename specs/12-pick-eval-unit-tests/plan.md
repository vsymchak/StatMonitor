# План реалізації SPEC-12: Unit Test Suite for Pick Parsing & Score Evaluation

1. **Створення тест-сьюту `test_eval_picks.py`**:
   - Використання стандартного `unittest.TestCase` для автоматичного виявлення `python -m unittest discover`.
   - Окремі класи тестів:
     - `TestFormatPick`: тестування форматування 1X2, фор, тоталів, баскетбольних ліній, сторонніх назв.
     - `TestEvalOutcome`: тестування розрахунку результатів для футболу, баскетболу, тенісу (WON, LOST, VOID).
     - `TestExtractShortPick`: тестування парсингу висновків Gemini AI, очищення тегів, видалення кефів, балансування дужок.
2. **Верифікація тестів**:
   - Запуск `python test_eval_picks.py`.
   - Запуск загального раннера `python -m unittest discover -s . -p "test_*.py"`.
3. **Оновлення документації**:
   - Оновлення `docs/roadmap.md` (Крок 12 -> Shipped).
   - Оновлення `docs/roadmap-diagram.md` (Крок 12 -> Shipped).
4. **Git commit & push**:
   - Зафіксувати зміни та завантажити в гілку `main`.
