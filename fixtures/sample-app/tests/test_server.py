"""Tests for sample_app.server HTTP endpoints."""

from __future__ import annotations

import json
import socket
import threading
from http.server import HTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from sample_app.server import HealthHandler, resolve_static_path, reset_tasks_for_testing


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def api_server():
    reset_tasks_for_testing()
    port = _free_port()
    server = HTTPServer(("127.0.0.1", port), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        yield base_url
    finally:
        server.shutdown()
        thread.join(timeout=2)


def _get(url: str) -> tuple[int, bytes]:
    with urlopen(url) as response:
        return response.status, response.read()


def _post_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        return exc.code, data


def _patch_json(url: str, payload: dict) -> tuple[int, dict]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="PATCH",
    )
    try:
        with urlopen(request) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8")
        data = json.loads(raw) if raw else {}
        return exc.code, data


def _delete(url: str) -> int:
    request = Request(url, method="DELETE")
    try:
        with urlopen(request) as response:
            return response.status
    except HTTPError as exc:
        return exc.code


def _options(url: str) -> tuple[int, dict[str, str]]:
    request = Request(url, method="OPTIONS")
    with urlopen(request) as response:
        headers = {key.lower(): value for key, value in response.headers.items()}
        return response.status, headers


def test_health_endpoint(api_server: str) -> None:
    status, body = _get(f"{api_server}/health")
    assert status == 200
    assert body == b"ok"


def test_serves_landing_page(api_server: str) -> None:
    status, body = _get(f"{api_server}/")
    assert status == 200
    assert b"Sample App" in body


def test_serves_tasks_page(api_server: str) -> None:
    status, body = _get(f"{api_server}/tasks/")
    assert status == 200
    assert b"Sample App - Tasks" in body
    assert b"New Task" in body
    assert b"Load Demo Tasks" in body
    assert b"Confirm Delete" in body
    assert b"Search tasks" in body
    assert b"Import Tasks" in body
    assert b"Confirm Import" in body


def test_serves_settings_page(api_server: str) -> None:
    status, body = _get(f"{api_server}/settings/")
    assert status == 200
    assert b"Sample App - Settings" in body
    assert b"Save Settings" in body
    assert b"Default sort order" in body


def test_tasks_path_redirects_to_trailing_slash(api_server: str) -> None:
    request = Request(f"{api_server}/tasks", method="GET")
    with urlopen(request) as response:
        assert response.status == 200
        assert response.url.endswith("/tasks/")


def test_post_task_success(api_server: str) -> None:
    status, task = _post_json(
        f"{api_server}/api/tasks",
        {"title": "Buy milk", "description": "2% organic"},
    )
    assert status == 201
    assert task["title"] == "Buy milk"
    assert task["description"] == "2% organic"
    assert task["id"] == 1
    assert task["completed"] is False


def test_post_without_title_fails(api_server: str) -> None:
    status, body = _post_json(f"{api_server}/api/tasks", {"description": "no title"})
    assert status == 400
    assert "title" in body["error"].lower()


def test_get_tasks_lists_created_tasks(api_server: str) -> None:
    _post_json(f"{api_server}/api/tasks", {"title": "First task"})
    _post_json(f"{api_server}/api/tasks", {"title": "Second task"})

    status, raw = _get(f"{api_server}/api/tasks")
    tasks = json.loads(raw.decode("utf-8"))
    assert status == 200
    assert len(tasks) == 2
    assert [task["title"] for task in tasks] == ["First task", "Second task"]


def test_cors_preflight_allows_post(api_server: str) -> None:
    status, headers = _options(f"{api_server}/api/tasks")
    assert status == 204
    assert headers.get("access-control-allow-origin") == "*"
    assert "POST" in headers.get("access-control-allow-methods", "")

    post_status, task = _post_json(
        f"{api_server}/api/tasks",
        {"title": "CORS task", "description": "via preflight"},
    )
    assert post_status == 201
    assert task["title"] == "CORS task"


@pytest.mark.parametrize(
    "path",
    [
        "/../etc/passwd",
        "/tasks/../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
        "/tasks/..%2f..%2fetc/passwd",
        "/tasks/%2e%2e/secret",
    ],
)
def test_static_path_traversal_rejected(api_server: str, path: str) -> None:
    with pytest.raises(HTTPError) as exc_info:
        _get(f"{api_server}{path}")
    assert exc_info.value.code == 404


@pytest.mark.parametrize(
    "path",
    [
        "/../etc/passwd",
        "/tasks/../../etc/passwd",
        "/%2e%2e/%2e%2e/etc/passwd",
    ],
)
def test_resolve_static_path_rejects_unsafe_paths(path: str) -> None:
    assert resolve_static_path(path) is None


def test_patch_task_completed(api_server: str) -> None:
    _, task = _post_json(f"{api_server}/api/tasks", {"title": "Toggle me"})
    status, updated = _patch_json(
        f"{api_server}/api/tasks/{task['id']}",
        {"completed": True},
    )
    assert status == 200
    assert updated["completed"] is True

    status, updated = _patch_json(
        f"{api_server}/api/tasks/{task['id']}",
        {"completed": False},
    )
    assert status == 200
    assert updated["completed"] is False


def test_patch_missing_task_returns_404(api_server: str) -> None:
    status, body = _patch_json(
        f"{api_server}/api/tasks/999",
        {"completed": True},
    )
    assert status == 404
    assert "not found" in body["error"].lower()


def test_patch_requires_completed_field(api_server: str) -> None:
    _, task = _post_json(f"{api_server}/api/tasks", {"title": "Needs completed"})
    status, body = _patch_json(f"{api_server}/api/tasks/{task['id']}", {})
    assert status == 400
    assert "completed" in body["error"].lower()


def test_delete_task(api_server: str) -> None:
    _, task = _post_json(f"{api_server}/api/tasks", {"title": "Delete me"})
    status = _delete(f"{api_server}/api/tasks/{task['id']}")
    assert status == 204

    list_status, raw = _get(f"{api_server}/api/tasks")
    tasks = json.loads(raw.decode("utf-8"))
    assert list_status == 200
    assert tasks == []


def test_delete_missing_task_returns_404(api_server: str) -> None:
    status = _delete(f"{api_server}/api/tasks/999")
    assert status == 404


def test_get_task_by_id(api_server: str) -> None:
    _, created = _post_json(f"{api_server}/api/tasks", {"title": "Detail me", "description": "Full text"})
    status, raw = _get(f"{api_server}/api/tasks/{created['id']}")
    task = json.loads(raw.decode("utf-8"))
    assert status == 200
    assert task["title"] == "Detail me"
    assert task["description"] == "Full text"


def test_get_missing_task_returns_404(api_server: str) -> None:
    with pytest.raises(HTTPError) as exc_info:
        _get(f"{api_server}/api/tasks/999")
    assert exc_info.value.code == 404


def test_serves_task_detail_page(api_server: str) -> None:
    _, created = _post_json(f"{api_server}/api/tasks", {"title": "View me", "description": "Body"})
    status, body = _get(f"{api_server}/tasks/{created['id']}")
    assert status == 200
    assert b"Sample App - Task Detail" in body
    assert b"task-detail-description" in body
    assert b"Back to Tasks" in body


def test_home_dashboard_markup(api_server: str) -> None:
    status, body = _get(f"{api_server}/")
    assert status == 200
    assert b"task-dashboard" in body
    assert b"stat-total" in body
    assert b"stat-active" in body
    assert b"stat-done" in body
    assert b"recent-tasks-list" in body
