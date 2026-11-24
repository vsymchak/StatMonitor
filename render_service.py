"""
Render.com Web Service Adapter для StatMonitor
Забезпечує відповідність вимогам безкоштовного тарифу Render Web Service:
- Слухає HTTP-порт $PORT для проходження перевірки працездатності (Health Check).
- У фоні запускає безперервного демона StatMonitor (кожні 30 хв).
- Дозволяє викликати миттєве оновлення через GET /trigger.
"""

import os
import sys
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from daemon import run_daemon, load_dotenv_fallback

load_dotenv_fallback()

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/healthz"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"StatMonitor 24/7 Web Service is ACTIVE.\n")
        elif self.path.startswith("/trigger") or self.path.startswith("/run"):
            # Миттєвий запуск через вебхук
            try:
                from main import run_pipeline
                t = threading.Thread(target=run_pipeline, kwargs={"force": True})
                t.start()
                self.send_response(200)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Pipeline triggered successfully.\n")
            except Exception as e:
                self.send_response(500)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(f"Trigger error: {e}\n".encode("utf-8"))
        else:
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
