# План реалізації SPEC-23: Both Teams to Score (BTTS) & Clean Totals Filtering

## Фаза 1: Конфігурація ліг
- [x] Додати ринок `"btts"` до конфігурації футбольних ліг у `config/leagues.json`.
- [x] Оновити `DEFAULT_LEAGUES_CONFIG` у `statmonitor/league_config.py`.

## Фаза 2: Збір даних та фільтрація чистих тоталів
- [x] Налаштувати запит ринку `btts` для футбольних ліг у `statmonitor/fetcher.py`.
- [x] Впровадити фільтр відсікання четвертних азіатських тоталів (`.25` та `.75`) у `fetcher.py`.
- [x] Синхронізувати захисний фільтр тоталів у `statmonitor/pipeline.py`.

## Фаза 3: Розрахунок та аналітика ставок
- [x] Оновити `format_pick` у `statmonitor/paper_trading.py` для підтримки лейблів «Обидві заб'ють: Так / Ні».
- [x] Оновити `parse_pick_label` для вилучення `(btts, Yes/No, None)`.
- [x] Реалізувати логіку розрахунку результату `eval_outcome` для ринку BTTS.
- [x] Додати підтримку ринку `btts` у `get_market_median_odds`.
- [x] Додати класифікацію групи «Обидві заб'ють» у `statmonitor/analytics.py:classify_market_group`.

## Фаза 4: Тестування та верифікація
- [x] Написати вичерпні тести у `test_eval_picks.py`.
- [x] Додати тест сегментації у `test_analytics.py`.
- [x] Перевірити успішність виконання всіх 105+ тестів (`python -m unittest discover`).

## Фаза 5: Документація та реліз
- [x] Створити специфікацію `specs/23-btts-clean-totals/specification.md` та `plan.md`.
- [ ] Оновити `docs/roadmap.md`, `docs/roadmap-diagram.md`, `docs/architecture.md`, `README.md`.
- [ ] Зробити git commit та push до репозиторію.
