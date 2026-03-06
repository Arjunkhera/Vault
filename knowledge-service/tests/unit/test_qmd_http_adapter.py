"""
Unit tests for QMDAdapter in HTTP daemon mode.

Starts a minimal in-process REST server using Python's http.server to verify
that the adapter routes search/semantic/hybrid calls to the correct REST
endpoints and correctly parses the structured responses.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any
from unittest.mock import patch

import pytest

from src.layer1.qmd_adapter import QMDAdapter, _QMDRestClient


# ── Minimal fake QMD REST server ─────────────────────────────────────────────

FAKE_RESULT = {
    "docid": "#abc123",
    "file": "shared/guides/overview.md",
    "title": "Overview",
    "score": 0.85,
    "snippet": "An overview of the system.",
}


def make_handler(calls: list[dict[str, Any]]):
    """Return a request handler class that records /query calls and returns fake results."""

    class FakeRestHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            pass  # Silence request logging in tests

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length))

            if self.path == "/query":
                calls.append({
                    "searches": body.get("searches", []),
                    "limit": body.get("limit"),
                    "collections": body.get("collections"),
                })
                response = json.dumps({"results": [FAKE_RESULT]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(response.encode())
                return

            self.send_response(404)
            self.end_headers()

    return FakeRestHandler


class FakeDaemon:
    """Context manager that starts/stops a fake QMD REST daemon on a free port."""

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
    """QMDAdapter routes search calls to REST /query when QMD_DAEMON_URL is set."""

    def test_search_sends_lex_query(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.search("vault knowledge", collection="shared", limit=5)

        assert len(daemon.calls) == 1
        assert daemon.calls[0]["searches"] == [{"type": "lex", "query": "vault knowledge"}]
        assert daemon.calls[0]["collections"] == ["shared"]
        assert daemon.calls[0]["limit"] == 5

        assert len(results) == 1
        assert results[0].score == 0.85
        assert results[0].file_path == "shared/guides/overview.md"
        assert results[0].snippet == "An overview of the system."

    def test_semantic_search_sends_vec_query(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.semantic_search("architecture concepts", limit=10)

        assert daemon.calls[0]["searches"] == [{"type": "vec", "query": "architecture concepts"}]
        assert daemon.calls[0]["collections"] is None  # no collection filter
        assert len(results) == 1

    def test_hybrid_search_sends_lex_and_vec(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.hybrid_search("design patterns", limit=3)

        assert daemon.calls[0]["searches"] == [
            {"type": "lex", "query": "design patterns"},
            {"type": "vec", "query": "design patterns"},
        ]
        assert daemon.calls[0]["limit"] == 3
        assert len(results) == 1

    def test_collection_extracted_from_file_path_when_not_provided(self) -> None:
        with FakeDaemon() as daemon:
            with patch.dict("os.environ", {"QMD_DAEMON_URL": daemon.url}):
                adapter = QMDAdapter()
                results = adapter.search("test")  # no collection kwarg

        # file is "shared/guides/overview.md" -> collection extracted as "shared"
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

    def test_no_rest_client_when_daemon_url_unset(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            # Ensure QMD_DAEMON_URL is not in env
            import os
            os.environ.pop("QMD_DAEMON_URL", None)
            adapter = QMDAdapter(index_name="knowledge")
            assert adapter._rest is None

    def test_rest_client_created_when_daemon_url_set(self) -> None:
        with patch.dict("os.environ", {"QMD_DAEMON_URL": "http://localhost:8181"}):
            adapter = QMDAdapter()
            assert adapter._rest is not None


class TestQMDRestClient:
    """_QMDRestClient sends correct requests to /query."""

    def test_search_posts_to_query_endpoint(self) -> None:
        with FakeDaemon() as daemon:
            client = _QMDRestClient(daemon.url)
            results = client.search("test", "lex", limit=5)
            assert len(results) == 1
            assert results[0]["file"] == "shared/guides/overview.md"

    def test_multi_search_sends_multiple_sub_queries(self) -> None:
        with FakeDaemon() as daemon:
            client = _QMDRestClient(daemon.url)
            results = client.multi_search(
                [{"type": "lex", "query": "first"}, {"type": "vec", "query": "second"}],
                limit=10,
            )
            assert len(results) == 1
            assert daemon.calls[0]["searches"] == [
                {"type": "lex", "query": "first"},
                {"type": "vec", "query": "second"},
            ]
