"""LangGraph agent for evidence-grounded Kuzu retrieval."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Literal, TypedDict

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from firma2.graph_ingestion import DEFAULT_DATABASE_PATH, PROJECT_ROOT
from firma2.retrieval import project_dataset, resolve_reference, traverse_shared_source

DEFAULT_MODEL = "gpt-4o-mini"
MAX_TOOL_CALLS = 3
ABSTENTIONS_PATH = PROJECT_ROOT / "data" / "output" / "retrieval" / "abstentions.jsonl"
ALLOWED_TOOLS = {"resolve_reference", "project_dataset", "traverse_shared_source", "search_abstentions"}


class AgentState(TypedDict, total=False):
    question: str
    plan: dict[str, Any]
    tool_results: list[dict[str, Any]]
    tool_calls: int
    answer: str
    abstained: bool
    error: str
    token_usage: dict[str, int]


class AgentPlan(BaseModel):
    tool: Literal["resolve_reference", "project_dataset", "traverse_shared_source", "search_abstentions", "finish"]
    arguments: dict[str, Any] = Field(default_factory=dict)


def _message_content(response: Any) -> str:
    content = getattr(response, "content", response)
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text", "")) if isinstance(part, dict) else str(part)
            for part in content
        )
    return str(content)


def _response_usage(response: Any) -> dict[str, int]:
    usage = getattr(response, "usage_metadata", None)
    if not isinstance(usage, dict):
        usage = getattr(response, "response_metadata", {}).get("token_usage", {})
    if not isinstance(usage, dict):
        return {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    input_tokens = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    output_tokens = int(usage.get("output_tokens", usage.get("completion_tokens", 0)) or 0)
    total_tokens = int(usage.get("total_tokens", input_tokens + output_tokens) or 0)
    return {"input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens}


def _accumulate_usage(state: AgentState, response: Any) -> dict[str, int]:
    current = state.get("token_usage", {})
    observed = _response_usage(response)
    return {
        name: int(current.get(name, 0)) + observed[name]
        for name in ("input_tokens", "output_tokens", "total_tokens")
    }


def _parse_json_object(value: str) -> dict[str, Any]:
    text = value.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model response did not contain a JSON object.")
        parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("Model response must be a JSON object.")
    return parsed


def _tool_schemas() -> str:
    return json.dumps(
        [
            {
                "name": "resolve_reference",
                "purpose": "Find ranked canonical entity candidates for a name or ABN/ACN.",
                "arguments": {"reference": "string", "limit": "integer optional, max 10"},
            },
            {
                "name": "project_dataset",
                "purpose": "Return a bounded flat projection of entities filtered by status, ABN, ACN, name_contains, or source_id.",
                "arguments": {"criteria": "object", "columns": "array of column names optional", "limit": "integer optional, max 100"},
            },
            {
                "name": "traverse_shared_source",
                "purpose": "Find entities connected to a known canonical key through shared source provenance; this is not an ownership or identity relation.",
                "arguments": {"entity_key": "string", "max_results": "integer optional, max 25"},
            },
            {
                "name": "search_abstentions",
                "purpose": "Find refused-to-link source observations by source or text query.",
                "arguments": {"query": "string optional", "source_id": "string optional", "limit": "integer optional, max 25"},
            },
        ],
        sort_keys=True,
    )


def _search_abstentions(query: str = "", source_id: str = "", limit: int = 25) -> list[dict]:
    if not ABSTENTIONS_PATH.exists():
        return []
    query_tokens = set(re.findall(r"[a-z0-9]+", query.casefold()))
    results = []
    with ABSTENTIONS_PATH.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if source_id and record.get("source_id") != source_id:
                continue
            haystack = json.dumps(record.get("entity", {}), sort_keys=True).casefold()
            if query_tokens and not all(token in haystack for token in query_tokens):
                continue
            results.append(record)
            if len(results) >= min(max(limit, 1), 25):
                break
    return results


def _execute_tool(
    tool_name: str,
    arguments: dict[str, Any],
    database_path: str | Path,
) -> Any:
    if tool_name not in ALLOWED_TOOLS:
        raise ValueError(f"Tool is not allowed: {tool_name}")
    if tool_name == "resolve_reference":
        reference = arguments.get("reference")
        if not isinstance(reference, str) or not reference.strip():
            raise ValueError("resolve_reference requires a non-empty reference.")
        return resolve_reference(reference.strip(), database_path, min(int(arguments.get("limit", 5)), 10))
    if tool_name == "project_dataset":
        criteria = arguments.get("criteria", {})
        columns = arguments.get("columns")
        if not isinstance(criteria, dict) or (columns is not None and not isinstance(columns, list)):
            raise ValueError("project_dataset requires an object criteria and optional columns array.")
        return project_dataset(criteria, columns, min(int(arguments.get("limit", 25)), 100), database_path)
    if tool_name == "traverse_shared_source":
        entity_key = arguments.get("entity_key")
        if not isinstance(entity_key, str) or not entity_key.strip():
            raise ValueError("traverse_shared_source requires an entity_key.")
        return traverse_shared_source(entity_key, min(int(arguments.get("max_results", 10)), 25), database_path)
    if tool_name == "search_abstentions":
        return _search_abstentions(
            str(arguments.get("query", "")),
            str(arguments.get("source_id", "")),
            min(int(arguments.get("limit", 10)), 25),
        )
    raise ValueError(f"Unsupported tool: {tool_name}")


def create_retrieval_agent(
    model: Any | None = None,
    database_path: str | Path = DEFAULT_DATABASE_PATH,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> Any:
    """Build a bounded agent graph; callers may inject a model for testing."""
    if model is None:
        load_dotenv(PROJECT_ROOT / ".env")
        if not os.getenv("OPENAI_API_KEY"):
            raise RuntimeError("OPENAI_API_KEY is missing. Set it in .env or the process environment.")
        model = ChatOpenAI(model=DEFAULT_MODEL, temperature=0)

    tool_budget = min(max(int(max_tool_calls), 1), MAX_TOOL_CALLS)
    planner = (
        model.with_structured_output(AgentPlan, method="function_calling", include_raw=True)
        if hasattr(model, "with_structured_output")
        else None
    )

    def plan_node(state: AgentState) -> dict[str, Any]:
        prompt = [
            (
                "system",
                "You are a cautious business-entity graph retrieval planner. Choose exactly one allowed tool "
                "or finish. Never decide entity identity yourself. Use resolve_reference for names/IDs, "
                "project_dataset for tabular selections, traverse_shared_source only when a known canonical "
                "key is available, and search_abstentions for unresolved-record questions. If existing tool "
                "results already answer the request, finish. Return only JSON: {tool: name or finish, arguments: object}.",
            ),
            ("system", f"Allowed tools: {_tool_schemas()}"),
            ("human", f"Question: {state['question']}\nTool results so far: {json.dumps(state.get('tool_results', []), sort_keys=True)}"),
        ]
        try:
            if planner is not None:
                structured = planner.invoke(prompt)
                response = structured.get("raw")
                parsed = structured.get("parsed")
                if structured.get("parsing_error") or parsed is None:
                    raise ValueError(str(structured.get("parsing_error") or "Structured plan was empty."))
                plan = parsed.model_dump() if isinstance(parsed, BaseModel) else parsed
            else:
                response = model.invoke(prompt)
                plan = _parse_json_object(_message_content(response))
        except Exception as error:
            updates: dict[str, Any] = {
                "plan": {"tool": "finish", "arguments": {}},
                "error": f"Planning failed: {error}",
            }
            if "response" in locals() and response is not None:
                updates["token_usage"] = _accumulate_usage(state, response)
            return updates
        tool_name = plan.get("tool")
        arguments = plan.get("arguments", {})
        if tool_name != "finish" and (tool_name not in ALLOWED_TOOLS or not isinstance(arguments, dict)):
            return {"plan": {"tool": "finish", "arguments": {}}, "error": "Planner selected an invalid tool or arguments."}
        return {"plan": {"tool": tool_name, "arguments": arguments}, "token_usage": _accumulate_usage(state, response)}

    def route_plan(state: AgentState) -> str:
        tool_name = state.get("plan", {}).get("tool", "finish")
        if tool_name == "finish" or state.get("tool_calls", 0) >= tool_budget:
            return "answer"
        return "execute"

    def execute_node(state: AgentState) -> dict[str, Any]:
        plan = state.get("plan", {})
        results = list(state.get("tool_results", []))
        try:
            result = _execute_tool(plan["tool"], plan.get("arguments", {}), database_path)
            results.append({"tool": plan["tool"], "arguments": plan.get("arguments", {}), "result": result})
            return {"tool_results": results, "tool_calls": state.get("tool_calls", 0) + 1}
        except Exception as error:
            results.append({"tool": plan.get("tool"), "arguments": plan.get("arguments", {}), "error": str(error)})
            return {"tool_results": results, "tool_calls": state.get("tool_calls", 0) + 1}

    def answer_node(state: AgentState) -> dict[str, Any]:
        tool_results = state.get("tool_results", [])
        evidence = json.dumps(tool_results, sort_keys=True)
        has_result = any("result" in result and result["result"] not in ([], {}, None) for result in tool_results)
        if not has_result:
            return {
                "answer": "I can’t answer this confidently from the available graph evidence, so I’m abstaining.",
                "abstained": True,
            }
        prompt = [
            (
                "system",
                "Answer the user's question using only the supplied tool results. Do not add facts or relationships "
                "not present there. Cite canonical keys and quote or summarize the evidence. If evidence is absent, "
                "ambiguous, or does not support the requested conclusion, explicitly abstain. Shared-source paths "
                "mean provenance only, never ownership, control, or common identity. Return concise plain text.",
            ),
            ("human", f"Question: {state['question']}\nTool results (the complete evidence basis): {evidence}"),
        ]
        try:
            response = model.invoke(prompt)
            answer = _message_content(response).strip()
        except Exception as error:
            return {"answer": "The evidence was retrieved, but answer generation failed; abstaining rather than guessing.", "abstained": True, "error": str(error)}
        lowered = answer.casefold()
        return {
            "answer": answer,
            "abstained": any(token in lowered for token in ("abstain", "cannot answer", "can't answer", "insufficient evidence")),
            "token_usage": _accumulate_usage(state, response),
        }

    workflow = StateGraph(AgentState)
    workflow.add_node("plan", plan_node)
    workflow.add_node("execute", execute_node)
    workflow.add_node("answer", answer_node)
    workflow.add_edge(START, "plan")
    workflow.add_conditional_edges("plan", route_plan, {"execute": "execute", "answer": "answer"})
    workflow.add_edge("execute", "plan")
    workflow.add_edge("answer", END)
    return workflow.compile()


def ask_agent(question: str, model: Any | None = None, database_path: str | Path = DEFAULT_DATABASE_PATH) -> dict[str, Any]:
    """Run one question through the LangGraph agent and return answer plus trace."""
    if not question.strip():
        raise ValueError("Question must not be empty.")
    agent = create_retrieval_agent(model=model, database_path=database_path)
    result = agent.invoke({"question": question.strip(), "tool_results": [], "tool_calls": 0, "token_usage": {}})
    return {
        "question": question.strip(),
        "answer": result.get("answer", "I can’t answer this confidently from the available graph evidence, so I’m abstaining."),
        "abstained": result.get("abstained", True),
        "tool_calls": result.get("tool_calls", 0),
        "tool_results": result.get("tool_results", []),
        "token_usage": result.get("token_usage", {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
        "error": result.get("error"),
    }


__all__ = ["ask_agent", "create_retrieval_agent"]