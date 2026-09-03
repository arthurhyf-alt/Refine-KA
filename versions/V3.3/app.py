from __future__ import annotations

import http.server
import importlib
import json
import os
import pathlib
import socketserver
import sqlite3
import threading
import urllib.request
import webbrowser
from threading import Timer

ROOT = pathlib.Path(__file__).resolve().parent
HOST = "127.0.0.1"
PORT = 8771
PID_PATH = ROOT / "data" / "server.pid"
PIPELINE_LOCK = threading.Lock()


def run_pipeline_background():
    if not PIPELINE_LOCK.acquire(blocking=False):
        return
    try:
        import pipeline
        # Reload the collector so source/parser updates take effect without
        # leaving users on a stale background process.
        pipeline = importlib.reload(pipeline)
        pipeline.run_pipeline()
        try:
            import company_pipeline
            company_pipeline = importlib.reload(company_pipeline)
            company_pipeline.run_company_pipeline()
        except Exception as error:
            print(f"[企业候选池] 更新失败，保留最近结果：{error}")
    finally:
        PIPELINE_LOCK.release()


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def do_GET(self):
        if self.path == "/api/health":
            payload = json.dumps({"status": "ok", "version": "3.3.0"}).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/pipeline/status":
            from pipeline import latest_status
            status = latest_status()
            status["running"] = PIPELINE_LOCK.locked()
            self.send_json(status)
            return
        if self.path == "/api/pipeline/results":
            result_path = ROOT / "data" / "pipeline-results.json"
            payload = result_path.read_bytes() if result_path.exists() else b"[]"
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/export-analysis":
            result_path = ROOT / "data" / "export-analysis.json"
            payload = result_path.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path == "/api/sources":
            source_path = ROOT / "config" / "sources.json"
            sources = json.loads(source_path.read_text(encoding="utf-8"))
            db_path = ROOT / "data" / "pipeline.db"
            if db_path.exists():
                try:
                    conn = sqlite3.connect(db_path)
                    rows = conn.execute(
                        """SELECT DISTINCT source_id, source_name, url, region, dimension, source_grade
                           FROM documents WHERE source_id LIKE 'discovered-%' ORDER BY fetched_at DESC LIMIT 100"""
                    ).fetchall()
                    conn.close()
                    sources.extend({
                        "id": row[0], "name": row[1], "url": row[2], "region": row[3],
                        "dimension": row[4], "source_grade": row[5], "metric": "自动发现的网页证据",
                        "collection_mode": "auto_discovered", "enabled": True,
                    } for row in rows)
                except sqlite3.Error:
                    pass
            self.send_json(sources)
            return
        super().do_GET()

    def do_POST(self):
        if self.path == "/api/pipeline/run":
            if PIPELINE_LOCK.locked():
                self.send_json({"accepted": False, "message": "采集任务正在运行"}, status=409)
                return
            threading.Thread(target=run_pipeline_background, daemon=True).start()
            self.send_json({"accepted": True, "message": "采集任务已启动"}, status=202)
            return
        self.send_error(404)

    def send_json(self, value, status=200):
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt, *args):
        print("[产业筛查器]", fmt % args)


def open_browser():
    if os.environ.get("REFINE_KA_NO_BROWSER") == "1":
        return
    webbrowser.open(f"http://{HOST}:{PORT}")


def existing_server_is_ours():
    try:
        with urllib.request.urlopen(f"http://{HOST}:{PORT}/api/health", timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return payload.get("status") == "ok"
    except Exception:
        return False


if __name__ == "__main__":
    if existing_server_is_ours():
        open_browser()
        print(f"产业筛查器已经在运行： http://{HOST}:{PORT}")
        raise SystemExit(0)
    PID_PATH.parent.mkdir(exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="ascii")
    Timer(0.8, open_browser).start()
    try:
        with socketserver.TCPServer((HOST, PORT), Handler) as server:
            print(f"产业筛查器已启动：http://{HOST}:{PORT}")
            print("按 Ctrl+C 停止。")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                print("\n已停止。")
    finally:
        try:
            PID_PATH.unlink(missing_ok=True)
        except OSError:
            pass
