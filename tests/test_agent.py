import json

from firma2.agent import ask_agent
from firma2.graph_ingestion import load_profiles_to_graph


class FakeModel:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.prompts = []

    def invoke(self, prompt):
        self.prompts.append(prompt)
        return next(self.responses)


def make_database(tmp_path):
    profiles = tmp_path / "profiles.jsonl"
    profiles.write_text(
        json.dumps({
            "entity_key": "abn:51824753556",
            "profile": {
                "legal_name": {
                    "value": "North Star Pty Ltd",
                    "confidence": 0.9,
                    "source": {"source_id": "source-a", "source_record_id": "1"},
                    "evidence": ["original record 1"],
                },
                "abn": {
                    "value": "51824753556",
                    "confidence": 0.9,
                    "source": {"source_id": "source-a", "source_record_id": "1"},
                    "evidence": ["ABN from record 1"],
                },
                "status": {"value": "active"},
            },
            "provenance": {},
        }) + "\n",
        encoding="utf-8",
    )
    database_path = tmp_path / "agent_graph.kuzu"
    load_profiles_to_graph(
        path=profiles,
        database_path=database_path,
        report_path=tmp_path / "load.csv",
        summary_path=tmp_path / "load.md",
    )
    return database_path


def test_agent_plans_tool_then_answers_from_retrieved_evidence(tmp_path):
    database_path = make_database(tmp_path)
    model = FakeModel([
        '{"tool":"resolve_reference","arguments":{"reference":"North Star"}}',
        '{"tool":"finish","arguments":{}}',
        "North Star Pty Ltd is canonical entity abn:51824753556. The graph contains an exact normalized-name match and source evidence from source-a.",
    ])

    result = ask_agent("Which business is North Star?", model=model, database_path=database_path)

    assert result["abstained"] is False
    assert result["tool_calls"] == 1
    assert result["tool_results"][0]["tool"] == "resolve_reference"
    assert result["tool_results"][0]["result"][0]["canonical_key"] == "abn:51824753556"
    assert "source-a" in result["answer"]


def test_agent_abstains_when_retrieval_returns_no_evidence(tmp_path):
    database_path = make_database(tmp_path)
    model = FakeModel([
        '{"tool":"resolve_reference","arguments":{"reference":"Unknown and Unmatched Holdings"}}',
        '{"tool":"finish","arguments":{}}',
    ])

    result = ask_agent("Who is Unknown and Unmatched Holdings?", model=model, database_path=database_path)

    assert result["abstained"] is True
    assert result["tool_calls"] == 1
    assert "abstaining" in result["answer"].casefold()


def test_agent_rejects_invalid_tool_and_still_abstains(tmp_path):
    database_path = make_database(tmp_path)
    model = FakeModel(['{"tool":"run_shell","arguments":{"command":"anything"}}'])

    result = ask_agent("Find an entity", model=model, database_path=database_path)

    assert result["abstained"] is True
    assert result["tool_calls"] == 0
    assert result["error"]