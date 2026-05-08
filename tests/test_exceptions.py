import pytest

from runvault.exceptions import (
    AuthenticationError,
    BudgetExceededError,
    ConfigurationError,
    ConnectionError,
    LLMProviderError,
    ProxyError,
    RegistrationError,
    RunVaultError,
    TokenExpiredError,
)


class TestRunVaultError:
    def test_message_only(self):
        e = RunVaultError("something went wrong")
        assert str(e) == "something went wrong"
        assert e.status_code is None
        assert e.error_code is None
        assert e.user_string == "something went wrong"

    def test_user_string_falls_back_to_message_when_none(self):
        e = RunVaultError("msg", user_string=None)
        assert e.user_string == "msg"

    def test_explicit_user_string(self):
        e = RunVaultError("internal msg", user_string="Human readable")
        assert e.user_string == "Human readable"
        assert str(e) == "internal msg"

    def test_all_fields(self):
        e = RunVaultError("msg", status_code=400, error_code="BAD", user_string="Bad")
        assert e.status_code == 400
        assert e.error_code == "BAD"
        assert e.user_string == "Bad"

    def test_is_exception(self):
        assert isinstance(RunVaultError("msg"), Exception)


class TestAuthErrors:
    def test_authentication_error_inherits_base(self):
        e = AuthenticationError("bad key", status_code=401, error_code="INVALID_API_KEY")
        assert isinstance(e, RunVaultError)
        assert e.status_code == 401
        assert e.error_code == "INVALID_API_KEY"

    def test_authentication_error_user_string(self):
        e = AuthenticationError("bad key", user_string="Invalid key.")
        assert e.user_string == "Invalid key."

    def test_registration_error(self):
        e = RegistrationError("failed", status_code=500, error_code="SERVER_ERROR")
        assert isinstance(e, RunVaultError)
        assert e.status_code == 500

    def test_connection_error(self):
        e = ConnectionError("unreachable", user_string="Cannot reach backend.")
        assert isinstance(e, RunVaultError)
        assert e.user_string == "Cannot reach backend."

    def test_configuration_error(self):
        e = ConfigurationError("missing config")
        assert isinstance(e, RunVaultError)


class TestProxyErrors:
    def test_budget_exceeded_no_remaining(self):
        e = BudgetExceededError("cap reached", status_code=429, error_code="BUDGET_CAP_REACHED")
        assert isinstance(e, RunVaultError)
        assert e.remaining_usd is None
        assert e.status_code == 429

    def test_budget_exceeded_with_remaining(self):
        e = BudgetExceededError("cap reached", remaining_usd=0.0042)
        assert e.remaining_usd == 0.0042

    def test_budget_exceeded_user_string(self):
        e = BudgetExceededError("internal", user_string="Spending limit reached.")
        assert e.user_string == "Spending limit reached."

    def test_token_expired_error(self):
        e = TokenExpiredError("expired", status_code=401, error_code="JWT_EXPIRED")
        assert isinstance(e, RunVaultError)
        assert e.status_code == 401

    def test_proxy_error(self):
        e = ProxyError("version mismatch", status_code=503, error_code="PROXY_VERSION_MISMATCH")
        assert isinstance(e, RunVaultError)
        assert e.status_code == 503


class TestLLMProviderError:
    def test_with_provider(self):
        e = LLMProviderError("model not found", provider="openai", status_code=404)
        assert isinstance(e, RunVaultError)
        assert e.provider == "openai"
        assert e.status_code == 404

    def test_without_provider(self):
        e = LLMProviderError("error")
        assert e.provider is None

    def test_user_string(self):
        e = LLMProviderError("bad request", provider="anthropic", user_string="Anthropic error.")
        assert e.user_string == "Anthropic error."


