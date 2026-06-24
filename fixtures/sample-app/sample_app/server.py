"""HTTP server: health check, task API, and static frontend."""

from __future__ import annotations

import json
import mimetypes
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"

_tasks_lock = threading.Lock()
_tasks: list[dict[str, Any]] = []
_next_task_id = 1


def reset_tasks_for_testing() -> None:
    """Clear the in-memory task store (for tests only)."""
    global _next_task_id
    with _tasks_lock:
        _tasks.clear()
        _next_task_id = 1


def resolve_static_path(url_path: str) -> Path | None:
    """Map a URL path to a file under ``static/``."""
    path = url_path.split("?", 1)[0]
    if path in {"", "/"}:
        candidate = STATIC_ROOT / "index.html"
        return candidate if candidate.is_file() else None

    relative = path.lstrip("/")
    direct = STATIC_ROOT / relative
    if direct.is_file():
        return direct

    directory = relative.rstrip("/")
    index_candidate = STATIC_ROOT / directory / "index.html"
    if index_candidate.is_file():
        return index_candidate

    return None


def _path_is_under_root(candidate: Path, root: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _read_json_body(handler: BaseHTTPRequestHandler) -> Any:
    length = int(handler.headers.get("Content-Length", "0"))
    if length <= 0:
        return None
    raw = handler.rfile.read(length)
    if not raw:
        return None
    return json.loads(raw.decode("utf-8"))


def _create_task(title: str, description: str | None = None) -> dict[str, Any]:
    global _next_task_id
    with _tasks_lock:
        task = {
            "id": _next_task_id,
            "title": title,
            "description": description or "",
            "completed": False,
        }
        _next_task_id += 1
        _tasks.append(task)
        return dict(task)


def _list_tasks() -> list[dict[str, Any]]:
    with _tasks_lock:
        return [dict(task) for task in _tasks]


class HealthHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(b"ok")
            return
        if path == "/api/tasks":
            _json_response(self, 200, _list_tasks())
            return

        if path == "/tasks":
            self.send_response(301)
            self.send_header("Location", "/tasks/")
            self.end_headers()
            return

        static_path = resolve_static_path(path)
        if static_path is None or not _path_is_under_root(static_path, STATIC_ROOT):
            self.send_response(404)
            self.end_headers()
            return

        content_type, _ = mimetypes.guess_type(str(static_path))
        body = static_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path != "/api/tasks":
            self.send_response(404)
            self.end_headers()
            return

        try:
            body = _read_json_body(self)
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "Invalid JSON body"})
            return

        if not isinstance(body, dict):
            _json_response(self, 400, {"error": "JSON object required"})
            return

        title = body.get("title")
        if title is None or (isinstance(title, str) and not title.strip()):
            _json_response(self, 400, {"error": "title is required"})
            return

        if not isinstance(title, str):
            _json_response(self, 400, {"error": "title must be a string"})
            return

        description = body.get("description")
        if description is not None and not isinstance(description, str):
            _json_response(self, 400, {"error": "description must be a string"})
            return

        task = _create_task(title.strip(), description)
        _json_response(self, 201, task)

    def log_message(self, format: str, *args: object) -> None:
        return


def main() -> None:
    required_static = [
        STATIC_ROOT / "index.html",
        STATIC_ROOT / "tasks" / "index.html",
    ]
    missing = [path for path in required_static if not path.is_file()]
    if missing:
        print(
            "sample-app server cannot start: missing static frontend files:",
            file=sys.stderr,
        )
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        print(
            "\nPull the latest cursor/sample-app-task-list branch. "
            "The unified server requires static/tasks/index.html.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    print(
        f"sample-app listening on http://localhost:{port} "
        f"(API + static frontend)",
        flush=True,
    )
    print(f"  UI home:  http://localhost:{port}/", flush=True)
    print(f"  UI tasks: http://localhost:{port}/tasks/", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
