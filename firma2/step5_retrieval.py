"""Command-line entry point for Step 5 retrieval outputs."""

from __future__ import annotations

import argparse

from firma2.retrieval import run_step5


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate lookup and traversal evaluation outputs.")
    parser.add_argument("--database", help="Path to the Kuzu database file.")
    parser.add_argument("--iterations", type=int, default=100, help="Number of local lookup calls to measure.")
    arguments = parser.parse_args()
    options = {"iterations": arguments.iterations}
    if arguments.database:
        options["database_path"] = arguments.database
    print(run_step5(**options))


if __name__ == "__main__":
    main()