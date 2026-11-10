"""Real TCP Streamable HTTP protocol with the SDK client; no live database."""

import asyncio
import json
import socket

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
import uvicorn

from mcp_mysql import server, tools
from mcp_mysql.validation import EXPLORATION_TOOLS, TOOL_ARGUMENT_MODELS


def test_sdk_http_initialization_tools_call_auth_and_session_shutdown(monkeypatch):
    monkeypatch.setenv("MCP_ENABLE_EXPLORATION_TOOLS", "false")
    monkeypatch.setattr(tools, "test_connection", lambda: tools.encode_response({"status": "connected"}))
    token = "http-integration-only-token-1234567890"

    async def scenario():
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
            app = server.build_http_app("127.0.0.1", port, [], token)
            deleted = []

            async def observed(scope, receive, send):
                async def record(message):
                    if scope.get("method") == "DELETE" and message["type"] == "http.response.start":
                        deleted.append(message["status"])
                    await send(message)
                await app(scope, receive, record)

            process = uvicorn.Server(uvicorn.Config(observed, log_level="warning", lifespan="on",
                                                   timeout_graceful_shutdown=3))
            task = asyncio.create_task(process.serve(sockets=[listener]))
            try:
                async def ready():
                    while not process.started:
                        if task.done():
                            await task
                            raise AssertionError("HTTP server exited before startup")
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(ready(), 5)
                base = f"http://127.0.0.1:{port}"
                async with httpx.AsyncClient(timeout=5) as client:
                    assert (await client.get(base + "/health")).json() == {"status": "ok"}
                    for auth in (None, "Bearer wrong"):
                        response = await client.post(base + "/mcp", headers={"Authorization": auth} if auth else {})
                        assert response.status_code == 401
                async with httpx.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=5) as client:
                    async with streamable_http_client(base + "/mcp", http_client=client) as (read, write, session_id):
                        async with ClientSession(read, write) as session:
                            initialized = await session.initialize()
                            assert initialized.serverInfo.name == "mcp-mysql"
                            definitions = (await session.list_tools()).tools
                            assert {tool.name for tool in definitions} == set(TOOL_ARGUMENT_MODELS) - EXPLORATION_TOOLS
                            assert len(definitions) == 13 and session_id()
                            result = await session.call_tool("test_connection", {})
                            assert not result.isError
                            assert json.loads(result.content[0].text)["data"]["status"] == "connected"
                            invalid = await session.call_tool("get_user", {"user_id": 1, "emails_offset": -1})
                            assert invalid.isError and json.loads(invalid.content[0].text)["error"]["code"] == "INVALID_ARGUMENTS"
                    assert deleted == [200]
            finally:
                process.should_exit = True
                await asyncio.wait_for(task, 5)

    asyncio.run(asyncio.wait_for(scenario(), 20))
