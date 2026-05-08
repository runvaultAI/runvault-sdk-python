"""RunVaultProviderTransport — scoped httpx transport for LLM provider routing.

Replaces the global httpx monkey-patch (interceptor.py).  Each LLM client
built by a factory in runvault.llm.* receives its own httpx.Client whose transport
is one of these classes.  Nothing outside those clients is affected.

At request time the transport:
  1. Reads the active Agent from the _current_agent ContextVar.
  2. Replaces the PLACEHOLDER_BASE URL with the real proxy URL.
  3. Mints a fresh per-request EdDSA JWT signed with the agent's private key
     and injects the PKI headers (X-RV-Certificate + X-RV-Agent-JWT). The
     legacy Bearer-token path was removed in v0.2.0.
  4. Forwards the rewritten request to the real network.
  5. On 401 CERTIFICATE_REVOKED, refreshes credentials and retries once.
  6. On any other 4xx/5xx, reads the body and raises a typed RunVaultError.

The proxy URL is read from the active Agent, which captures it once at
registration time.  It is fixed for the lifetime of that Agent — changing
RUNVAULT_PROXY_URL after construction has no effect on existing agents.
"""

from __future__ import annotations

import httpx

from runvault.exceptions import (
    BudgetExceededError,
    LLMProviderError,
    ProxyError,
    TokenExpiredError,
)

# Placeholder inserted by LLM factories at construction time.
# Replaced at request time with the real proxy URL from the active Agent.
PLACEHOLDER_BASE = "http://runvault.internal"

# Per-client timeout defaults.
# Read is None because LLM streams can run for minutes.
DEFAULT_TIMEOUT = httpx.Timeout(connect=10.0, read=None, write=10.0, pool=10.0)


# ---------------------------------------------------------------------------
# Error helpers (same classification logic as the old interceptor.py)
# ---------------------------------------------------------------------------

def _parse_proxy_error(
    response: httpx.Response,
) -> tuple[str | None, str | None, str | None]:
    """Try to parse a RunVault proxy error body.

    Returns (error_code, user_string, internal_detail).
    All three are None when the body is not a RunVault-structured error.
    """
    try:
        body = response.json()
        if "code" in body:
            return body.get("code"), body.get("user_string", ""), body.get("detail", "")
        inner = body.get("detail", {})
        if isinstance(inner, dict) and "code" in inner:
            return inner.get("code"), inner.get("user_string", ""), inner.get("detail", "")
    except Exception:
        pass
    return None, None, None


def _extract_llm_error(response: httpx.Response, provider: str) -> str:
    """Extract a readable error message from an LLM provider error body."""
    try:
        body = response.json()
        error = body.get("error", {})
        if isinstance(error, dict):
            msg = error.get("message", "")
            if msg:
                return msg
        msg = body.get("message", "") or body.get("detail", "")
        if msg:
            return str(msg)
    except Exception:
        pass
    return f"{provider} returned HTTP {response.status_code}"


def _raise_for_error(response: httpx.Response, provider: str) -> None:
    """Raise a typed RunVaultError for any 4xx/5xx response.

    Checks the X-RunVault-Code header first (set by the proxy when it
    denies a request but forwards a provider-native body format), then
    falls back to parsing the RunVault error envelope, then treats the
    response as a plain LLM provider error.
    """
    status = response.status_code

    rv_code = response.headers.get("x-runvault-code")
    if rv_code == "BUDGET_CAP_REACHED":
        msg = _extract_llm_error(response, provider)
        raise BudgetExceededError(
            msg,
            status_code=status,
            error_code="BUDGET_CAP_REACHED",
            user_string="This agent has reached its spending limit.",
        )

    error_code, user_string, detail = _parse_proxy_error(response)

    if error_code:
        if status == 402 or error_code == "BUDGET_CAP_REACHED":
            raise BudgetExceededError(
                detail or "Budget cap reached.",
                status_code=status,
                error_code=error_code,
                user_string=user_string or "Agent has exceeded its spending budget.",
            )
        if status == 401 or error_code in ("INVALID_TOKEN", "TOKEN_EXPIRED", "JWT_EXPIRED"):
            raise TokenExpiredError(
                detail or "Token expired or invalid.",
                status_code=status,
                error_code=error_code,
                user_string=user_string or "RunVault session expired. Re-run runvault.init() to get a new token.",
            )
        if status == 503 or error_code == "PROXY_VERSION_MISMATCH":
            raise ProxyError(
                detail or "Proxy version mismatch.",
                status_code=status,
                error_code=error_code,
                user_string=user_string or "RunVault proxy is unavailable. Contact your administrator.",
            )
        raise ProxyError(
            detail or f"Proxy error (HTTP {status}).",
            status_code=status,
            error_code=error_code,
            user_string=user_string or f"RunVault proxy returned an error (HTTP {status}).",
        )

    message = _extract_llm_error(response, provider)
    raise LLMProviderError(
        message,
        provider=provider,
        status_code=status,
        error_code=f"{provider.upper()}_ERROR",
        user_string=message,
    )


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------

def _rewrite_request(
    request: httpx.Request,
    proxy_base: str,
    provider: str,
    agent_jwt: str,
    certificate_b64: str,
) -> httpx.Request:
    """Return a new request with the placeholder URL replaced and PKI headers injected.

    Every request to the proxy must carry both:
        X-RV-Certificate  base64-encoded RunVault certificate — CA-signed proof that
                          this agent is registered in RunVault.
        X-RV-Agent-JWT    EdDSA-signed short-lived JWT — run-specific claims
                          (agent_id, run_id, jti, exp) signed with the agent's private key.

    The proxy verifies the CA signature on the certificate, then verifies the
    agent JWT using the public key embedded in that certificate. No backend
    JWT or API key is sent — the certificate and agent JWT are the only auth.
    """
    new_url = str(request.url).replace(PLACEHOLDER_BASE, proxy_base.rstrip("/"), 1)

    headers = dict(request.headers)
    headers.pop("authorization", None)
    headers.pop("x-goog-api-key", None)
    headers["x-rv-certificate"] = certificate_b64
    headers["x-rv-agent-jwt"] = agent_jwt

    return httpx.Request(
        method=request.method,
        url=new_url,
        headers=headers,
        stream=request.stream,
    )


def _is_cert_revoked_response(response: httpx.Response) -> bool:
    """Return True if the response is a proxy 401 with code=CERTIFICATE_REVOKED.

    Used to decide whether the transport should attempt a one-shot
    credential refresh + retry. Any other 4xx/5xx propagates as a normal
    error via ``_raise_for_error``.
    """
    if response.status_code != 401:
        return False
    error_code, _, _ = _parse_proxy_error(response)
    return error_code == "CERTIFICATE_REVOKED"


def _build_signed_request(
    request: httpx.Request,
    agent,  # sdk.runtime.agent.Agent — typed loosely to avoid circular import
    provider: str,
) -> httpx.Request:
    """Mint a fresh per-request EdDSA JWT + rewrite URL/headers for the proxy.

    Helper used twice on the retry path: once for the initial send, and once
    after ``agent.refresh_credentials()`` if the proxy reported the cert was
    revoked. Both calls read the agent's current credentials at the moment
    they're made — ensuring the second call uses the freshly-minted ones.
    """
    from runvault.auth.signer import create_agent_jwt

    if agent.private_key_bytes is None or agent.certificate_b64 is None:
        raise RuntimeError(
            "Agent is missing PKI credentials. Ensure the agent registered "
            "successfully and RV_CA_PUBLIC_KEY is set."
        )

    agent_jwt = create_agent_jwt(
        agent_id=str(agent.info.id),
        run_id=str(agent.info.run_id),
        private_key_bytes=agent.private_key_bytes,
    )

    return _rewrite_request(
        request,
        proxy_base=agent.info.proxy_url,
        provider=provider,
        agent_jwt=agent_jwt,
        certificate_b64=agent.certificate_b64,
    )


class RunVaultProviderTransport(httpx.BaseTransport):
    """Sync httpx transport that routes requests through the RunVault proxy.

    One instance is created per LLM client. The active Agent is looked
    up from the ContextVar at request time — never stored on the transport.

    Credential refresh on 401 CERTIFICATE_REVOKED
    ─────────────────────────────────────────────
    When an admin rotates an agent's certificate (scope change or explicit
    revoke), the proxy's revocation cache picks up the change within ≤30 s
    and starts returning 401 CERTIFICATE_REVOKED to in-flight requests. To
    keep the agent running transparently, this transport detects that
    specific 4xx, calls ``agent.refresh_credentials()`` to mint fresh
    creds, and retries the request ONCE with the new JWT/cert.

    Limitations of the retry:
      - One retry only. If the second attempt also fails, the error
        propagates normally — no retry storm.
      - If the agent has been administratively suspended,
        ``agent.refresh_credentials()`` raises ``AgentSuspendedError``;
        the transport propagates it without retrying.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._inner = httpx.HTTPTransport(verify=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from runvault.context import _current_agent

        agent = _current_agent.get(None)
        if agent is None:
            raise RuntimeError(
                f"No active RunVault agent. Call runvault.init(...) before "
                f"invoking this {self.provider} LLM client."
            )

        rewritten = _build_signed_request(request, agent, self.provider)
        response = self._inner.handle_request(rewritten)

        # Cert-revoked recovery: refresh + retry exactly once.
        if _is_cert_revoked_response(response):
            response.read()  # drain so the connection can be reused
            agent.refresh_credentials()  # mutates agent.private_key_bytes/cert in place;
                                         # raises AgentSuspendedError on 403 (don't retry)
            rewritten = _build_signed_request(request, agent, self.provider)
            response = self._inner.handle_request(rewritten)

        if response.status_code >= 400:
            response.read()
            _raise_for_error(response, self.provider)

        return response

    def close(self) -> None:
        self._inner.close()


class RunVaultProviderAsyncTransport(httpx.AsyncBaseTransport):
    """Async httpx transport that routes requests through the RunVault proxy.

    Mirrors :class:`RunVaultProviderTransport`, including the lazy refresh
    on 401 CERTIFICATE_REVOKED.
    """

    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._inner = httpx.AsyncHTTPTransport(verify=True)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from runvault.context import _current_agent

        agent = _current_agent.get(None)
        if agent is None:
            raise RuntimeError(
                f"No active RunVault agent. Call runvault.init(...) before "
                f"invoking this {self.provider} LLM client."
            )

        rewritten = _build_signed_request(request, agent, self.provider)
        response = await self._inner.handle_async_request(rewritten)

        if _is_cert_revoked_response(response):
            await response.aread()
            # Note: refresh_credentials is currently sync. For the async
            # transport we still call it synchronously because the SDK's
            # BackendClient is a sync httpx.Client — the call is fast
            # enough (single round-trip) that a brief block in the event
            # loop is acceptable here. If/when BackendClient gains an
            # async variant, this should switch to an async call.
            agent.refresh_credentials()
            rewritten = _build_signed_request(request, agent, self.provider)
            response = await self._inner.handle_async_request(rewritten)

        if response.status_code >= 400:
            await response.aread()
            _raise_for_error(response, self.provider)

        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
