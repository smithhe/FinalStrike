"""HTTP server: health check, task API, and static frontend."""

from __future__ import annotations

import json
import re
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

STATIC_ROOT = Path(__file__).resolve().parent.parent / "static"

_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*$")
_TASK_ID_RE = re.compile(r"^/api/tasks/(\d+)$")
_TASK_DETAIL_UI_RE = re.compile(r"^/tasks/(\d+)$")
_CORS_METHODS = "GET, POST, PATCH, DELETE, OPTIONS"
_STATIC_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".ico": "image/x-icon",
    ".svg": "image/svg+xml",
}

_tasks_lock = threading.Lock()
_tasks: list[dict[str, Any]] = []
_next_task_id = 1


def reset_tasks_for_testing() -> None:
    """Clear the in-memory task store (for tests only)."""
    global _next_task_id
    with _tasks_lock:
        _tasks.clear()
        _next_task_id = 1


def _safe_path_segments(url_path: str) -> list[str] | None:
    """Parse a URL path into safe static-file segments, or None if rejected."""
    path = unquote(urlparse(url_path).path)
    if path in {"", "/"}:
        return []

    relative = path.lstrip("/").rstrip("/")
    if not relative:
        return []

    segments = relative.split("/")
    if any(
        not segment or segment in {".", ".."} or not _SAFE_SEGMENT_RE.match(segment)
        for segment in segments
    ):
        return None
    return segments


def _file_if_under_root(candidate: Path) -> Path | None:
    if not candidate.is_file():
        return None
    try:
        candidate.resolve().relative_to(STATIC_ROOT.resolve())
    except ValueError:
        return None
    return candidate


def resolve_static_path(url_path: str) -> Path | None:
    """Map a URL path to a file under ``static/`` without path traversal."""
    segments = _safe_path_segments(url_path)
    if segments is None:
        return None

    if not segments:
        return _file_if_under_root(STATIC_ROOT / "index.html")

    direct = STATIC_ROOT.joinpath(*segments)
    resolved = _file_if_under_root(direct)
    if resolved is not None:
        return resolved

    index_candidate = STATIC_ROOT.joinpath(*segments, "index.html")
    return _file_if_under_root(index_candidate)


def _static_content_type(path: Path) -> str:
    """Return a fixed Content-Type for known static assets."""
    return _STATIC_CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: Any) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", _CORS_METHODS)
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(body)


def _empty_response(handler: BaseHTTPRequestHandler, status: int) -> None:
    handler.send_response(status)
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", _CORS_METHODS)
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()


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


def _parse_task_id(path: str) -> int | None:
    match = _TASK_ID_RE.match(path)
    if not match:
        return None
    return int(match.group(1))


def _get_task(task_id: int) -> dict[str, Any] | None:
    with _tasks_lock:
        for task in _tasks:
            if task["id"] == task_id:
                return dict(task)
    return None


def _update_task(task_id: int, *, completed: bool) -> dict[str, Any] | None:
    with _tasks_lock:
        for task in _tasks:
            if task["id"] == task_id:
                task["completed"] = completed
                return dict(task)
    return None


def _delete_task(task_id: int) -> bool:
    with _tasks_lock:
        for index, task in enumerate(_tasks):
            if task["id"] == task_id:
                _tasks.pop(index)
                return True
    return False


class HealthHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", _CORS_METHODS)
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

        task_id = _parse_task_id(path)
        if task_id is not None:
            task = _get_task(task_id)
            if task is None:
                _json_response(self, 404, {"error": "Task not found"})
            else:
                _json_response(self, 200, task)
            return

        if path == "/tasks":
            self.send_response(301)
            self.send_header("Location", "/tasks/")
            self.end_headers()
            return

        detail_match = _TASK_DETAIL_UI_RE.match(path)
        if detail_match is not None:
            detail_page = STATIC_ROOT / "tasks" / "detail.html"
            if not detail_page.is_file():
                self.send_response(404)
                self.end_headers()
                return
            body = detail_page.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", _static_content_type(detail_page))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        static_path = resolve_static_path(path)
        if static_path is None:
            self.send_response(404)
            self.end_headers()
            return

        body = static_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", _static_content_type(static_path))
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

    def do_PATCH(self) -> None:
        path = urlparse(self.path).path
        task_id = _parse_task_id(path)
        if task_id is None:
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

        if "completed" not in body:
            _json_response(self, 400, {"error": "completed is required"})
            return

        completed = body["completed"]
        if not isinstance(completed, bool):
            _json_response(self, 400, {"error": "completed must be a boolean"})
            return

        updated = _update_task(task_id, completed=completed)
        if updated is None:
            _json_response(self, 404, {"error": "Task not found"})
            return

        _json_response(self, 200, updated)

    def do_DELETE(self) -> None:
        path = urlparse(self.path).path
        task_id = _parse_task_id(path)
        if task_id is None:
            self.send_response(404)
            self.end_headers()
            return

        if not _delete_task(task_id):
            _json_response(self, 404, {"error": "Task not found"})
            return

        _empty_response(self, 204)

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
    print(f"  UI detail: http://localhost:{port}/tasks/<id>", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
