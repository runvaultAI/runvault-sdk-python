from __future__ import annotations

from .base import RunVaultError


class NoActiveRunError(RunVaultError):
    """``current_run()`` called outside a ``with identity.run():`` block.

    The SDK never falls back to a default run — a missing run is a
    programming error, not a recoverable condition. Wrap the call in
    ``with identity.run():`` before invoking the LLM.
    """


class UntrustedHostError(RunVaultError):
    """The transport refused to attach RunVault credentials to a non-proxy host.

    The transport signs every outbound request with the agent's
    private key. A user-held ``identity.http_client()`` aimed at any
    other URL would otherwise exfiltrate a valid signed JWT. The host
    allowlist closes this off — only the configured proxy host is
    permitted.
    """


class CrossIdentityError(RunVaultError):
    """An LLM bound to one identity was invoked under another identity's run.

    Raised by the transport when ``security_policy="hard"`` (the default).
    Catches accidental cross-wiring between agents in multi-identity
    codebases. With ``security_policy="soft"``, the SDK emits
    :class:`CrossIdentityWarning` instead and lets the call proceed
    using the *bound* identity's key.
    """


class CrossIdentityWarning(Warning):
    """Emitted in ``security_policy="soft"`` mode when a bound LLM is
    invoked under a different identity's active run.

    The request proceeds using the bound identity's key (the transport
    cannot sign with keys it doesn't hold), so the **bound** identity
    is billed — not the run owner.
    """
