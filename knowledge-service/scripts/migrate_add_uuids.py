#!/usr/bin/env python3
"""
Big-bang migration: stamp UUIDv4 `id` into every knowledge-base page's frontmatter.

Usage:
    python migrate_add_uuids.py <knowledge-base-path>

Behaviour:
- Scans all .md files recursively under <knowledge-base-path>
- Skips files that already have an `id:` field in frontmatter
- Inserts `id: <uuidv4>` as the first field after the opening `---`
- Writes the file back; no other content is touched
- Idempotent: safe to re-run

Exit codes:
    0  — all files processed (migrated + skipped, zero failures)
    1  — one or more files failed to process
"""

import re
import sys
import uuid
from pathlib import Path


# Matches a YAML frontmatter block at the very start of a file:
#   ---\n<content>\n---\n
_FRONTMATTER_RE = re.compile(r"^---\n(.*?\n)---\n", re.DOTALL)

# Matches an existing `id:` field in frontmatter (to detect already-migrated pages)
_ID_FIELD_RE = re.compile(r"^id:\s+\S", re.MULTILINE)


def process_file(path: Path) -> tuple[bool, str]:
    """
    Attempt to stamp a UUID into the frontmatter of a single .md file.

    Returns:
        (modified, info)  where modified=True means the file was written.
        info is the new UUID on success, or a short reason string if skipped.
    """
    content = path.read_text(encoding="utf-8")

    match = _FRONTMATTER_RE.match(content)
    if not match:
        return False, "no frontmatter"

    fm_body = match.group(1)

    if _ID_FIELD_RE.search(fm_body):
        return False, "already has id"

    page_id = str(uuid.uuid4())
    new_fm_body = f"id: {page_id}\n{fm_body}"
    new_content = f"---\n{new_fm_body}---\n{content[match.end():]}"

    path.write_text(new_content, encoding="utf-8")
    return True, page_id


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <knowledge-base-path>", file=sys.stderr)
        sys.exit(1)

    kb_path = Path(sys.argv[1])
    if not kb_path.is_dir():
        print(f"Error: '{kb_path}' is not a directory", file=sys.stderr)
        sys.exit(1)

    pages = sorted(kb_path.rglob("*.md"))
    if not pages:
        print(f"No .md files found under {kb_path}")
        return

    migrated = 0
    skipped = 0
    failed = 0

    for page in pages:
        rel = page.relative_to(kb_path)
        try:
            modified, info = process_file(page)
            if modified:
                print(f"  + {rel}  [{info}]")
                migrated += 1
            else:
                print(f"  - {rel}  ({info})")
                skipped += 1
        except Exception as exc:
            print(f"  ! {rel}  ERROR: {exc}", file=sys.stderr)
            failed += 1

    print(f"\nDone: {migrated} migrated, {skipped} skipped", end="")
    if failed:
        print(f", {failed} FAILED", file=sys.stderr)
        sys.exit(1)
    else:
        print()


if __name__ == "__main__":
    main()
