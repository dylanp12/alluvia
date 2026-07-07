import asyncio
import pytest


def test_tools_register_over_inmemory_transport(repo, monkeypatch, tmp_path):
    monkeypatch.setenv("SIFT_DB", str(tmp_path / "mcp.db"))
    mem = pytest.importorskip("mcp.shared.memory")
    from alluvia.mcp_server import build_server

    server = build_server()

    async def main():
        async with mem.create_connected_server_and_client_session(
                server._mcp_server) as client:
            tools = await client.list_tools()
            names = {t.name for t in tools.tools}
            assert {"recall_themes", "find_connections", "unfinished_threads",
                    "show_source", "list_proposals", "propose_next",
                    "rate_proposal", "get_digest"} <= names

    try:
        asyncio.run(main())
    except (AttributeError, TypeError) as e:            # SDK surface drift
        pytest.skip(f"in-memory transport unavailable in this SDK version: {e}")
