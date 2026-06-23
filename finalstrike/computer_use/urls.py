"""URL helpers for computer-use launch actions."""

from __future__ import annotations

from urllib.parse import urljoin, urlparse


_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def canonical_ui_url(*, base_url: str, smoke_route: str = "/") -> str:
    """Build the configured smoke URL from ``ui.base_url`` and ``ui.smoke_route``."""
    base = base_url.rstrip("/") + "/"
    route = smoke_route.lstrip("/")
    return urljoin(base, route)


def _endpoint_key(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        host = "loopback"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    return host, port


def validate_launch_url(url: str, *, ui_base_url: str) -> str:
    """Ensure ``url`` is an allowed http(s) launch target for this repo.

    Permits the configured ``ui.base_url`` origin (any path) and treats
  ``localhost`` / ``127.0.0.1`` as equivalent loopback hosts.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(
            f"launch URL must use http or https, got {parsed.scheme!r}: {url!r}"
        )
    if not parsed.netloc:
        raise ValueError(f"launch URL must include a host: {url!r}")

    if _endpoint_key(url) != _endpoint_key(ui_base_url):
        raise ValueError(
            f"launch URL {url!r} is outside configured ui.base_url {ui_base_url!r}"
        )
    return url
