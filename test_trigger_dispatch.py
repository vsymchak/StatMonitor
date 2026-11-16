from trigger_dispatch import build_headers, build_dispatch_payload, generate_curl_command, trigger_workflow

def test_build_headers():
    h = build_headers("test_secret_token_123")
    assert h["Accept"] == "application/vnd.github+json"
    assert h["Authorization"] == "Bearer test_secret_token_123"
    assert h["X-GitHub-Api-Version"] == "2022-11-28"

def test_build_dispatch_payload():
    p = build_dispatch_payload(ref="feature/test", trigger_source="cron_job_org")
    assert p["ref"] == "feature/test"
    assert p["inputs"]["trigger_source"] == "cron_job_org"

def test_generate_curl_command():
    curl = generate_curl_command(repo="vsymchak/StatMonitor", workflow="scheduler.yml", token="my_token")
    assert "https://api.github.com/repos/vsymchak/StatMonitor/actions/workflows/scheduler.yml/dispatches" in curl
    assert "Bearer my_token" in curl
    assert '"trigger_source":"external_webhook"' in curl

def test_trigger_workflow_no_token():
    ok, code, msg = trigger_workflow(token="")
    assert ok is False
    assert code == 401
    assert "не вказано токен" in msg

if __name__ == "__main__":
    test_build_headers()
    test_build_dispatch_payload()
    test_generate_curl_command()
    test_trigger_workflow_no_token()
    print("Всі тести trigger_dispatch успішно пройдено!")
