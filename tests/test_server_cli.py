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
