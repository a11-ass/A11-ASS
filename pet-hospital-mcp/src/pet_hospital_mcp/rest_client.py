"""Async REST client wrapping the Go pet hospital backend.

Responsibilities:

* Map :class:`ToolError`/network failures to the right :class:`ErrorCode`.
* Retry a bounded number of times for transient failures.
* Surface the Go ``data`` envelope (``items``/``total``/...) untouched on
  success — validation against the Pydantic model happens in the tool layer.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .config import Settings, settings as default_settings
from .errors import ErrorCode, ToolError


class RestApiClient:
    """Thin httpx wrapper with timeout, retry and error translation.

    The underlying ``httpx.AsyncClient`` is bound to the event loop that was
    running when it was created. If a long-lived ``RestApiClient`` instance
    (e.g. the module-level :data:`default_client`) is reused across requests
    served by different loops — which happens whenever the MCP SDK restarts
    its session task group between stateless calls — the stale client raises
    ``RuntimeError: ... attached to a different loop``. ``_ensure_client``
    detects that drift, closes the old client silently, and rebuilds one bound
    to the current loop.
    """

    def __init__(self, config: Settings | None = None) -> None:
        self._config = config or default_settings
        self._client: httpx.AsyncClient | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    async def __aenter__(self) -> "RestApiClient":
        await self._ensure_client()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _ensure_client(self) -> httpx.AsyncClient:
        current_loop = asyncio.get_running_loop()
        # Reuse rules:
        #   * _client is None              -> build a fresh one
        #   * _loop is None                -> externally injected client (tests);
        #                                     trust it and reuse as-is
        #   * _loop is current_loop        -> same loop, reuse
        #   * _loop is not current_loop    -> loop drifted (stateless MCP across
        #                                     lifespans); close + rebuild
        if self._client is not None and (
            self._loop is None or self._loop is current_loop
        ):
            return self._client

        if self._client is not None:
            # Previous client is bound to a now-closed loop. Best-effort close
            # — if that loop is gone, aclose() itself raises RuntimeError,
            # which we swallow since we're about to replace it.
            try:
                await self._client.aclose()
            except (RuntimeError, Exception):
                pass
            self._client = None
            self._loop = None

        self._client = httpx.AsyncClient(
            base_url=self._config.pet_hospital_base_url,
            timeout=httpx.Timeout(self._config.backend_timeout_seconds),
        )
        self._loop = current_loop
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except (RuntimeError, Exception):
                # Same defensive guard — closing a client bound to a dead loop.
                pass
            self._client = None
            self._loop = None

    async def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue ``GET path`` and return the parsed JSON body.

        Raises :class:`ToolError` for every failure mode — network timeouts,
        unreachable backend, non-2xx responses, and invalid JSON bodies.
        """
        client = await self._ensure_client()

        last_exc: Exception | None = None
        attempts = max(1, self._config.backend_retries + 1)
        for attempt in range(attempts):
            try:
                response = await client.get(path, params=params)
                # 5xx is treated as transient → retry
                if 500 <= response.status_code < 600 and attempt < attempts - 1:
                    last_exc = ToolError(
                        ErrorCode.BACKEND_API_ERROR,
                        f"backend returned HTTP {response.status_code}",
                        details={"status_code": response.status_code},
                    )
                    await self._backoff(attempt)
                    continue
                return self._handle_response(response)
            except httpx.TimeoutException as exc:
                last_exc = ToolError(
                    ErrorCode.BACKEND_TIMEOUT,
                    "backend request timed out",
                    details={"path": path, "attempt": attempt + 1},
                )
            except httpx.ConnectError as exc:
                last_exc = ToolError(
                    ErrorCode.BACKEND_UNAVAILABLE,
                    "backend service unavailable",
                    details={"path": path, "attempt": attempt + 1},
                )
            except httpx.HTTPError as exc:
                last_exc = ToolError(
                    ErrorCode.BACKEND_API_ERROR,
                    f"http transport error: {exc.__class__.__name__}",
                    details={"path": path, "attempt": attempt + 1},
                )

            if attempt < attempts - 1:
                await self._backoff(attempt)

        # All retries exhausted — re-raise the last structured error.
        assert last_exc is not None
        raise last_exc

    async def _backoff(self, attempt: int) -> None:
        import asyncio

        await asyncio.sleep(self._config.backend_backoff_seconds * (attempt + 1))

    def _handle_response(self, response: httpx.Response) -> Any:
        """Validate a successful httpx.Response and return the body JSON."""
        if response.status_code >= 400:
            raise ToolError(
                ErrorCode.BACKEND_API_ERROR,
                f"backend returned HTTP {response.status_code}",
                details={
                    "status_code": response.status_code,
                    "body": response.text[:500],
                },
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise ToolError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "backend returned non-JSON response",
                details={"body": response.text[:500]},
            ) from exc

        if not isinstance(body, dict):
            raise ToolError(
                ErrorCode.BACKEND_INVALID_RESPONSE,
                "backend response is not a JSON object",
                details={"body_type": type(body).__name__},
            )

        data = body.get("data")
        if data is None:
            # Go API returns ``data: null`` only on failure envelopes — surface it.
            message = body.get("message") or "backend returned null data"
            raise ToolError(
                ErrorCode.BACKEND_API_ERROR,
                str(message),
                details={"code": body.get("code")},
            )

        return data


# Module-level singleton reused by tools. Tests inject their own client.
default_client = RestApiClient()
