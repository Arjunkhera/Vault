"""
Integration tests for the Vault Knowledge Service REST API.

Uses FastAPI TestClient with a MockSearchStore to test all 5 endpoints end-to-end.
Creates a separate FastAPI app without the lifespan (which requires QMD).
"""

import pytest
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from fastapi.responses import JSONResponse

from src.errors import VaultError
from src.api.routes import router, get_store
from tests.conftest import MockSearchStore, SAMPLE_PAGES


def _create_test_app() -> tuple[FastAPI, MockSearchStore]:
    """Create a test FastAPI app with MockSearchStore, no lifespan."""
    mock_store = MockSearchStore(documents=dict(SAMPLE_PAGES))

    test_app = FastAPI(title="Vault Knowledge Service Test")

    @test_app.exception_handler(VaultError)
    async def vault_error_handler(request: Request, exc: VaultError):
        from src.errors import ErrorCode
        mapping = {
            ErrorCode.PAGE_NOT_FOUND: 404,
            ErrorCode.TYPE_NOT_FOUND: 404,
            ErrorCode.VALIDATION_ERROR: 422,
            ErrorCode.SEARCH_ERROR: 502,
        }
        return JSONResponse(
            status_code=mapping.get(exc.code, 500),
            content=exc.to_dict()
        )

    def get_store_override():
        return mock_store

    test_app.dependency_overrides[get_store] = get_store_override
    test_app.include_router(router, prefix="", tags=["knowledge"])
    test_app.state.store = mock_store

    @test_app.get("/health")
    async def health_check(request: Request):
        store = request.app.state.store
        return JSONResponse(
            status_code=200,
            content={
                "status": "ok",
                "service": "vault-knowledge-service",
                "version": "0.2.0",
                "index": store.status()
            }
        )

    @test_app.get("/")
    async def root():
        return {
            "service": "Vault Knowledge Service",
            "version": "0.2.0",
            "endpoints": {
                "resolve_context": "POST /resolve-context",
                "search": "POST /search",
                "get_page": "POST /get-page",
                "get_related": "POST /get-related",
                "list_by_scope": "POST /list-by-scope"
            },
        }

    return test_app, mock_store


@pytest.fixture
def client():
    """Create a test client with MockSearchStore injected."""
    test_app, _ = _create_test_app()
    with TestClient(test_app) as client:
        yield client


class TestHealthEndpoint:
    def test_health_check(self, client):
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["service"] == "vault-knowledge-service"


class TestRootEndpoint:
    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "Vault Knowledge Service"
        assert "resolve_context" in data["endpoints"]


class TestResolveContext:
    def test_resolve_context_for_anvil(self, client):
        response = client.post("/resolve-context", json={"repo": "anvil"})
        assert response.status_code == 200
        data = response.json()

        # Should have entry point (anvil repo-profile)
        assert data["entry_point"] is not None
        assert data["entry_point"]["title"] == "Anvil"

        # Should have scope
        assert data["scope"]["repo"] == "anvil"
        assert data["scope"]["program"] == "anvil-forge-vault"

        # Should have operational pages
        assert len(data["operational_pages"]) > 0

    def test_resolve_context_unknown_repo(self, client):
        response = client.post("/resolve-context", json={"repo": "nonexistent"})
        assert response.status_code == 200
        data = response.json()
        assert data["entry_point"] is None
        assert data["scope"]["repo"] == "nonexistent"

    def test_resolve_context_include_full(self, client):
        response = client.post("/resolve-context", json={
            "repo": "anvil",
            "include_full": True,
        })
        assert response.status_code == 200
        data = response.json()
        # Full pages should have body field
        for page in data["operational_pages"]:
            assert "body" in page


class TestSearch:
    def test_search_basic(self, client):
        response = client.post("/search", json={"query": "anvil"})
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        assert len(data["results"]) > 0

    def test_search_with_mode_filter(self, client):
        response = client.post("/search", json={
            "query": "anvil",
            "mode": "operational",
        })
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["mode"] == "operational"

    def test_search_with_type_filter(self, client):
        response = client.post("/search", json={
            "query": "anvil",
            "type": "repo-profile",
        })
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["type"] == "repo-profile"

    def test_search_with_scope_filter(self, client):
        response = client.post("/search", json={
            "query": "anvil",
            "scope": {"repo": "anvil"},
        })
        assert response.status_code == 200
        data = response.json()
        for result in data["results"]:
            assert result["scope"].get("repo") == "anvil"

    def test_search_with_limit(self, client):
        response = client.post("/search", json={
            "query": "anvil",
            "limit": 2,
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["results"]) <= 2


class TestGetPage:
    def test_get_existing_page(self, client):
        response = client.post("/get-page", json={"id": "repos/anvil.md"})
        assert response.status_code == 200
        data = response.json()
        assert data["title"] == "Anvil"
        assert data["body"] is not None
        assert "# Anvil" in data["body"]

    def test_get_nonexistent_page(self, client):
        response = client.post("/get-page", json={"id": "nonexistent.md"})
        assert response.status_code == 404


class TestGetRelated:
    def test_get_related_from_anvil(self, client):
        response = client.post("/get-related", json={"id": "repos/anvil.md"})
        assert response.status_code == 200
        data = response.json()
        assert data["source"]["title"] == "Anvil"
        assert len(data["related"]) > 0

    def test_get_related_nonexistent(self, client):
        response = client.post("/get-related", json={"id": "nonexistent.md"})
        assert response.status_code == 404


class TestListByScope:
    def test_list_by_program(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"program": "anvil-forge-vault"},
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0
        for page in data["pages"]:
            assert page["scope"].get("program") == "anvil-forge-vault"

    def test_list_by_repo(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"repo": "anvil"},
        })
        assert response.status_code == 200
        data = response.json()
        assert data["total"] > 0

    def test_list_by_scope_with_mode_filter(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"program": "anvil-forge-vault"},
            "mode": "operational",
        })
        assert response.status_code == 200
        data = response.json()
        for page in data["pages"]:
            assert page["mode"] == "operational"

    def test_list_by_scope_with_type_filter(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"program": "anvil-forge-vault"},
            "type": "repo-profile",
        })
        assert response.status_code == 200
        data = response.json()
        for page in data["pages"]:
            assert page["type"] == "repo-profile"

    def test_list_by_scope_with_tags(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"program": "anvil-forge-vault"},
            "tags": ["core"],
        })
        assert response.status_code == 200
        data = response.json()
        for page in data["pages"]:
            assert "core" in page["tags"]

    def test_list_with_limit(self, client):
        response = client.post("/list-by-scope", json={
            "scope": {"program": "anvil-forge-vault"},
            "limit": 2,
        })
        assert response.status_code == 200
        data = response.json()
        assert len(data["pages"]) <= 2
