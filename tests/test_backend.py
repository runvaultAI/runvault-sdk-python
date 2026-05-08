import pytest
import httpx
from unittest.mock import MagicMock, patch

from runvault.http.backend import BackendClient
from runvault.exceptions import AuthenticationError, ConnectionError, RegistrationError


def _make_client() -> BackendClient:
    return BackendClient(be_url="http://backend:30080")


def _mock_resp(status_code: int, json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_body
    resp.text = str(json_body)
    return resp


# ---------------------------------------------------------------------------
# post()
# ---------------------------------------------------------------------------

class TestBackendClientPost:
    def test_returns_json_on_200(self):
        client = _make_client()
        with patch.object(client._client, "post", return_value=_mock_resp(200, {"token": "jwt"})):
            result = client.post("/auth/agents/runs", {"key": "val"})
        assert result == {"token": "jwt"}

    def test_raises_connection_error_on_connect_error(self):
        client = _make_client()
        with patch.object(client._client, "post", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ConnectionError, match="backend"):
                client.post("/auth/agents/runs", {})

    def test_raises_connection_error_on_timeout(self):
        client = _make_client()
        with patch.object(client._client, "post", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="timed out"):
                client.post("/auth/agents/runs", {})

    def test_raises_authentication_error_on_401(self):
        client = _make_client()
        body = {"detail": {"detail": "Bad key", "code": "INVALID_API_KEY", "user_string": "Invalid"}}
        with patch.object(client._client, "post", return_value=_mock_resp(401, body)):
            with pytest.raises(AuthenticationError) as exc_info:
                client.post("/auth/agents/runs", {})
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == "INVALID_API_KEY"

    def test_raises_registration_error_on_500(self):
        client = _make_client()
        body = {"detail": {"detail": "Server error", "code": "INTERNAL_ERROR", "user_string": "Error"}}
        with patch.object(client._client, "post", return_value=_mock_resp(500, body)):
            with pytest.raises(RegistrationError) as exc_info:
                client.post("/auth/agents/runs", {})
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# get()
# ---------------------------------------------------------------------------

class TestBackendClientGet:
    def test_returns_json_on_200(self):
        client = _make_client()
        with patch.object(client._client, "get", return_value=_mock_resp(200, {"version": "1.0.0"})):
            result = client.get("/info")
        assert result == {"version": "1.0.0"}

    def test_raises_connection_error_on_connect_error(self):
        client = _make_client()
        with patch.object(client._client, "get", side_effect=httpx.ConnectError("refused")):
            with pytest.raises(ConnectionError, match="backend"):
                client.get("/info")

    def test_raises_connection_error_on_timeout(self):
        client = _make_client()
        with patch.object(client._client, "get", side_effect=httpx.TimeoutException("timeout")):
            with pytest.raises(ConnectionError, match="timed out"):
                client.get("/info")

    def test_raises_authentication_error_on_401(self):
        client = _make_client()
        body = {"detail": {"detail": "Unauthorized", "code": "UNAUTHORIZED", "user_string": "Unauthorized"}}
        with patch.object(client._client, "get", return_value=_mock_resp(401, body)):
            with pytest.raises(AuthenticationError):
                client.get("/protected")


# ---------------------------------------------------------------------------
# _handle()
# ---------------------------------------------------------------------------

class TestBackendClientHandle:
    def test_200_returns_json(self):
        client = _make_client()
        assert client._handle(_mock_resp(200, {"data": "value"})) == {"data": "value"}

    def test_401_raises_authentication_error(self):
        client = _make_client()
        body = {"detail": {"detail": "Bad key", "code": "INVALID_API_KEY", "user_string": "Invalid"}}
        with pytest.raises(AuthenticationError) as exc_info:
            client._handle(_mock_resp(401, body))
        assert exc_info.value.status_code == 401
        assert exc_info.value.error_code == "INVALID_API_KEY"

    def test_400_raises_authentication_error(self):
        client = _make_client()
        body = {"detail": {"detail": "Bad request", "code": "VALIDATION_ERROR", "user_string": "Bad"}}
        with pytest.raises(AuthenticationError) as exc_info:
            client._handle(_mock_resp(400, body))
        assert exc_info.value.status_code == 400

    def test_500_raises_registration_error(self):
        client = _make_client()
        body = {"detail": {"detail": "Server error", "code": "INTERNAL_ERROR", "user_string": "Error"}}
        with pytest.raises(RegistrationError) as exc_info:
            client._handle(_mock_resp(500, body))
        assert exc_info.value.status_code == 500


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------

class TestBackendClientClose:
    def test_close_closes_underlying_client(self):
        client = _make_client()
        with patch.object(client._client, "close") as mock_close:
            client.close()
        mock_close.assert_called_once()
