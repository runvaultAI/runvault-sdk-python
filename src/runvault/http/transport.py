"""RunVaultProviderTransport — scoped httpx transport for LLM provider routing.

Each LLM client built by a factory in ``runvault.llm.*`` receives its
own httpx.Client whose transport is one of these classes — a transport
is **bound** to the Identity that built the LLM. Nothing outside those
clients is affected.

At request time the transport:
  1. Reads the active Run from the _CURRENT_RUN ContextVar (set by
     ``with identity.run():``). Raises :class:`NoActiveRunError` if
     no run is active.
  2. Refuses to attach RunVault credentials to any host other than the
     bound identity's proxy — raises :class:`UntrustedHostError`. Without
     this, a user-held ``identity.http_client()`` aimed at any URL would
     exfiltrate valid signed JWTs.
  3. Compares the bound identity (the LLM's owner) against the active
     run's identity. On mismatch, consults the run's effective
     ``security_policy`` and either raises :class:`CrossIdentityError`
     (``"hard"``) or warns with :class:`CrossIdentityWarning` (``"soft"``).
  4. Replaces the PLACEHOLDER_BASE URL with the bound identity's proxy URL.
  5. Mints a fresh per-request EdDSA JWT signed with the **bound**
     identity's private key (the only key the transport holds) and
     injects the PKI headers (X-RV-Certificate + X-RV-Agent-JWT).
  6. Forwards the rewritten request to the real network.
  7. On 401 CERTIFICATE_REVOKED, calls
     ``bound_identity.refresh_credentials()`` and retries once.
  8. On any other 4xx/5xx, reads the body and raises a typed RunVaultError.

The bound identity is captured at transport construction; ``run.identity``
is consulted only for run_id and for the cross-identity check.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING

import httpx

from runvault.exceptions import (
    BudgetExceededError,
    CrossIdentityError,
    CrossIdentityWarning,
    LLMProviderError,
    NoActiveRunError,
    ProxyError,
    TokenExpiredError,
    UntrustedHostError,
)

if TYPE_CHECKING:
    from runvault.identity import Identity

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
    bound_identity: "Identity",
    run_id: str,
    provider: str,
) -> httpx.Request:
    """Mint a fresh per-request EdDSA JWT + rewrite URL/headers for the proxy.

    Signs with the *bound* identity's key — the only key the transport
    holds. ``run_id`` comes from the active Run separately so the transport
    can record the call against the correct execution scope even when
    ``security_policy="soft"`` lets a cross-identity call through.

    Helper used twice on the retry path: once for the initial send, and
    once after ``bound_identity.refresh_credentials()`` if the proxy
    reported the cert was revoked. Both calls read the identity's current
    credentials at the moment they're made.
    """
    from runvault.auth.signer import create_agent_jwt

    if bound_identity.private_key_bytes is None or bound_identity.certificate_b64 is None:
        raise RuntimeError(
            "Identity is missing PKI credentials. Ensure register_agent() "
            "completed successfully and RV_CA_PUBLIC_KEY is set."
        )

    agent_jwt = create_agent_jwt(
        agent_id=bound_identity.db_agent_id,
        run_id=run_id,
        private_key_bytes=bound_identity.private_key_bytes,
    )

    return _rewrite_request(
        request,
        proxy_base=bound_identity.proxy_url,
        provider=provider,
        agent_jwt=agent_jwt,
        certificate_b64=bound_identity.certificate_b64,
    )


def _check_host_allowlist(
    request: httpx.Request,
    proxy_host: str,
) -> None:
    """Refuse to attach RunVault credentials to any host but the proxy.

    The PLACEHOLDER_BASE rewrite step replaces the placeholder host with
    the proxy host before headers are attached, so legitimate proxy-bound
    requests always pass. A user-held ``identity.http_client()`` aimed at
    an arbitrary URL trips this check before any signing happens, so no
    JWT is exposed.
    """
    request_host = request.url.host
    if request_host == proxy_host:
        return
    # Allow the placeholder host through — it gets rewritten to the proxy
    # in _rewrite_request a few lines later. Anything else is suspect.
    if request_host == httpx.URL(PLACEHOLDER_BASE).host:
        return
    raise UntrustedHostError(
        f"Refusing to attach RunVault credentials to {request_host!r}; "
        f"allowed host: {proxy_host!r}.",
        error_code="UNTRUSTED_HOST",
        user_string=(
            "The RunVault client refused to send a signed request to a "
            "non-proxy URL. Check the URL your code is hitting."
        ),
    )


def _check_cross_identity(
    bound_identity: "Identity",
    run,
) -> None:
    """Compare the bound identity to the active run's identity.

    In ``"hard"`` mode (default), mismatch raises :class:`CrossIdentityError`
    before the request is sent. In ``"soft"`` mode, the SDK warns and lets
    the call proceed — the transport then signs with the bound identity's
    key (the only key it holds), so the **bound** identity is billed.
    """
    run_identity = run.identity
    if run_identity.agent_id == bound_identity.agent_id:
        return

    policy = run.effective_security_policy
    msg = (
        f"LLM bound to agent_id={bound_identity.agent_id!r} was invoked "
        f"under a run owned by agent_id={run_identity.agent_id!r}."
    )
    if policy == "hard":
        raise CrossIdentityError(
            msg,
            error_code="CROSS_IDENTITY",
            user_string=(
                "A RunVault call crossed identity boundaries. Check that "
                "each LLM is used inside the matching `with identity.run():`."
            ),
        )
    warnings.warn(msg, CrossIdentityWarning, stacklevel=2)


class RunVaultProviderTransport(httpx.BaseTransport):
    """Sync httpx transport that routes requests through the RunVault proxy.

    One instance is created per LLM client and **bound to the Identity
    that built the LLM**. The active Run is looked up from the ContextVar
    at request time; if the bound identity and the run's identity differ,
    the cross-identity guard kicks in per the run's ``security_policy``.

    Credential refresh on 401 CERTIFICATE_REVOKED
    ─────────────────────────────────────────────
    When an admin rotates an agent's certificate (scope change or explicit
    revoke), the proxy's revocation cache picks up the change within ≤30 s
    and starts returning 401 CERTIFICATE_REVOKED to in-flight requests. To
    keep the agent running transparently, this transport detects that
    specific 4xx, calls ``bound_identity.refresh_credentials()`` to mint
    fresh creds, and retries the request ONCE with the new JWT/cert.

    Limitations of the retry:
      - One retry only. If the second attempt also fails, the error
        propagates normally — no retry storm.
      - If the agent has been administratively suspended,
        ``bound_identity.refresh_credentials()`` raises ``AgentSuspendedError``;
        the transport propagates it without retrying.
    """

    def __init__(self, provider: str, bound_identity: "Identity") -> None:
        self.provider = provider
        self._bound_identity = bound_identity
        self._proxy_host = httpx.URL(bound_identity.proxy_url).host
        self._inner = httpx.HTTPTransport(verify=True)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        from runvault.identity import _CURRENT_RUN

        run = _CURRENT_RUN.get(None)
        if run is None:
            raise NoActiveRunError(
                f"No active RunVault run. Wrap your {self.provider} call in "
                f"`with identity.run():` before invoking it."
            )

        _check_host_allowlist(request, self._proxy_host)
        _check_cross_identity(self._bound_identity, run)

        rewritten = _build_signed_request(
            request, self._bound_identity, run.run_id, self.provider,
        )
        response = self._inner.handle_request(rewritten)

        # Cert-revoked recovery: refresh + retry exactly once.
        if _is_cert_revoked_response(response):
            response.read()  # drain so the connection can be reused
            self._bound_identity.refresh_credentials()  # mutates in place;
                                                        # raises AgentSuspendedError on 403
            rewritten = _build_signed_request(
                request, self._bound_identity, run.run_id, self.provider,
            )
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
    on 401 CERTIFICATE_REVOKED and the cross-identity guard.
    """

    def __init__(self, provider: str, bound_identity: "Identity") -> None:
        self.provider = provider
        self._bound_identity = bound_identity
        self._proxy_host = httpx.URL(bound_identity.proxy_url).host
        self._inner = httpx.AsyncHTTPTransport(verify=True)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        from runvault.identity import _CURRENT_RUN

        run = _CURRENT_RUN.get(None)
        if run is None:
            raise NoActiveRunError(
                f"No active RunVault run. Wrap your {self.provider} call in "
                f"`async with identity.run():` before invoking it."
            )

        _check_host_allowlist(request, self._proxy_host)
        _check_cross_identity(self._bound_identity, run)

        rewritten = _build_signed_request(
            request, self._bound_identity, run.run_id, self.provider,
        )
        response = await self._inner.handle_async_request(rewritten)

        if _is_cert_revoked_response(response):
            await response.aread()
            # Note: refresh_credentials is currently sync. For the async
            # transport we still call it synchronously because the SDK's
            # BackendClient is a sync httpx.Client — the call is fast
            # enough (single round-trip) that a brief block in the event
            # loop is acceptable here. If/when BackendClient gains an
            # async variant, this should switch to an async call.
            self._bound_identity.refresh_credentials()
            rewritten = _build_signed_request(
                request, self._bound_identity, run.run_id, self.provider,
            )
            response = await self._inner.handle_async_request(rewritten)

        if response.status_code >= 400:
            await response.aread()
            _raise_for_error(response, self.provider)

        return response

    async def aclose(self) -> None:
        await self._inner.aclose()
