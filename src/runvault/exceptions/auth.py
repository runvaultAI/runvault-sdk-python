from .base import RunVaultError


class AuthenticationError(RunVaultError):
    """API key is invalid, revoked, or has no linked LLM vault key."""


class RegistrationError(RunVaultError):
    """Agent registration with the RunVault backend failed."""


class ConnectionError(RunVaultError):
    """RunVault backend could not be reached (network error or timeout)."""


class ConfigurationError(RunVaultError):
    """Required SDK configuration is missing or invalid (e.g. no proxy URL)."""


class CertificateVerificationError(RunVaultError):
    """Certificate CA signature or expiry check failed.

    This indicates either:
      - The RunVault CA has rotated its signing key (re-register to get a
        certificate signed by the new key).
      - The certificate on disk has been corrupted or tampered with.
      - The certificate has expired.

    Re-registering with the backend always resolves this — the backend issues
    a fresh keypair and a new CA-signed certificate on every registration call.
    """


class AgentSuspendedError(RunVaultError):
    """Agent has been administratively suspended.

    Raised when the backend returns 403 AGENT_SUSPENDED from either init() or
    /credentials/refresh. The agent's status has been set to 'revoked' by an
    admin via the dashboard. The SDK CANNOT recover from this state on its
    own — an admin must click "Reactivate" in the dashboard, after which the
    agent's next call automatically obtains fresh credentials via
    /credentials/refresh.

    Catching this exception should surface a permanent-failure message to
    operators (e.g. "Your administrator has suspended this agent. Contact
    them to reactivate it."). Do NOT auto-retry; do NOT fall back to other
    auth paths.
    """
