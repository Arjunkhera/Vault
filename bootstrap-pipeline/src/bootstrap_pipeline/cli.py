"""
CLI entrypoint for the bootstrap pipeline.

Usage by the agent:
  bootstrap ingest-repo  <url>  [--branch <branch>] [--output <path>]
  bootstrap ingest-local <path> [--output <path>]

Both commands write an IngestResult as JSON to stdout (or --output file),
which the agent reads to decide what pages to generate.
"""

from __future__ import annotations

import argparse
import json
import sys

from .ingest import ingest_local, ingest_repo


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="bootstrap",
        description="Bootstrap pipeline CLI — ingest sources for knowledge page generation",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # --- ingest-repo ---
    repo_parser = subparsers.add_parser(
        "ingest-repo",
        help="Clone a GitHub repo and produce an IngestResult",
    )
    repo_parser.add_argument("url", help="GitHub HTTPS or SSH URL")
    repo_parser.add_argument("--branch", default=None, help="Branch to clone (default: repo default)")
    repo_parser.add_argument("--output", default=None, help="Write JSON to file instead of stdout")
    repo_parser.add_argument(
        "--exclude-dir", action="append", default=[],
        help="Additional directory names to exclude (repeatable)",
    )
    repo_parser.add_argument(
        "--exclude-pattern", action="append", default=[],
        help="Additional glob patterns to exclude (repeatable)",
    )
    repo_parser.add_argument(
        "--max-file-size", type=int, default=None,
        help="Max file size in bytes (default: 100000)",
    )

    # --- ingest-local ---
    local_parser = subparsers.add_parser(
        "ingest-local",
        help="Read a local directory and produce an IngestResult",
    )
    local_parser.add_argument("path", help="Absolute path to directory or file")
    local_parser.add_argument("--output", default=None, help="Write JSON to file instead of stdout")
    local_parser.add_argument(
        "--exclude-dir", action="append", default=[],
        help="Additional directory names to exclude (repeatable)",
    )
    local_parser.add_argument(
        "--exclude-pattern", action="append", default=[],
        help="Additional glob patterns to exclude (repeatable)",
    )
    local_parser.add_argument(
        "--max-file-size", type=int, default=None,
        help="Max file size in bytes (default: 100000)",
    )

    args = parser.parse_args()

    try:
        if args.command == "ingest-repo":
            result = ingest_repo(
                args.url,
                extra_excluded_dirs=set(args.exclude_dir) if args.exclude_dir else None,
                extra_excluded_patterns=args.exclude_pattern or None,
                max_file_size=args.max_file_size,
            )
        elif args.command == "ingest-local":
            result = ingest_local(
                args.path,
                extra_excluded_dirs=set(args.exclude_dir) if args.exclude_dir else None,
                extra_excluded_patterns=args.exclude_pattern or None,
                max_file_size=args.max_file_size,
            )
        else:
            parser.print_help()
            sys.exit(1)

        output_json = result.model_dump_json(indent=2)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_json)
            _print_summary(result, args.output)
        else:
            print(output_json)

    except Exception as e:
        print(json.dumps({"error": str(e), "type": type(e).__name__}), file=sys.stderr)
        sys.exit(1)


def _print_summary(result, output_path: str) -> None:
    """Print a human-readable summary to stderr when writing to a file."""
    m = result.metadata
    print(f"Ingest complete: {m.name}", file=sys.stderr)
    print(f"  Source:    {result.origin}", file=sys.stderr)
    print(f"  Files:     {m.included_files} included / {m.excluded_files} excluded / {m.total_files} total", file=sys.stderr)
    if m.languages:
        print(f"  Languages: {', '.join(m.languages)}", file=sys.stderr)
    print(f"  Output:    {output_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
