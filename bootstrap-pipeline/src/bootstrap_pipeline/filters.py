"""
File exclusion filters for the ingest stage.

Applies gitignore-style patterns to skip files that would waste LLM tokens
(lock files, node_modules, binaries, vendor dirs, etc.).

The defaults are intentionally aggressive — it's better to miss a file the
agent can request later than to blow the context window with package-lock.json.
"""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass, field


EXCLUDED_DIRS: set[str] = {
    "node_modules",
    ".git",
    ".svn",
    ".hg",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "venv",
    "env",
    ".env",
    "dist",
    "build",
    "out",
    "target",
    ".next",
    ".nuxt",
    ".output",
    ".cache",
    ".gradle",
    ".idea",
    ".vscode",
    ".settings",
    "vendor",
    "bower_components",
    "coverage",
    ".nyc_output",
    ".terraform",
    ".serverless",
    "cdk.out",
}

EXCLUDED_EXTENSIONS: set[str] = {
    # Lock / dependency files
    "lock",
    # Compiled / binary
    "pyc", "pyo", "class", "o", "so", "dylib", "dll", "exe",
    "wasm", "jar", "war", "ear",
    # Archives
    "zip", "tar", "gz", "bz2", "xz", "7z", "rar",
    # Images / media
    "png", "jpg", "jpeg", "gif", "bmp", "ico", "svg", "webp",
    "mp3", "mp4", "wav", "avi", "mov", "webm",
    # Fonts
    "woff", "woff2", "ttf", "eot", "otf",
    # Data blobs
    "db", "sqlite", "sqlite3",
    # IDE / OS
    "DS_Store",
    # Minified
    "min.js", "min.css",
    # Maps
    "map",
}

EXCLUDED_FILENAMES: set[str] = {
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "Pipfile.lock",
    "composer.lock",
    "Gemfile.lock",
    "go.sum",
    ".gitignore",
    ".gitattributes",
    ".editorconfig",
    ".prettierrc",
    ".eslintignore",
    ".npmrc",
    ".nvmrc",
    ".python-version",
    "thumbs.db",
    ".DS_Store",
}

MAX_FILE_SIZE_BYTES: int = 100_000  # 100 KB — files larger than this are likely not prose

INCLUDED_EXTENSIONS: set[str] = {
    "md", "mdx", "txt", "rst",
    "py", "js", "ts", "tsx", "jsx",
    "java", "kt", "scala", "go", "rs",
    "rb", "php", "cs", "swift", "m",
    "c", "cpp", "h", "hpp",
    "sh", "bash", "zsh", "fish",
    "yaml", "yml", "json", "toml", "ini", "cfg", "conf",
    "xml", "html", "css", "scss", "less",
    "sql",
    "proto", "graphql", "gql",
    "tf", "hcl",
    "dockerfile",
    "makefile",
    "gradle",
    "properties",
}


@dataclass
class FilterStats:
    """Tracks what the filter included and excluded."""
    total_scanned: int = 0
    included: int = 0
    excluded_by_dir: int = 0
    excluded_by_extension: int = 0
    excluded_by_filename: int = 0
    excluded_by_size: int = 0
    excluded_by_allowlist: int = 0


@dataclass
class FileFilter:
    """
    Decides whether a file should be included in the ingest output.

    Uses a layered strategy:
    1. Skip entire directories (node_modules, .git, etc.)
    2. Skip by filename (lock files, OS files)
    3. Skip by extension (binaries, images, etc.)
    4. Skip files larger than the size limit
    5. If an allowlist is active (default: INCLUDED_EXTENSIONS), only keep those
    6. Apply any additional user-provided glob patterns

    The caller can extend defaults via extra_excluded_dirs, extra_excluded_patterns,
    or override the allowlist entirely.
    """
    extra_excluded_dirs: set[str] = field(default_factory=set)
    extra_excluded_patterns: list[str] = field(default_factory=list)
    max_file_size: int = MAX_FILE_SIZE_BYTES
    use_allowlist: bool = True
    stats: FilterStats = field(default_factory=FilterStats)

    @property
    def _excluded_dirs(self) -> set[str]:
        return EXCLUDED_DIRS | self.extra_excluded_dirs

    def should_include(self, rel_path: str, size_bytes: int) -> bool:
        """Return True if the file should be included in the ingest output."""
        self.stats.total_scanned += 1

        parts = rel_path.replace("\\", "/").split("/")

        for part in parts[:-1]:
            if part in self._excluded_dirs:
                self.stats.excluded_by_dir += 1
                return False

        filename = parts[-1]

        if filename in EXCLUDED_FILENAMES:
            self.stats.excluded_by_filename += 1
            return False

        ext = _get_extension(filename)
        if ext in EXCLUDED_EXTENSIONS:
            self.stats.excluded_by_extension += 1
            return False

        if size_bytes > self.max_file_size:
            self.stats.excluded_by_size += 1
            return False

        if self.use_allowlist:
            matchable_name = filename.lower()
            name_no_ext = os.path.splitext(matchable_name)[0]
            if ext not in INCLUDED_EXTENSIONS and name_no_ext not in INCLUDED_EXTENSIONS:
                self.stats.excluded_by_allowlist += 1
                return False

        for pattern in self.extra_excluded_patterns:
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(filename, pattern):
                self.stats.excluded_by_filename += 1
                return False

        self.stats.included += 1
        return True


def _get_extension(filename: str) -> str:
    """Extract the lowercase extension without the dot."""
    _, ext = os.path.splitext(filename)
    return ext.lstrip(".").lower()
