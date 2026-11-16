# Специфікація: Гібридний зовнішній тригер розкладу (SPEC-11)

## 1. Контекст та бізнес-мета
GitHub Actions має дві суттєві вади при роботі суто через внутрішній `schedule: cron`:
1. **Затримки в чергах**: У пікові години черга cron може запізнюватись на 20–45 хвилин.
2. **Зупинка неактивних репозиторіїв**: Якщо в репозиторії немає комітів понад 60 днів, GitHub автоматично відключає заплановані воркфлоу (`Scheduled workflows disabled`).

Натомість виклик через API — **`workflow_dispatch`** — стартує майже миттєво (за 5–15 секунд), оминаючи повільну чергу планувальника GitHub.

**Мета SPEC-11**: Забезпечити гібридний запуск воркфлоу через зовнішній Webhook та API GitHub (`workflow_dispatch`), що дозволяє запускати моніторинг за точним розкладом через безкоштовні зовнішні планувальники (Cron-job.org, Cloudflare Worker, Vercel, або власний сервер).

---

## 2. Компоненти рішення

### А. Модуль керування диспетчеризацією (`trigger_dispatch.py`)
Python-модуль та CLI-утиліта, яка:
* Аутентифікується через GitHub Personal Access Token або `GITHUB_TOKEN`.
* Викликає API GitHub для миттєвого тригеру:
  `POST https://api.github.com/repos/{owner}/{repo}/actions/workflows/scheduler.yml/dispatches`
* Отримує статус останніх запусків воркфлоу (`--status`).
* Експортує список контрольних точок із `scheduler_plan` у форматі cron / curl для налаштування зовнішніх сервісів (`--export-cron`).

### Б. Безсерверний Webhook-шлюз (`deploy/cloudflare_webhook.js`)
Готовий скрипт для безкоштовного Cloudflare Worker (до 100 000 безкоштовних запитів на день):
* Приймає вхідний HTTP GET/POST запит із секретним токеном:
  `https://statmonitor-trigger.<subdomain>.workers.dev/?secret=YOUR_SECRET&source=cron_job`
* Безпечно зберігає `GITHUB_TOKEN` у змінних Cloudflare (Secrets).
* Робить запит `dispatches` до GitHub API і повертає статус HTTP 200 із `run_id` або підтвердженням старту.

### В. Оновлення воркфлоу `.github/workflows/scheduler.yml`
* Додавання параметра `inputs.trigger_source` у блок `workflow_dispatch`:
  - `manual` (ручний запуск із вебінтерфейсу GitHub)
  - `external_webhook` (запуск через зовнішній планувальник / Cloudflare)
  - `watchdog_retry` (повторний запуск після збою)

---

## 3. Критерії приймання (Acceptance Criteria)

- **AC-1**: Модуль `trigger_dispatch.py` успішно формує валідні HTTP-запити до GitHub Actions API `workflow_dispatch`.
- **AC-2**: Модуль підтримує CLI-команди:
  - `python trigger_dispatch.py --trigger` (запуск воркфлоу)
  - `python trigger_dispatch.py --status` (перевірка останнього стану)
  - `python trigger_dispatch.py --export-curl` (генерація готової curl-команди для налаштування Cron-job.org)
- **AC-3**: Файл `deploy/cloudflare_webhook.js` містить автономний код для Cloudflare Worker з валідацією секретного ключа та обробкою помилок GitHub API.
- **AC-4**: Воркфлоу `.github/workflows/scheduler.yml` підтримує вхідний параметр `trigger_source` та відображає джерело запуску в логах.
- **AC-5**: Написано автотести `test_trigger_dispatch.py` для перевірки формування заголовків, URL та payload без відправки реальних запитів.
