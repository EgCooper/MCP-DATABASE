"""Validate timeout configuration without reading credentials from disk."""

from dataclasses import replace

import pytest

from mcp_mysql.config import MySQLConfig


TIMEOUTS = {
    "MYSQL_CONNECT_TIMEOUT": ("connection_timeout", 10),
    "MYSQL_READ_TIMEOUT": ("read_timeout", 30),
    "MYSQL_WRITE_TIMEOUT": ("write_timeout", 30),
    "MYSQL_QUERY_TIMEOUT_MS": ("query_timeout_ms", 15000),
}


@pytest.fixture
def config():
    return MySQLConfig(
        host="example.invalid", port=3306, user="readonly",
        password="dummy-secret", database="test",
    )


def test_timeout_defaults_and_password_representation(config):
    for name, expected in TIMEOUTS.values():
        assert getattr(config, name) == expected
    assert "dummy-secret" not in repr(config)


def test_timeout_environment_overrides(monkeypatch):
    for variable in TIMEOUTS:
        monkeypatch.setenv(variable, "25")
    config = MySQLConfig.from_env()
    for name, _ in TIMEOUTS.values():
        assert getattr(config, name) == 25


@pytest.mark.parametrize("variable", TIMEOUTS)
@pytest.mark.parametrize("value", ["0", "-1", "", "abc", "1.5"])
def test_invalid_environment_timeouts_are_rejected(monkeypatch, variable, value):
    for key in TIMEOUTS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv(variable, value)
    with pytest.raises(ValueError, match=variable):
        MySQLConfig.from_env()


@pytest.mark.parametrize("name", [item[0] for item in TIMEOUTS.values()])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10", None])
def test_direct_configuration_cannot_disable_timeouts(config, name, value):
    with pytest.raises(ValueError, match=name):
        replace(config, **{name: value})


def test_execution_timeout_rejects_values_mysql_cannot_represent(config):
    with pytest.raises(ValueError, match="4294967295"):
        replace(config, query_timeout_ms=4294967296)


def test_database_user_is_required_and_never_defaults_to_root(monkeypatch):
    monkeypatch.delenv("MYSQL_USER")
    with pytest.raises(ValueError, match="MYSQL_USER is required"):
        MySQLConfig.from_env()
    monkeypatch.setenv("MYSQL_USER", "   ")
    with pytest.raises(ValueError, match="MYSQL_USER is required"):
        MySQLConfig.from_env()


def test_tls_settings_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("MYSQL_SSL_CA", "/etc/ssl/db-ca.pem")
    monkeypatch.setenv("MYSQL_SSL_VERIFY_IDENTITY", "true")
    options = MySQLConfig.from_env().as_dict()
    assert options["ssl_ca"] == "/etc/ssl/db-ca.pem" and options["ssl_verify_cert"] is True
    assert options["ssl_verify_identity"] is True


def test_without_a_ca_no_tls_options_are_forced(monkeypatch):
    assert "ssl_ca" not in MySQLConfig.from_env().as_dict()


def test_identity_verification_needs_a_ca(config):
    with pytest.raises(ValueError, match="MYSQL_SSL_CA"):
        replace(config, ssl_verify_identity=True)


@pytest.mark.parametrize("value, expected", [("1", True), ("TRUE", True), ("on", True), ("0", False), ("no", False), ("", False)])
def test_exploration_flag_parsing(monkeypatch, value, expected):
    from mcp_mysql.config import exploration_tools_enabled
    monkeypatch.setenv("MCP_ENABLE_EXPLORATION_TOOLS", value)
    assert exploration_tools_enabled() is expected


def test_exploration_tools_are_disabled_by_default_and_flags_are_strict(monkeypatch):
    from mcp_mysql.config import exploration_tools_enabled
    monkeypatch.delenv("MCP_ENABLE_EXPLORATION_TOOLS")
    assert exploration_tools_enabled() is False
    monkeypatch.setenv("MCP_ENABLE_EXPLORATION_TOOLS", "maybe")
    with pytest.raises(ValueError, match="true or false"):
        exploration_tools_enabled()
