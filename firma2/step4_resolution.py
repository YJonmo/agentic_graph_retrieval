"""Command-line entry point for Step 4 resolution outputs."""

from __future__ import annotations

import argparse

from firma2.resolution import run_resolution


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve source observations and generate review artifacts.")
    parser.add_argument("--database", help="Path to the Kuzu database file.")
    parser.add_argument("--observation-dir", help="Directory containing per-source observation JSONL files.")
    arguments = parser.parse_args()
    options = {}
    if arguments.database:
        options["database_path"] = arguments.database
    if arguments.observation_dir:
        options["observation_dir"] = arguments.observation_dir
    print(run_resolution(**options))


if __name__ == "__main__":
    main()