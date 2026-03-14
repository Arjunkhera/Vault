"""
GitWriter — Handles git operations for the write-path: branch creation, commit, push, and PR creation.

Used by the /write-page endpoint to atomically:
1. Create a feature branch from base
2. Write page content to disk
3. Commit changes
4. Push to GitHub
5. Create a pull request for review

All operations are synchronous (blocking) — called via asyncio.to_thread() in the API handler.
"""

import subprocess
import uuid as uuid_lib
from pathlib import Path
from typing import Optional

from ..errors import git_error, github_api_error


class GitWriter:
    """
    Manages git operations for writing pages to the knowledge-base repository.

    Synchronous API — designed to be called via asyncio.to_thread() to avoid blocking the event loop.
    """

    def __init__(
        self,
        repo_path: str,
        github_token: str,
        github_repo: str,
        base_branch: str = "master"
    ) -> None:
        """
        Initialize GitWriter.

        Args:
            repo_path: Path to the knowledge-base git repository
            github_token: GitHub personal access token (with repo scope)
            github_repo: GitHub repo in format "owner/repo" (e.g., "arkhera/knowledge-base")
            base_branch: Base branch to branch from (default: "master")
        """
        self.repo_path = repo_path
        self.github_token = github_token
        self.github_repo = github_repo
        self.base_branch = base_branch

    def _inject_uuid_if_missing(self, content: str) -> str:
        """
        Ensure the page content has an `id` field in its YAML frontmatter.

        If the frontmatter already contains an `id` key, the content is returned
        unchanged. Otherwise, a UUIDv4 is generated and inserted as the first
        field in the frontmatter block.

        Args:
            content: Full markdown content with YAML frontmatter

        Returns:
            Content with `id` guaranteed to be present in frontmatter
        """
        # Quick check: if "id:" appears in the frontmatter, skip injection
        if content.startswith("---"):
            closing = content.find("---", 3)
            if closing != -1:
                frontmatter_block = content[3:closing]
                for line in frontmatter_block.splitlines():
                    if line.startswith("id:") or line.startswith("id :"):
                        return content  # id already present

        # Inject id as the first frontmatter field
        new_id = str(uuid_lib.uuid4())
        if content.startswith("---"):
            lines = content.split("\n", 2)
            content = lines[0] + "\n" + f"id: {new_id}" + "\n" + "\n".join(lines[1:])
        else:
            content = f"---\nid: {new_id}\n---\n" + content
        return content

    def write_page(
        self,
        page_path: str,
        content: str,
        branch: str,
        commit_message: str,
        pr_title: str,
        pr_body: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Write a page to a feature branch and create a GitHub PR.

        Steps:
        1. Ensure content has a UUID in frontmatter (inject if missing)
        2. Checkout base_branch (ensure clean state)
        3. Create and checkout feature branch
        4. Write page content to disk
        5. Stage and commit
        6. Push to origin
        7. Create PR via GitHub API
        8. Return to base_branch

        Args:
            page_path: Relative path within repo (e.g., "repos/anvil.md")
            content: Full markdown content with YAML frontmatter
            branch: Feature branch name to create
            commit_message: Git commit message
            pr_title: GitHub PR title
            pr_body: GitHub PR description body

        Returns:
            Tuple of (pr_url, commit_sha)

        Raises:
            VaultError(GIT_ERROR) if git operations fail
            VaultError(GITHUB_API_ERROR) if PR creation fails
        """
        # Stamp UUID into frontmatter for new pages (no-op if already present)
        content = self._inject_uuid_if_missing(content)

        try:
            # Ensure we're on a clean base
            self._git("checkout", self.base_branch)

            # Create and checkout feature branch
            self._git("checkout", "-b", branch)

            # Write page to disk
            self._write_file(page_path, content)

            # Stage the change
            self._git("add", page_path)

            # Commit
            self._git("commit", "-m", commit_message)

            # Get the commit SHA
            commit_sha = self._git("rev-parse", "HEAD")

            # Push to origin
            self._git("push", "origin", branch)

            # Create PR via GitHub API
            pr_url = self._create_pr(branch, pr_title, pr_body or "")

            # Return to base branch
            self._git("checkout", self.base_branch)

            return pr_url, commit_sha

        except Exception as e:
            # If something goes wrong, try to return to base_branch
            try:
                self._git("checkout", self.base_branch)
            except Exception:
                pass  # Ignore cleanup errors
            raise

    def _git(self, *args: str) -> str:
        """
        Run a git command.

        Args:
            *args: Git command and arguments

        Returns:
            Command stdout (stripped)

        Raises:
            VaultError(GIT_ERROR) if git command fails
        """
        try:
            result = subprocess.run(
                ["git", "-C", str(self.repo_path)] + list(args),
                capture_output=True,
                text=True,
                check=True,
            )
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise git_error(
                f"Git command failed: {' '.join(args)}",
                {
                    "command": " ".join(args),
                    "returncode": e.returncode,
                    "stderr": e.stderr,
                    "stdout": e.stdout,
                }
            )

    def _write_file(self, page_path: str, content: str) -> None:
        """
        Write page content to disk, creating parent directories as needed.

        Args:
            page_path: Relative path within repo
            content: Full markdown content with YAML frontmatter

        Raises:
            VaultError(GIT_ERROR) if write fails
        """
        try:
            target = Path(self.repo_path) / page_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        except Exception as e:
            raise git_error(
                f"Failed to write page: {page_path}",
                {
                    "path": page_path,
                    "error": str(e),
                }
            )

    def _create_pr(self, branch: str, title: str, body: str) -> str:
        """
        Create a GitHub pull request via the REST API.

        Args:
            branch: Feature branch name (will be merged into base_branch)
            title: PR title
            body: PR description

        Returns:
            GitHub PR URL

        Raises:
            VaultError(GITHUB_API_ERROR) if PR creation fails
        """
        try:
            import httpx
        except ImportError:
            raise github_api_error("httpx library not available")

        try:
            url = f"https://api.github.com/repos/{self.github_repo}/pulls"
            headers = {
                "Authorization": f"Bearer {self.github_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
            payload = {
                "title": title,
                "body": body,
                "head": branch,
                "base": self.base_branch,
            }

            response = httpx.post(url, json=payload, headers=headers, timeout=30.0)
            response.raise_for_status()

            result = response.json()
            html_url = result["html_url"]
            assert isinstance(html_url, str)
            return html_url

        except httpx.HTTPStatusError as e:
            raise github_api_error(
                f"GitHub API returned {e.response.status_code}",
                {
                    "status_code": e.response.status_code,
                    "response": e.response.text,
                }
            )
        except Exception as e:
            raise github_api_error(
                f"PR creation failed: {e}",
                {"error": str(e)}
            )
