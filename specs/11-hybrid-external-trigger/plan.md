# Технічний план реалізації SPEC-11: Гібридний зовнішній тригер

## 1. Архітектурна схема

```mermaid
flowchart LR
    subgraph ExternalServices[Зовнішні сервіси розкладу]
        CronJob["Cron-job.org / UptimeKuma<br>(Точний час по секундах)"]
        LocalCLI["Адміністратор / CLI<br>(python trigger_dispatch.py)"]
    end

    subgraph Gateway[Шлюз безпеки]
        Worker["Cloudflare Worker<br>(deploy/cloudflare_webhook.js)"]
    end

    subgraph GitHub[GitHub Infrastructure]
        GHAPI["GitHub REST API<br>/actions/workflows/scheduler.yml/dispatches"]
        Runner["GitHub Actions Runner<br>(main.py виконується)"]
    end

    CronJob -->|GET /?secret=***| Worker
    LocalCLI -->|Direct POST з GH_PAT| GHAPI
    Worker -->|POST workflow_dispatch| GHAPI
    GHAPI --> Runner
```

---

## 2. Формат запитів GitHub Actions API
* **Endpoint**:
  `https://api.github.com/repos/{OWNER}/{REPO}/actions/workflows/{WORKFLOW_ID}/dispatches`
* **Headers**:
  ```http
  Accept: application/vnd.github+json
  Authorization: Bearer <GITHUB_TOKEN>
  X-GitHub-Api-Version: 2022-11-28
  ```
* **Payload**:
  ```json
  {
    "ref": "main",
    "inputs": {
      "trigger_source": "external_webhook"
    }
  }
  ```
* **Очікувана відповідь**: `HTTP 204 No Content` (успішна постановка в чергу виконання).
