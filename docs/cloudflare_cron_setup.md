# Налаштування високоточного розкладу Cloudflare Worker Cron (Zero-Delay Architecture)

> **Мета**: Повна відмова від ненадійного внутрішнього крону GitHub Actions (який затримувався на 20–50+ хвилин у чергах) та перехід на високоточні **Cron Triggers на Edge-інфраструктурі Cloudflare** (0 секунд затримки).

---

## ⚡ Як увімкнути Cron у Cloudflare Dashboard (за 1 хвилину через браузер)

У вас уже створено та підключено воркер `statmonitor.symchak.workers.dev`. Щоб додати до нього регулярний розклад:

### Крок 1. Оновіть код воркера
1. Відкрийте [Cloudflare Dashboard](https://dash.cloudflare.com/) $\rightarrow$ **Workers & Pages**.
2. Оберіть ваш воркер `statmonitor`.
3. Натисніть **Edit Code** (або Quick Edit у правому кутку).
4. Замініть код на вміст файлу [**`cloudflare/worker.js`**](file:///c:/Users/vsymchak/projects/StatMonitor/cloudflare/worker.js).
5. Натисніть **Deploy** (Зберегти та розгорнути).

### Крок 2. Увімкніть розклад (Cron Trigger)
1. У налаштуваннях воркера перейдіть на вкладку **Settings** $\rightarrow$ **Triggers**.
2. Знайдіть блок **Cron Triggers** та натисніть **Add Cron Trigger**.
3. Вкажіть бажаний інтервал виконання:
   - `*/20 * * * *` — запуск кожні 20 хвилин (на 00, 20 та 40 хвилині години);
   - або `*/15 * * * *` — запуск кожні 15 хвилин.
4. Натисніть **Save Trigger**.

### Крок 3. Перевірте змінні середовища та секрети
У розділі **Settings** $\rightarrow$ **Variables and Secrets** переконайтеся, що налаштовані:
- `GH_PAT` (Encrypt / Secret) — GitHub Personal Access Token (з правами `repo` або `actions:write`).
- `SECRET_KEY` (Encrypt / Secret) — секретний ключ доступу (співпадає з ключем у Streamlit Secrets).
- `GH_REPO` (Text) — `vsymchak/StatMonitor` (за замовчуванням).
- `GH_WORKFLOW` (Text) — `scheduler.yml` (за замовчуванням).
- *(Рекомендовано для SPEC-38)* `SUPABASE_URL` (Text) — URL вашого проекту Supabase (наприклад, `https://xyzcompany.supabase.co`).
- *(Рекомендовано для SPEC-38)* `SUPABASE_KEY` (Encrypt / Secret) — Anon / Service Role ключ Supabase для швидких edge-перевірок розкладу.

---

## 🎯 Що змінилося в поведінці системи

1. **Zero-Cost Orchestration Sync (SPEC-38, 0 хв білінгу на холостих тіках)**:
   - Перед кожним запуском GitHub Actions воркер виконує легкий безкоштовний edge-запит до REST API Supabase.
   - Якщо немає контрольних точок у вікні `[now - 25m, now + 7m]`, немає ставок для термінового розрахунку і не настав час планового 80-хвилинного сканування — воркер миттєво завершується без виклику Actions.
   - Це повністю усуває перевитрату 2000 безкоштовних хвилин Actions на місяць!
2. **Точність секунда в секунду**: Cloudflare запускає воркер рівно у призначену секунду на найближчому edge-вузлі.
3. **Миттєвий виклик GitHub Actions API**: коли є події, воркер відправляє `POST /dispatches` безпосередньо у чергу виконання GitHub.
4. **Відсутність шуму та хибних тривог**:
   - Планувальник більше не генерує зобов'язувальні точки для випадкових матчів, на які немає активних ставок.
   - Нічний фільтр (00:00 – 08:00) автоматично переводить застарілі нічні точки у статус `SKIPPED` без тривожних повідомлень у Telegram.
5. **Контроль залишку квоти токенів**:
   - В адмін-кабінеті Streamlit Dashboard завжди відображається блок квот (основний та резервні ключі The Odds API).
