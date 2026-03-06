"""
Tests for knowledge_write_page collection prefix stripping.

Covers Bug 47c4f206: write-page double-prefixes path when caller passes
ID format (e.g. "shared/repos/foo.md") instead of bare path.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.api.routes import _write_page_sync
from src.api.models import WritePageRequest
from src.layer2.schema import SchemaLoader


VALID_CONTENT = """---
type: repo-profile
title: Foo Repo
description: A test repository for unit testing write-page path handling
scope:
  repo: foo
  program: test-program
mode: reference
tags: [test]
owner: tester
---
# Foo Repo

Test content.
"""


@pytest.fixture
def mock_loader():
    loader = MagicMock(spec=SchemaLoader)
    loader.page_types = {"repo-profile": MagicMock()}
    validator_result = MagicMock()
    validator_result.valid = True
    validator_result.errors = []
    with patch("src.api.routes.PageValidator") as MockValidator:
        MockValidator.return_value.validate.return_value = validator_result
        yield loader


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.github_token = "fake-token"
    settings.github_repo = "owner/repo"
    settings.github_base_branch = "main"
    settings.knowledge_repo_path = "/fake/repo"
    return settings


class TestWritePagePathStripping:
    def _run(self, path, mock_loader, mock_settings):
        request = WritePageRequest(path=path, content=VALID_CONTENT)
        with patch("src.api.routes.PageValidator") as MockValidator, \
             patch("src.api.routes.GitWriter") as MockWriter:
            validator_result = MagicMock()
            validator_result.valid = True
            validator_result.errors = []
            MockValidator.return_value.validate.return_value = validator_result
            MockWriter.return_value.write_page.return_value = ("https://github.com/pr/1", "abc123")
            _write_page_sync(request, mock_loader, mock_settings)
            return MockWriter.return_value.write_page.call_args

    def test_shared_prefix_stripped(self, mock_loader, mock_settings):
        call_args = self._run("shared/repos/foo.md", mock_loader, mock_settings)
        page_path = call_args.kwargs.get("page_path") or call_args[1].get("page_path") or call_args[0][0]
        assert page_path == "repos/foo.md"

    def test_workspace_prefix_stripped(self, mock_loader, mock_settings):
        call_args = self._run("workspace/docs/bar.md", mock_loader, mock_settings)
        page_path = call_args.kwargs.get("page_path") or call_args[1].get("page_path") or call_args[0][0]
        assert page_path == "docs/bar.md"

    def test_bare_path_unchanged(self, mock_loader, mock_settings):
        call_args = self._run("repos/foo.md", mock_loader, mock_settings)
        page_path = call_args.kwargs.get("page_path") or call_args[1].get("page_path") or call_args[0][0]
        assert page_path == "repos/foo.md"

    def test_nested_shared_not_double_stripped(self, mock_loader, mock_settings):
        """Only the leading prefix is stripped — 'shared/' inside the path is preserved."""
        call_args = self._run("shared/shared/repos/foo.md", mock_loader, mock_settings)
        page_path = call_args.kwargs.get("page_path") or call_args[1].get("page_path") or call_args[0][0]
        assert page_path == "shared/repos/foo.md"

    def test_response_path_uses_stripped_path(self, mock_loader, mock_settings):
        request = WritePageRequest(path="shared/repos/foo.md", content=VALID_CONTENT)
        with patch("src.api.routes.PageValidator") as MockValidator, \
             patch("src.api.routes.GitWriter") as MockWriter:
            validator_result = MagicMock()
            validator_result.valid = True
            validator_result.errors = []
            MockValidator.return_value.validate.return_value = validator_result
            MockWriter.return_value.write_page.return_value = ("https://github.com/pr/1", "abc123")
            response = _write_page_sync(request, mock_loader, mock_settings)
        assert response.path == "repos/foo.md"
