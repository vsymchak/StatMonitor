# Чекліст виконання (SPEC-11)

- [x] 1. Створити модуль `trigger_dispatch.py`:
  - [x] `build_headers(token)`
  - [x] `build_dispatch_payload(ref, trigger_source)`
  - [x] `trigger_workflow(repo, workflow, token, ref, trigger_source)`
  - [x] `get_workflow_status(repo, workflow, token, limit)`
  - [x] `generate_curl_command(repo, workflow, token)`
- [x] 2. Створити безсерверний скрипт `deploy/cloudflare_webhook.js` для Cloudflare Worker.
- [x] 3. Оновити `.github/workflows/scheduler.yml` з підтримкою `inputs.trigger_source`.
- [x] 4. Створити автотести `test_trigger_dispatch.py`.
- [x] 5. Оновити статуси в `docs/roadmap.md` та `docs/roadmap-diagram.md` (крок 11 -> Shipped!).
- [x] 6. Провести перевірку та запустити тести.
