"""Tests for runvault.auth.credentials — file storage + cert verification."""

from __future__ import annotations

import base64
import json
import stat
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from runvault.auth.credentials import (
    load_credentials,
    save_credentials,
    verify_certificate,
)
from runvault.exceptions.auth import CertificateVerificationError


@pytest.fixture
def tmp_home(tmp_path, monkeypatch):
    """Redirect Path.home() to a temp directory so tests don't touch the real $HOME."""
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def ca_keypair():
    """A fresh Ed25519 CA keypair returned as (private_key_obj, base64_public_key)."""
    private = Ed25519PrivateKey.generate()
    public_b64 = base64.b64encode(private.public_key().public_bytes_raw()).decode()
    return private, public_b64


def _signed_certificate(
    ca_private: Ed25519PrivateKey,
    *,
    serial_number: str = "test-serial-001",
    expires_at: datetime | None = None,
) -> dict:
    """Build a CA-signed certificate dict matching the backend's signing format."""
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(days=365)
    payload = {
        "version": 1,
        "serial_number": serial_number,
        "agent_id": "a3a268ce-e2db-4abd-ba01-f69057e6e825",
        "project_id": "00000000-0000-0000-0000-000000000000",
        "issued_by": "RunVault-Test",
        "issued_at": "2026-01-01T00:00:00+00:00",
        "expires_at": expires_at.isoformat(),
        "scope": ["LLM"],
        "public_key": base64.b64encode(b"\x00" * 32).decode(),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    signature = ca_private.sign(canonical)
    payload["signature"] = base64.b64encode(signature).decode()
    return payload


# ---------------------------------------------------------------------------
# save_credentials / load_credentials
# ---------------------------------------------------------------------------

class TestSaveLoadRoundTrip:
    def test_round_trip(self, tmp_home):
        raw_key = b"\x42" * 32
        cert = {"serial_number": "abc", "agent_id": "x", "scope": ["LLM"]}

        save_credentials(
            agent_id="my-agent",
            private_key_b64=base64.b64encode(raw_key).decode(),
            certificate=cert,
        )

        loaded = load_credentials("my-agent")
        assert loaded is not None
        loaded_key, loaded_cert = loaded
        assert loaded_key == raw_key
        assert loaded_cert == cert

    def test_load_returns_none_when_files_missing(self, tmp_home):
        assert load_credentials("never-saved") is None

    def test_save_overwrites_existing_files(self, tmp_home):
        save_credentials(
            agent_id="ag",
            private_key_b64=base64.b64encode(b"\x01" * 32).decode(),
            certificate={"v": 1},
        )
        save_credentials(
            agent_id="ag",
            private_key_b64=base64.b64encode(b"\x02" * 32).decode(),
            certificate={"v": 2},
        )
        loaded_key, loaded_cert = load_credentials("ag")
        assert loaded_key == b"\x02" * 32
        assert loaded_cert == {"v": 2}


class TestSavedFilePermissions:
    """Private keys are sensitive — file permissions must reject other users.

    These tests are POSIX-only (Windows has no concept of 0600).
    """

    def test_private_key_file_is_0600(self, tmp_home):
        save_credentials(
            agent_id="perms-agent",
            private_key_b64=base64.b64encode(b"\x00" * 32).decode(),
            certificate={"any": "thing"},
        )
        key_file = tmp_home / ".runvault" / "perms-agent" / "private.key"
        mode = stat.S_IMODE(key_file.stat().st_mode)
        assert mode == 0o600, f"expected 0o600 on private.key, got {oct(mode)}"

    def test_certificate_file_is_0600(self, tmp_home):
        save_credentials(
            agent_id="perms-agent",
            private_key_b64=base64.b64encode(b"\x00" * 32).decode(),
            certificate={"any": "thing"},
        )
        cert_file = tmp_home / ".runvault" / "perms-agent" / "certificate.json"
        mode = stat.S_IMODE(cert_file.stat().st_mode)
        assert mode == 0o600, f"expected 0o600 on certificate.json, got {oct(mode)}"

    def test_agent_directory_is_0700(self, tmp_home):
        save_credentials(
            agent_id="perms-agent",
            private_key_b64=base64.b64encode(b"\x00" * 32).decode(),
            certificate={"any": "thing"},
        )
        agent_dir = tmp_home / ".runvault" / "perms-agent"
        mode = stat.S_IMODE(agent_dir.stat().st_mode)
        assert mode == 0o700, f"expected 0o700 on agent dir, got {oct(mode)}"


# ---------------------------------------------------------------------------
# verify_certificate
# ---------------------------------------------------------------------------

class TestVerifyCertificate:
    def test_accepts_valid_signed_cert(self, ca_keypair):
        ca_private, ca_public_b64 = ca_keypair
        cert = _signed_certificate(ca_private)
        # Should not raise.
        verify_certificate(cert, ca_public_b64)

    def test_rejects_when_signed_by_different_ca(self, ca_keypair):
        ca_private, _ = ca_keypair
        cert = _signed_certificate(ca_private)

        other_ca_public_b64 = base64.b64encode(
            Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        ).decode()

        with pytest.raises(CertificateVerificationError, match="signature is invalid"):
            verify_certificate(cert, other_ca_public_b64)

    def test_rejects_tampered_payload(self, ca_keypair):
        ca_private, ca_public_b64 = ca_keypair
        cert = _signed_certificate(ca_private)

        # Tamper after signing — the signature still references the original payload.
        cert["agent_id"] = "0c0c0c0c-0c0c-0c0c-0c0c-0c0c0c0c0c0c"

        with pytest.raises(CertificateVerificationError, match="signature is invalid"):
            verify_certificate(cert, ca_public_b64)

    def test_rejects_expired_cert(self, ca_keypair):
        ca_private, ca_public_b64 = ca_keypair
        cert = _signed_certificate(
            ca_private,
            expires_at=datetime.now(timezone.utc) - timedelta(days=1),
        )

        with pytest.raises(CertificateVerificationError, match="expired"):
            verify_certificate(cert, ca_public_b64)

    def test_rejects_missing_signature_field(self, ca_keypair):
        _, ca_public_b64 = ca_keypair
        cert = {"agent_id": "x", "expires_at": "2099-01-01T00:00:00+00:00"}
        with pytest.raises(CertificateVerificationError, match="missing the 'signature'"):
            verify_certificate(cert, ca_public_b64)

    def test_rejects_unparseable_expires_at(self, ca_keypair):
        ca_private, ca_public_b64 = ca_keypair
        cert = _signed_certificate(ca_private)
        # Re-sign after corrupting expires_at so signature still verifies.
        cert.pop("signature")
        cert["expires_at"] = "garbage"
        canonical = json.dumps(cert, sort_keys=True, separators=(",", ":")).encode()
        cert["signature"] = base64.b64encode(ca_private.sign(canonical)).decode()

        with pytest.raises(CertificateVerificationError, match="unparseable expires_at"):
            verify_certificate(cert, ca_public_b64)

    def test_rejects_wrong_length_ca_key(self):
        cert = {"signature": base64.b64encode(b"x" * 64).decode(), "expires_at": "2099-01-01T00:00:00+00:00"}
        short_key = base64.b64encode(b"\x00" * 16).decode()
        with pytest.raises(ValueError, match="must be 32 bytes"):
            verify_certificate(cert, short_key)

    def test_rejects_non_base64_ca_key(self):
        cert = {"signature": base64.b64encode(b"x" * 64).decode(), "expires_at": "2099-01-01T00:00:00+00:00"}
        with pytest.raises(ValueError, match="not valid base64"):
            verify_certificate(cert, "not!valid!base64!!!")
