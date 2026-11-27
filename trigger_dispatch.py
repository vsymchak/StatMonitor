import os
import sys
import argparse
import requests

DEFAULT_REPO = os.environ.get("GH_REPO", "vsymchak/StatMonitor")
DEFAULT_WORKFLOW = os.environ.get("GH_WORKFLOW", "scheduler.yml")
DEFAULT_TOKEN = os.environ.get("GH_PAT") or os.environ.get("GITHUB_TOKEN")
WEBHOOK_URL = os.environ.get("TRIGGER_WEBHOOK_URL", "https://statmonitor.symchak.workers.dev")


def trigger_via_webhook(secret=None, source="telegram_bot", url=None):
    """Викликає HTTP-вебхук (Cloudflare Worker або Oracle/Render /trigger)."""
    sec = (secret or os.environ.get("SECRET_KEY") or "").strip()
    target_url = (url or WEBHOOK_URL).strip()
    if not sec:
        return False, "Не задано SECRET_KEY у змінних середовища."
    try:
        r = requests.get(target_url, params={"secret": sec, "source": source}, timeout=12)
        if r.status_code in (200, 202, 204):
            return True, f"OK ({r.status_code})"
        return False, f"HTTP {r.status_code}: {r.text[:150]}"
    except Exception as e:
        return False, str(e)

def build_headers(token):
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers

def build_dispatch_payload(ref="main", trigger_source="manual"):
    return {
        "ref": ref,
        "inputs": {
            "trigger_source": trigger_source,
        },
    }

def trigger_workflow(repo=DEFAULT_REPO, workflow=DEFAULT_WORKFLOW, token=None, ref="main", trigger_source="manual"):
    """
    Надсилає запит до GitHub API для запуску workflow_dispatch.
    Повертає кортеж: (success: bool, status_code: int, message: str)
    """
    token = token or DEFAULT_TOKEN
    if not token:
        return False, 401, "Помилка: не вказано токен GitHub (GH_PAT або GITHUB_TOKEN)."

    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches"
    headers = build_headers(token)
    payload = build_dispatch_payload(ref=ref, trigger_source=trigger_source)

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=15)
        if r.status_code == 204:
            return True, 204, f"Успішно! Воркфлоу {workflow} поставлено в чергу на гілці {ref} (джерело: {trigger_source})."
        return False, r.status_code, f"GitHub API помилка ({r.status_code}): {r.text[:200]}"
    except Exception as e:
        return False, 500, f"Мережева помилка: {e}"

def get_workflow_status(repo=DEFAULT_REPO, workflow=DEFAULT_WORKFLOW, token=None, limit=3):
    """
    Отримує статус останніх запусків воркфлоу.
    """
    token = token or DEFAULT_TOKEN
    url = f"https://api.github.com/repos/{repo}/actions/workflows/{workflow}/runs?per_page={limit}"
    headers = build_headers(token)

    try:
        r = requests.get(url, headers=headers, timeout=15)
        if r.status_code == 200:
            runs = r.json().get("workflow_runs", [])
            results = []
            for run in runs:
                results.append({
                    "id": run.get("id"),
                    "name": run.get("name"),
                    "status": run.get("status"),
                    "conclusion": run.get("conclusion") or "running",
                    "created_at": run.get("created_at"),
                    "url": run.get("html_url"),
                    "event": run.get("event"),
                })
            return True, results
        return False, f"Помилка отримання статусу ({r.status_code}): {r.text[:150]}"
    except Exception as e:
        return False, f"Помилка: {e}"

def generate_curl_command(repo=DEFAULT_REPO, workflow=DEFAULT_WORKFLOW, token="<YOUR_GITHUB_TOKEN>"):
    """
    Генерує готову команду cURL для налаштування зовнішніх планувальників (Cron-job.org / Webhook).
    """
    return (
        f'curl -X POST \\\n'
        f'  -H "Accept: application/vnd.github+json" \\\n'
        f'  -H "Authorization: Bearer {token}" \\\n'
        f'  -H "X-GitHub-Api-Version: 2022-11-28" \\\n'
        f'  https://api.github.com/repos/{repo}/actions/workflows/{workflow}/dispatches \\\n'
        f'  -d \'{{"ref":"main","inputs":{{"trigger_source":"external_webhook"}}}}\''
    )

def main():
    parser = argparse.ArgumentParser(description="Керування запуском GitHub Actions StatMonitor через API")
    parser.add_argument("--trigger", "-t", action="store_true", help="Запустити воркфлоу негайно")
    parser.add_argument("--status", "-s", action="store_true", help="Отримати статус останніх запусків")
    parser.add_argument("--curl", "-c", action="store_true", help="Показати curl-команду для налаштування Cron-job.org")
    parser.add_argument("--source", default="manual", help="Ідентифікатор джерела запуску (manual, cron_job, watchdog)")
    parser.add_argument("--ref", default="main", help="Гілка репозиторію (default: main)")
    parser.add_argument("--token", help="GitHub Personal Access Token (якщо не задано в env)")
    args = parser.parse_args()

    token = args.token or DEFAULT_TOKEN

    if args.curl:
        print("Готова команда cURL для зовнішнього сервісу:\n")
        print(generate_curl_command(token=token or "<YOUR_GITHUB_TOKEN>"))
        return

    if args.status:
        print(f"Перевірка останніх запусків для {DEFAULT_REPO} ({DEFAULT_WORKFLOW})...\n")
        ok, data = get_workflow_status(token=token)
        if ok:
            for run in data:
                print(f"• Run #{run['id']}: [{run['status']}] / [{run['conclusion']}]")
                print(f"  Час: {run['created_at']} | Подія: {run['event']}")
                print(f"  Посилання: {run['url']}\n")
        else:
            print("Помилка:", data)
        return

    if args.trigger:
        print(f"Відправка тригеру для {DEFAULT_REPO} (гілка {args.ref}, джерело: {args.source})...")
        ok, code, msg = trigger_workflow(token=token, ref=args.ref, trigger_source=args.source)
        print(f"[{code}] {msg}")
        return

    parser.print_help()

if __name__ == "__main__":
    main()
