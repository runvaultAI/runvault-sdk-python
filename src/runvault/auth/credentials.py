"""Credential storage and verification for RunVault agents.

Files are written to:
    ~/.runvault/<agent_id>/
        private.key       raw 32-byte Ed25519 private key (binary)
        certificate.json  signed RunVault certificate (JSON text)

~/ resolves to $HOME at call time via Path.home(), so the location is
correct whether the agent runs on a developer laptop or inside Docker
(where HOME=/home/appuser is set explicitly in docker-compose.yml).

Permissions:
    directory  0700 — only the owner can enter it
    files      0600 — only the owner can read or write

Why 0600 and not world-readable?
    The private key is a long-lived secret. Anyone who reads it can
    impersonate this agent — forge JWTs, make LLM calls on its budget,
    and sign fraudulent certificates. 0600 ensures the OS enforces that
    only the user account running the agent can access the file.
    This mirrors the convention used by SSH (~/.ssh/id_ed25519 is 0600).

Re-registration overwrites existing files. This is intentional — a new
registration issues a fresh keypair, making the old private key useless.
The old certificate is also replaced. Any in-flight requests using the
old certificate will continue to work until that certificate expires.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)


def _agent_dir(agent_id: str) -> Path:
    return Path.home() / ".runvault" / agent_id


def save_credentials(
    agent_id: str,
    private_key_b64: str,
    certificate: dict,
) -> None:
    """Save the agent's private key and certificate to disk.

    Args:
        agent_id:        External agent ID string (e.g. "research-v1").
                         Used as the directory name — must be filesystem-safe.
        private_key_b64: Base64-encoded raw 32-byte Ed25519 private key,
                         as returned by the backend registration response.
        certificate:     Signed certificate dict, as returned by the backend.

    Raises:
        OSError: If the directory cannot be created or files cannot be written
                 (e.g. read-only filesystem, permission denied).
    """
    agent_dir = _agent_dir(agent_id)
    agent_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(agent_dir, 0o700)

    key_file = agent_dir / "private.key"
    key_file.write_bytes(base64.b64decode(private_key_b64))
    os.chmod(key_file, 0o600)

    cert_file = agent_dir / "certificate.json"
    cert_file.write_text(json.dumps(certificate, indent=2))
    os.chmod(cert_file, 0o600)

    log.info("credentials saved: agent_id=%r dir=%s", agent_id, agent_dir)


def load_credentials(agent_id: str) -> tuple[bytes, dict] | None:
    """Load the agent's private key and certificate from disk.

    Args:
        agent_id: External agent ID string — must match what was used in save.

    Returns:
        (private_key_bytes, certificate_dict) if both files exist, else None.
        Returns None (not raises) when files are absent — callers decide
        whether a missing credential is an error.
    """
    agent_dir = _agent_dir(agent_id)
    key_file = agent_dir / "private.key"
    cert_file = agent_dir / "certificate.json"

    if not key_file.exists() or not cert_file.exists():
        log.debug("no credentials on disk for agent_id=%r", agent_id)
        return None

    private_key_bytes = key_file.read_bytes()
    certificate = json.loads(cert_file.read_text())

    log.debug("credentials loaded from disk: agent_id=%r", agent_id)
    return private_key_bytes, certificate


def verify_certificate(certificate: dict, ca_public_key_b64: str) -> None:
    """Verify a RunVault certificate against the CA public key.

    Checks two things:
      1. CA signature — proves RunVault issued this certificate and it has not
         been tampered with. Fails if RunVault has rotated its CA keys since
         this certificate was issued.
      2. Expiry — the certificate's expires_at must be in the future.

    This function is called automatically by the SDK after every registration
    to confirm the backend returned a genuinely CA-signed certificate. It can
    also be called manually to check credentials already stored on disk.

    Args:
        certificate:      The certificate dict (as returned by the backend or
                          loaded from ~/.runvault/<agent_id>/certificate.json).
        ca_public_key_b64: Base64-encoded 32-byte Ed25519 CA public key.
                           Use the value of the RV_CA_PUBLIC_KEY environment
                           variable from your RunVault deployment.

    Raises:
        CertificateVerificationError: Signature is invalid or certificate has expired.
        ValueError: ca_public_key_b64 is not valid base64 or wrong key length.

    Example — verify credentials stored on disk::

        from runvault.auth.credentials import load_credentials, verify_certificate
        import os

        creds = load_credentials("my-agent")
        if creds:
            _, cert = creds
            verify_certificate(cert, os.environ["RV_CA_PUBLIC_KEY"])
            print("Certificate is valid")
    """
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from runvault.exceptions.auth import CertificateVerificationError

    # Decode and validate the CA public key.
    try:
        ca_key_bytes = base64.b64decode(ca_public_key_b64)
    except Exception as exc:
        raise ValueError(f"ca_public_key_b64 is not valid base64: {exc}") from exc

    if len(ca_key_bytes) != 32:
        raise ValueError(
            f"CA public key must be 32 bytes (Ed25519), got {len(ca_key_bytes)}"
        )

    ca_public_key = Ed25519PublicKey.from_public_bytes(ca_key_bytes)

    # Extract and remove the signature before re-encoding the payload.
    sig_b64 = certificate.get("signature")
    if not sig_b64:
        raise CertificateVerificationError(
            "certificate is missing the 'signature' field"
        )

    try:
        signature = base64.b64decode(sig_b64)
    except Exception as exc:
        raise CertificateVerificationError(
            f"certificate signature is not valid base64: {exc}"
        ) from exc

    # Reconstruct the canonical signing bytes.
    # The backend signs with: json.dumps(payload, sort_keys=True, separators=(",",":"))
    # Python's json.dumps with sort_keys=True produces keys in alphabetical order,
    # identical to what the backend signed. The signature field is excluded.
    payload = {k: v for k, v in certificate.items() if k != "signature"}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()

    # Verify the CA signature.
    try:
        ca_public_key.verify(signature, canonical)
    except InvalidSignature as exc:
        raise CertificateVerificationError(
            "certificate CA signature is invalid — the CA may have rotated its "
            "signing key. Re-registering will issue a fresh certificate."
        ) from exc

    # Check expiry.
    expires_at_str = certificate.get("expires_at", "")
    try:
        expires_at = datetime.fromisoformat(expires_at_str)
    except ValueError as exc:
        raise CertificateVerificationError(
            f"certificate has unparseable expires_at: {expires_at_str!r}"
        ) from exc

    if datetime.now(timezone.utc) > expires_at.astimezone(timezone.utc):
        raise CertificateVerificationError(
            f"certificate expired at {expires_at_str}"
        )

    log.debug(
        "certificate verified: serial=%s expires_at=%s",
        certificate.get("serial_number"),
        expires_at_str,
    )
