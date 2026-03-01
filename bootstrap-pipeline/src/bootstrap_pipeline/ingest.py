"""
Ingest adapters for the bootstrap pipeline.

Two entry points:
  ingest_repo(url)   — clone a GitHub repo to a temp dir, scan, filter, read
  ingest_local(path) — scan a local directory, filter, read

Both produce an IngestResult that the LLM reads to decide what pages to generate.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .filters import FileFilter, FilterStats
from .models import FileEntry, IngestResult, RepoMetadata, SourceType


# ============================================================================
# Public API
# ============================================================================

def ingest_repo(
    url: str,
    *,
    branch: str | None = None,
    extra_excluded_dirs: set[str] | None = None,
    extra_excluded_patterns: list[str] | None = None,
    max_file_size: int | None = None,
) -> IngestResult:
    """
    Clone a GitHub repo and produce an IngestResult.

    Args:
        url: HTTPS or SSH git URL.
        branch: Branch to clone. None = default branch.
        extra_excluded_dirs: Additional directory names to skip.
        extra_excluded_patterns: Additional glob patterns to skip.
        max_file_size: Override the default max file size in bytes.
    """
    tmp_dir = tempfile.mkdtemp(prefix="bootstrap-ingest-")
    try:
        clone_path = _clone_repo(url, tmp_dir, branch=branch)
        cloned_branch = _get_current_branch(clone_path)
        repo_name = _repo_name_from_url(url)

        file_filter = _build_filter(extra_excluded_dirs, extra_excluded_patterns, max_file_size)
        files, tree_str = _scan_and_read(clone_path, file_filter)

        metadata = _detect_repo_metadata(
            clone_path, repo_name, cloned_branch, url, file_filter.stats, files,
        )

        return IngestResult(
            source_type=SourceType.REPO,
            origin=url,
            metadata=metadata,
            files=files,
            tree=tree_str,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def ingest_local(
    path: str,
    *,
    extra_excluded_dirs: set[str] | None = None,
    extra_excluded_patterns: list[str] | None = None,
    max_file_size: int | None = None,
) -> IngestResult:
    """
    Read a local directory and produce an IngestResult.

    Args:
        path: Absolute path to directory (or a single file).
        extra_excluded_dirs: Additional directory names to skip.
        extra_excluded_patterns: Additional glob patterns to skip.
        max_file_size: Override the default max file size in bytes.
    """
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Path does not exist: {root}")

    if root.is_file():
        return _ingest_single_file(root)

    dir_name = root.name
    file_filter = _build_filter(extra_excluded_dirs, extra_excluded_patterns, max_file_size)
    files, tree_str = _scan_and_read(root, file_filter)

    metadata = RepoMetadata(
        name=dir_name,
        origin_url=None,
        total_files=file_filter.stats.total_scanned,
        included_files=file_filter.stats.included,
        excluded_files=file_filter.stats.total_scanned - file_filter.stats.included,
    )
    _enrich_metadata_from_files(metadata, files, root)

    return IngestResult(
        source_type=SourceType.LOCAL,
        origin=str(root),
        metadata=metadata,
        files=files,
        tree=tree_str,
    )


# ============================================================================
# Git operations
# ============================================================================

def _clone_repo(url: str, dest_dir: str, *, branch: str | None = None) -> Path:
    """Shallow-clone a repo into dest_dir. Returns the clone path."""
    repo_name = _repo_name_from_url(url)
    clone_path = Path(dest_dir) / repo_name

    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd += ["--branch", branch]
    cmd += [url, str(clone_path)]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(
            f"git clone failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )
    return clone_path


def _get_current_branch(repo_path: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, cwd=repo_path,
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def _repo_name_from_url(url: str) -> str:
    name = url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    return name


# ============================================================================
# Scanning and reading
# ============================================================================

def _build_filter(
    extra_dirs: set[str] | None,
    extra_patterns: list[str] | None,
    max_size: int | None,
) -> FileFilter:
    kw: dict = {}
    if extra_dirs:
        kw["extra_excluded_dirs"] = extra_dirs
    if extra_patterns:
        kw["extra_excluded_patterns"] = extra_patterns
    if max_size is not None:
        kw["max_file_size"] = max_size
    return FileFilter(**kw)


def _scan_and_read(
    root: Path,
    file_filter: FileFilter,
) -> tuple[list[FileEntry], str]:
    """
    Walk a directory tree, apply the filter, read included files, and build
    a formatted tree string.

    Returns (files, tree_string).
    """
    files: list[FileEntry] = []
    included_names_by_dir: dict[str, list[str]] = {}

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        norm_dir = "" if rel_dir == "." else rel_dir.replace("\\", "/")

        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in file_filter._excluded_dirs
        ]

        dir_included: list[str] = []
        for fname in sorted(filenames):
            rel_path = f"{norm_dir}/{fname}" if norm_dir else fname
            full_path = Path(dirpath) / fname

            try:
                size = full_path.stat().st_size
            except OSError:
                continue

            if not file_filter.should_include(rel_path, size):
                continue

            content = _safe_read(full_path)
            if content is None:
                continue

            ext = os.path.splitext(fname)[1].lstrip(".").lower()
            files.append(FileEntry(
                path=rel_path,
                content=content,
                size_bytes=size,
                extension=ext,
            ))
            dir_included.append(fname)

        included_names_by_dir[norm_dir] = dir_included

    tree_str = _build_tree(root.name, root, file_filter._excluded_dirs, included_names_by_dir)
    return files, tree_str


def _build_tree(
    root_name: str,
    root: Path,
    excluded_dirs: set[str],
    included_names_by_dir: dict[str, list[str]],
) -> str:
    """Build a clean directory tree string showing only included files."""
    lines: list[str] = [f"{root_name}/"]

    def _walk(dir_path: Path, rel_prefix: str, depth: int) -> None:
        indent = "│   " * depth
        subdirs = sorted([
            d.name for d in dir_path.iterdir()
            if d.is_dir() and d.name not in excluded_dirs
        ])
        file_names = included_names_by_dir.get(rel_prefix, [])

        entries = [(True, d) for d in subdirs] + [(False, f) for f in file_names]
        for i, (is_dir, name) in enumerate(entries):
            connector = "└── " if i == len(entries) - 1 else "├── "
            lines.append(f"{indent}{connector}{name}{'/' if is_dir else ''}")
            if is_dir:
                child_rel = f"{rel_prefix}/{name}" if rel_prefix else name
                _walk(dir_path / name, child_rel, depth + 1)

    _walk(root, "", 0)
    return "\n".join(lines)


def _safe_read(path: Path) -> str | None:
    """Read a file as UTF-8, returning None if it's binary or unreadable."""
    try:
        return path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, PermissionError, OSError):
        return None


# ============================================================================
# Metadata detection
# ============================================================================

def _detect_repo_metadata(
    root: Path,
    name: str,
    branch: str,
    url: str,
    stats: FilterStats,
    files: list[FileEntry],
) -> RepoMetadata:
    meta = RepoMetadata(
        name=name,
        default_branch=branch,
        origin_url=url,
        total_files=stats.total_scanned,
        included_files=stats.included,
        excluded_files=stats.total_scanned - stats.included,
    )
    _enrich_metadata_from_files(meta, files, root)
    return meta


def _enrich_metadata_from_files(meta: RepoMetadata, files: list[FileEntry], root: Path) -> None:
    """Set boolean flags and language detection from the file list."""
    paths = {f.path for f in files}
    extensions = {f.extension for f in files}

    meta.has_readme = any(
        f.path.lower() in ("readme.md", "readme.txt", "readme.rst", "readme")
        for f in files
    )
    meta.has_openapi = any(
        "openapi" in f.path.lower() or "swagger" in f.path.lower()
        for f in files
    )
    meta.has_dockerfile = any(
        f.path.lower().startswith("dockerfile") or f.path.lower() == "dockerfile"
        for f in files
    )
    meta.has_ci = any(
        ".github/workflows" in f.path or "Jenkinsfile" in f.path or ".gitlab-ci" in f.path
        for f in files
    )

    lang_map = {
        "py": "Python", "js": "JavaScript", "ts": "TypeScript",
        "java": "Java", "kt": "Kotlin", "go": "Go", "rs": "Rust",
        "rb": "Ruby", "php": "PHP", "cs": "C#", "swift": "Swift",
        "scala": "Scala", "cpp": "C++", "c": "C",
    }
    meta.languages = sorted({lang_map[ext] for ext in extensions if ext in lang_map})

    pm_signals = {
        "package.json": "npm",
        "pom.xml": "maven",
        "build.gradle": "gradle",
        "requirements.txt": "pip",
        "pyproject.toml": "pip",
        "Cargo.toml": "cargo",
        "go.mod": "go",
        "Gemfile": "bundler",
        "composer.json": "composer",
    }
    for filename, pm in pm_signals.items():
        if filename in paths:
            meta.package_manager = pm
            break


# ============================================================================
# Single file ingest
# ============================================================================

def _ingest_single_file(file_path: Path) -> IngestResult:
    """Handle the edge case where the user points at a single file."""
    content = _safe_read(file_path)
    if content is None:
        raise ValueError(f"Cannot read file (binary or permission error): {file_path}")

    ext = file_path.suffix.lstrip(".").lower()
    entry = FileEntry(
        path=file_path.name,
        content=content,
        size_bytes=file_path.stat().st_size,
        extension=ext,
    )
    meta = RepoMetadata(
        name=file_path.parent.name,
        total_files=1,
        included_files=1,
        excluded_files=0,
    )
    return IngestResult(
        source_type=SourceType.LOCAL,
        origin=str(file_path),
        metadata=meta,
        files=[entry],
        tree=file_path.name,
    )
