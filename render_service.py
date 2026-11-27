"""
Render.com Web Service Adapter для StatMonitor
Забезпечує відповідність вимогам безкоштовного тарифу Render Web Service:
- Слухає HTTP-порт $PORT для проходження перевірки працездатності (Health Check).
- У фоні запускає безперервного демона StatMonitor (кожні 30 хв).
- Дозволяє викликати миттєве оновлення через GET /trigger.
"""

import os
import hmac
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
from daemon import run_daemon, load_dotenv_fallback

load_dotenv_fallback()

PIPELINE_LOCK = threading.Lock()
TRIGGER_SECRET = (os.environ.get("SECRET_KEY") or "").strip()


def _run_pipeline_guarded(force: bool = True):
    if not PIPELINE_LOCK.acquire(blocking=False):
        print("⚠️ [Trigger] Пайплайн уже виконується — повторний виклик пропущено.")
        return
    try:
        from main import run_pipeline
        run_pipeline(force=force)
    finally:
        PIPELINE_LOCK.release()


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            state = "RUNNING" if PIPELINE_LOCK.locked() else "IDLE"
            self.wfile.write(f"StatMonitor 24/7 Web Service is ACTIVE ({state}).\n".encode("utf-8"))
            return

        if path in ("/trigger", "/run"):
            qs = parse_qs(parsed.query)
            req_secret = (qs.get("secret", [""])[0] or self.headers.get("X-Trigger-Secret", "")).strip()
            expected_secret = (os.environ.get("SECRET_KEY") or TRIGGER_SECRET or "").strip()
            if not expected_secret or not req_secret or not hmac.compare_digest(req_secret, expected_secret):
                self.send_response(401)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Unauthorized: invalid secret.\n")
                return

            if PIPELINE_LOCK.locked():
                self.send_response(409)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Pipeline is already running.\n")
                return

            try:
                t = threading.Thread(target=_run_pipeline_guarded, kwargs={"force": True}, daemon=True)
                t.start()
                self.send_response(202)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Pipeline triggered successfully.\n")
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Trigger error: {e}\n".encode("utf-8"))
            return

        self.send_response(404)
        self.end_headers()

    def log_message(self, format, *args):
        # Приглушуємо логування звичайних пінґів
        pass

def start_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"🌐 [Render] HTTP Health Server запущено на порту {port}")
    server.serve_forever()

if __name__ == "__main__":
    # 1. Запускаємо HTTP сервер у фоні для Render
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()

    # 2. Запускаємо основний безперервний цикл моніторингу
    interval = int(os.environ.get("POLL_INTERVAL", 30))
    run_daemon(interval_minutes=interval)
