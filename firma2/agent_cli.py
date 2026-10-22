"""Command-line interface for the LangGraph retrieval agent."""

from __future__ import annotations

import argparse
import json

from firma2.agent import ask_agent


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the evidence-grounded graph retrieval agent.")
    parser.add_argument("question", help="A question about business entities in the Kuzu graph.")
    parser.add_argument("--database", help="Path to the Kuzu database file.")
    arguments = parser.parse_args()
    options = {}
    if arguments.database:
        options["database_path"] = arguments.database
    print(json.dumps(ask_agent(arguments.question, **options), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()