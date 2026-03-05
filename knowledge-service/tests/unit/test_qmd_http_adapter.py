"""
Unit tests for QMDAdapter in HTTP daemon mode.

Starts a minimal in-process MCP server using Python's http.server to verify
that the adapter routes search/semantic/hybrid calls to the correct MCP tools
and correctly parses the structured responses.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import patch

import pytest

from src.layer1.qmd_adapter import QMDAdapter, _QMDMcpSession


# ── Minimal fake MCP HTTP server ─────────────────────────────────────────────

FAKE_RESULT = {
    "docid": "#abc123",
    "file": "shared/guides/overview.md",
    "title": "Overview",
    "score": 0.85,
    "snippet": "An overview of the system.",
}


def make_handler(calls: list[dict[str, Any]]):
    """Return a request handler class that records tool calls and returns fake results."""

    class FakeMcpHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Silence request logging in tests

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))
            method = body.get("method", "")

            if method == "initialize":
                session_id = "test-session-001"
                response = json.dumps({
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {"protocolVersion": "2024-11-05", "capabilities": {}},
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Mcp-Session-Id", session_id)
                self.end_headers()
                self.wfile.write(response.encode())
                return

            if method == "notifications/initialized":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b"{}")
                return

            if method == "tools/call":
                params = body.get("params", {})
                calls.append({"name": params.get("name"), "args": params.get("arguments", {})})
                response = json.dumps({
                    "jsonrpc": "2.0",
                    "id": body.get("id"),
                    "result": {
                        "content": [{"type": "text", "text": "1 result"}],
                        "structuredContent": {"results": [FAKE_RESULT]},
                    },
                })
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.encode())
                return

            self.send_response(404)
            self.end_headers()

    return FakeMcpHandler


class FakeDaemon:
    """Context manager that starts/stops a fake MCP daemon on a free port."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None
        self.url = ""

    def __enter__(self) -> "FakeDaemon":
        self._server = HTTPServer(("127.0.0.1", 0), make_handler(self.calls))
        port = self._server.server_address[1]
        self.url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_: Any) -> None:
        if self._server:
            self._server.shutdown()


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestQMDAdapterHttpMode:
    """QMDAdapter routes search calls to MCP tools when QMD_DAEMON_URL is set."""

    def test_search_routes_to_search_tool(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.search("vault knowledge", collection="shared", limit=5)

        assert len(daemon.calls) == 1
        assert daemon.calls[0]["name"] == "search"
        assert daemon.calls[0]["args"]["query"] == "vault knowledge"
        assert daemon.calls[0]["args"]["collection"] == "shared"
        assert daemon.calls[0]["args"]["limit"] == 5

        assert len(results) == 1
        assert results[0].score == 0.85
        assert results[0].file_path == "shared/guides/overview.md"
        assert results[0].snippet == "An overview of the system."

    def test_semantic_search_routes_to_vector_search_tool(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.semantic_search("architecture concepts", limit=10)

        assert daemon.calls[0]["name"] == "vector_search"
        assert daemon.calls[0]["args"]["query"] == "architecture concepts"
        assert len(results) == 1

    def test_hybrid_search_routes_to_deep_search_tool(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.hybrid_search("design patterns", limit=3)

        assert daemon.calls[0]["name"] == "deep_search"
        assert daemon.calls[0]["args"]["query"] == "design patterns"
        assert daemon.calls[0]["args"]["limit"] == 3
        assert len(results) == 1

    def test_collection_extracted_from_file_path_when_not_provided(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.search("test")  # no collection kwarg

        # file is "shared/guides/overview.md" → collection extracted as "shared"
        assert results[0].collection == "shared"

    def test_search_returns_empty_on_daemon_error(self) -> None:
        # Point at a port with nothing listening
        with patch.dict("os.environ", {"QMD_DAEMON_URL": "http://127.0.0.1:19999"}):
            adapter = QMDAdapter()
            results = adapter.search("anything")

        assert results == []

    def test_semantic_search_returns_empty_on_daemon_error(self) -> None:
        with patch.dict("os.environ", {"QMD_DAEMON_URL": "http://127.0.0.1:19999"}):
            adapter = QMDAdapter()
            results = adapter.semantic_search("anything")

        assert results == []

    def test_hybrid_search_returns_empty_on_daemon_error(self) -> None:
        with patch.dict("os.environ", {"QMD_DAEMON_URL": "http://127.0.0.1:19999"}):
            adapter = QMDAdapter()
            results = adapter.hybrid_search("anything")

        assert results == []


class TestQMDAdapterSubprocessFallback:
    """Without QMD_DAEMON_URL, adapter uses subprocess mode."""

    def test_no_mcp_client_when_daemon_url_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            # Ensure QMD_DAEMON_URL is not in env
            import os
            os.environ.pop("QMD_DAEMON_URL", None)
            adapter = QMDAdapter(index_name="knowledge")
            assert adapter._mcp is None

    def test_mcp_client_created_when_daemon_url_set(self) -> None:
        with patch.dict("os.environ", {"QMD_DAEMON_URL": "http://localhost:8181"}):
            adapter = QMDAdapter()
            assert adapter._mcp is not None


class TestQMDMcpSession:
    """_QMDMcpSession initialises and makes tool calls correctly."""

    def test_initialize_sets_session_id(self) -> None:
        with FakeDaemon() as daemon:
            session = _QMDMcpSession(daemon.url)
            session._ensure_session()
            assert session._session_id == "test-session-001"

    def test_call_tool_returns_results(self) -> None:
        with FakeDaemon() as daemon:
            session = _QMDMcpSession(daemon.url)
            results = session.call_tool("search", {"query": "test", "limit": 5})
            assert len(results) == 1
            assert results[0]["file"] == "shared/guides/overview.md"

    def test_session_reused_across_calls(self) -> None:
        with FakeDaemon() as daemon:
            session = _QMDMcpSession(daemon.url)
            session.call_tool("search", {"query": "first"})
            session.call_tool("search", {"query": "second"})
            # Both calls recorded; session was not re-initialised
            assert len(daemon.calls) == 2
            assert session._session_id == "test-session-001"
