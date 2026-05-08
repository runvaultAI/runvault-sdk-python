from __future__ import annotations

import json

import httpx


def make_httpx_response(
    status_code: int,
    body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Build a real httpx.Response for use in interceptor tests."""
    content = json.dumps(body).encode() if body is not None else b""
    h = {"content-type": "application/json"}
    if headers:
        h.update({k.lower(): v for k, v in headers.items()})
    return httpx.Response(status_code=status_code, content=content, headers=h)
