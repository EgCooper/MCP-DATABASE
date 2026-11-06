"""Server dispatch, audit logging and command line helpers."""

import asyncio
import json
import logging
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from mcp_mysql import cli, db, grants, server, setup, tickets, tools
from mcp_mysql.access import ALLOWED_TABLE_COLUMNS, INTERNAL_TABLE_COLUMNS
from mcp_mysql.server import mcp


@pytest.fixture(autouse=True)
def no_live_database(monkeypatch):
    monkeypatch.setattr(db, "get_connection", Mock(side_effect=AssertionError("No real connections")))


def test_every_call_is_audited_without_arguments_or_results(monkeypatch, caplog):
    schema = tickets.Schema({t: {c.casefold() for c in cols} for t, cols in ALLOWED_TABLE_COLUMNS.items()})
    monkeypatch.setattr(tickets, "_load_schema", lambda: schema)
    monkeypatch.setattr(db, "fetch_all", Mock(return_value=[{"company_id": 1, "name": "PRIVATE COMPANY", "status": 1}]))
    monkeypatch.setattr(db, "fetch_one", Mock(return_value=None))
    with caplog.at_level(logging.INFO, logger="mcp_mysql.audit"):
        ok = asyncio.run(mcp.call_tool("find_companies", {"name": "PRIVATE SEARCH"}))
        bad = asyncio.run(mcp.call_tool("find_companies", {"name": "x", "password": "SECRET"}))
    lines = [record.getMessage() for record in caplog.records if record.name == "mcp_mysql.audit"]
    assert len(lines) == 2
    ok_id = json.loads(ok.content[0].text)["meta"]["request_id"]
    bad_id = json.loads(bad.content[0].text)["meta"]["request_id"]
    assert f"request_id={ok_id} operation=find_companies outcome=ok" in lines[0]
    assert f"request_id={bad_id} operation=find_companies outcome=INVALID_ARGUMENTS" in lines[1]
    assert "duration_ms=" in lines[0]
    for text in ("PRIVATE", "SECRET", "password"):
        assert text not in caplog.text


def test_unknown_tool_names_are_not_logged_verbatim(caplog):
    with caplog.at_level(logging.INFO, logger="mcp_mysql.audit"):
        asyncio.run(mcp.call_tool("drop_database_now", {}))
    assert "drop_database_now" not in caplog.text
    assert "operation=unknown outcome=UNKNOWN_TOOL" in caplog.text


def test_blocking_database_work_does_not_freeze_the_event_loop(monkeypatch):
    def slow_connection_check():
        time.sleep(0.3)
        return tools.encode_response({"status": "connected"})

    monkeypatch.setattr(tools, "test_connection", slow_connection_check)

    async def scenario():
        ticks = 0

        async def ticker():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.01)
                ticks += 1

        task = asyncio.create_task(ticker())
        result = await mcp.call_tool("test_connection", {})
        task.cancel()
        return result, ticks

    result, ticks = asyncio.run(scenario())
    assert result.isError is False
    assert ticks >= 10


def test_every_tool_has_a_description_schema_and_read_only_annotation():
    definitions = asyncio.run(mcp.list_tools())
    for tool in definitions:
        assert tool.description and len(tool.description) < 1024
        assert tool.annotations.readOnlyHint is True and tool.annotations.destructiveHint is False
    assert len(server.INSTRUCTIONS) < 6000


# Command line ----------------------------------------------------------------------------------------

def test_setup_subcommand_is_routed_and_requests_stdio(capsys):
    cli.main(["setup", "--print"])
    snippet = json.loads(capsys.readouterr().out.split("\n\n", 1)[0])
    entry = snippet["mcpServers"]["mysql"]
    assert entry["args"] == ["-m", "mcp_mysql", "--transport", "stdio"]
    assert Path(entry["command"]).name.startswith("python")


def test_setup_prints_a_claude_code_command_instead_of_editing_its_config(capsys, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cli.main(["setup", "--client", "claude-code"])
    command = capsys.readouterr().out.strip()
    assert command.startswith("claude mcp add mysql -s user -- ")
    assert command.endswith("-m mcp_mysql --transport stdio")
    assert list(tmp_path.iterdir()) == []


def test_setup_merges_into_an_existing_config_without_touching_other_servers(tmp_path, capsys):
    target = tmp_path / "mcp.json"
    target.write_text(json.dumps({"mcpServers": {"other": {"command": "x"}}, "theme": "dark"}))
    cli.main(["setup", "--path", str(target)])
    config = json.loads(target.read_text())
    assert config["theme"] == "dark" and config["mcpServers"]["other"] == {"command": "x"}
    assert config["mcpServers"]["mysql"]["args"][-2:] == ["--transport", "stdio"]


def test_server_is_the_default_command(monkeypatch):
    run = Mock()
    monkeypatch.setattr(server, "main", run)
    cli.main(["--transport", "stdio"])
    run.assert_called_once_with(["--transport", "stdio"])


def test_grants_cover_exactly_the_policy_columns(capsys):
    cli.main(["grants", "--database", "osticket", "--user", "mcp_readonly", "--host", "172.18.%"])
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("GRANT")]
    tables = {**ALLOWED_TABLE_COLUMNS, **INTERNAL_TABLE_COLUMNS}
    assert len(lines) == len(tables)
    for line in lines:
        assert line.startswith("GRANT SELECT (") and line.endswith("TO 'mcp_readonly'@'172.18.%';")
    staff = next(line for line in lines if "`ost_staff`" in line)
    assert "`passwd`" not in staff and "`email`" not in staff and "`firstname`" in staff
    assert not any(word in "\n".join(lines) for word in ("INSERT", "UPDATE", "DELETE", "ALL PRIVILEGES", "*.*"))


@pytest.mark.parametrize("options", [
    ["--database", "osticket`; DROP DATABASE x; --"], ["--database", "osticket", "--user", "a'b"],
    ["--database", "osticket", "--host", "evil' OR 1"],
])
def test_grants_reject_names_that_could_inject_sql(options, capsys):
    with pytest.raises(SystemExit):
        grants.main(options)
    assert "GRANT" not in capsys.readouterr().out


def test_setup_entry_has_no_credentials(tmp_path):
    entry = setup.mysql_server_entry(tmp_path, Path("/usr/bin/python3"))
    assert set(entry) == {"command", "args", "cwd"}


# HTTP gate --------------------------------------------------------------------------------------

import httpx

from mcp_mysql.config import mcp_allowed_hosts, mcp_auth_token

TOKEN = "t" * 40


async def _echo_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"reached"})


def _request(gate, method="POST", path="/mcp", headers=None):
    async def call():
        transport = httpx.ASGITransport(app=gate)
        async with httpx.AsyncClient(transport=transport, base_url="http://mcp-osticket:8000") as client:
            return await client.request(method, path, headers=headers or {})
    return asyncio.run(call())


@pytest.mark.parametrize("headers", [
    {}, {"Authorization": "Bearer wrong"}, {"Authorization": TOKEN}, {"Authorization": f"Basic {TOKEN}"},
    {"Authorization": f"Bearer {TOKEN}x"}, {"X-Token": TOKEN},
])
def test_gate_rejects_missing_or_wrong_tokens_without_logging_them(headers, caplog):
    with caplog.at_level(logging.WARNING, logger="mcp_mysql.security"):
        response = _request(server.HttpGate(_echo_app, TOKEN), headers=headers)
    assert response.status_code == 401 and response.text != "reached"
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert "http_unauthorized" in caplog.text and TOKEN not in caplog.text and "wrong" not in caplog.text


def test_gate_passes_the_correct_token_through():
    response = _request(server.HttpGate(_echo_app, TOKEN), headers={"Authorization": f"Bearer {TOKEN}"})
    assert response.status_code == 200 and response.text == "reached"


def test_health_needs_no_token_and_never_reaches_the_mcp_app():
    gate = server.HttpGate(_echo_app, TOKEN)
    response = _request(gate, method="GET", path="/health")
    assert response.status_code == 200 and response.json() == {"status": "ok"}
    assert _request(gate, method="POST", path="/health").status_code == 405


def test_real_mcp_endpoint_requires_the_token():
    app = server.build_http_app("0.0.0.0", 8000, ["mcp-osticket:*"], TOKEN)
    response = _request(app, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"})
    assert response.status_code == 401


@pytest.mark.parametrize("host", ["0.0.0.0", "172.17.0.1", "10.0.0.5", "mcp-osticket"])
def test_non_loopback_http_without_a_token_refuses_to_start(monkeypatch, host):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    with pytest.raises(SystemExit, match="MCP_AUTH_TOKEN is required"):
        server.main(["--host", host])
    run.assert_not_called()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_loopback_http_may_run_without_a_token(monkeypatch, host):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    server.main(["--host", host, "--port", "8123"])
    assert run.call_args.kwargs["host"] == host and run.call_args.kwargs["port"] == 8123


def test_explicit_opt_out_allows_a_controlled_unauthenticated_test(monkeypatch):
    monkeypatch.delenv("MCP_AUTH_TOKEN", raising=False)
    run = Mock()
    monkeypatch.setattr("uvicorn.run", run)
    server.main(["--host", "172.17.0.1", "--allow-unauthenticated"])
    assert isinstance(run.call_args.args[0], server.HttpGate)


@pytest.mark.parametrize("value", ["short", "x" * 31, "x" * 20 + " " + "y" * 20, "ñ" * 40])
def test_weak_or_malformed_tokens_are_rejected(monkeypatch, value):
    monkeypatch.setenv("MCP_AUTH_TOKEN", value)
    with pytest.raises(ValueError, match="MCP_AUTH_TOKEN"):
        mcp_auth_token()


def test_token_and_allowed_hosts_are_read_from_environment(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_TOKEN", f"  {TOKEN}  ")
    monkeypatch.setenv("MCP_ALLOWED_HOSTS", "mcp-osticket:*, otro:8000 ,")
    assert mcp_auth_token() == TOKEN
    assert mcp_allowed_hosts() == ["mcp-osticket:*", "otro:8000"]


def test_image_build_context_excludes_secrets():
    ignored = Path(__file__).resolve().parents[1].joinpath(".dockerignore").read_text().splitlines()
    assert ".env" in ignored and ".git" in ignored and ".venv" in ignored
