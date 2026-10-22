"""Streamlit demo for the evidence-first business graph."""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from firma2.agent import ask_agent
from firma2.graph_ingestion import DEFAULT_DATABASE_PATH
from firma2.retrieval import project_dataset, resolve_reference, traverse_shared_source

ROOT = Path(__file__).resolve().parents[1]
ABSTENTIONS_PATH = ROOT / "outputs" / "retrieval" / "abstentions.jsonl"

st.set_page_config(page_title="Firma Graph Workbench", page_icon="◎", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=Manrope:wght@400;500;600;700;800&display=swap');
    :root { --ink: #162321; --muted: #64716d; --paper: #f3f5f0; --leaf: #145b46; --lime: #d9ed69; --coral: #e88167; --line: #d8ded7; }
    html, body, [class*="css"] { font-family: 'Manrope', sans-serif; color: var(--ink); }
    .stApp, [data-testid="stAppViewContainer"] { background: radial-gradient(ellipse at 90% 0%, #e0ebd4 0, transparent 34%), linear-gradient(145deg, #f3f5f0 0%, #edf1e9 58%, #e8eee4 100%); color: var(--ink); }
    [data-testid="stAppViewContainer"] h1, [data-testid="stAppViewContainer"] h2, [data-testid="stAppViewContainer"] h3,
    [data-testid="stAppViewContainer"] p, [data-testid="stAppViewContainer"] label,
    [data-testid="stAppViewContainer"] [data-testid="stMarkdownContainer"],
    [data-testid="stAppViewContainer"] [data-testid="stWidgetLabel"] { color: var(--ink) !important; }
    [data-testid="stAppViewContainer"] input, [data-testid="stAppViewContainer"] textarea,
    [data-testid="stAppViewContainer"] [data-baseweb="select"] > div { background: #fff !important; color: var(--ink) !important; }
    [data-testid="stSidebar"] { background: #162321; }
    [data-testid="stSidebar"] * { color: #edf3e9; }
    .brand { font-size: 13px; letter-spacing: 2px; text-transform: uppercase; color: #d9ed69; font-family: 'DM Mono', monospace; }
    .headline { font-size: clamp(28px, 3.4vw, 42px); line-height: 1.05; font-weight: 800; max-width: 820px; margin: 12px 0 8px; }
    .subhead { color: #64716d; font-size: 14px; margin-bottom: 24px; }
    .eyebrow { color: #145b46; font-family: 'DM Mono', monospace; font-size: 11px; text-transform: uppercase; letter-spacing: 1px; }
    .metric { border-top: 1px solid #9eaaa1; padding-top: 10px; }
    div[data-testid="stMetricValue"] { color: #145b46; }
    .stButton > button { border-radius: 5px; background: #145b46; color: #fff; border: 0; font-weight: 700; }
    .stButton > button:hover { background: #0f4737; color: white; }
    .stButton > button[kind="primary"] { background: #145b46 !important; color: #fff !important; }
    [data-testid="stAppViewContainer"] input::placeholder, [data-testid="stAppViewContainer"] textarea::placeholder { color: #64716d !important; opacity: 1; }
    .stTabs [data-baseweb="tab-list"] { gap: 14px; border-bottom: 1px solid #d8ded7; }
    .stTabs [data-baseweb="tab"] { font-weight: 700; color: var(--muted); }
    .stTabs [aria-selected="true"] { color: var(--leaf) !important; }
    code, pre { font-family: 'DM Mono', monospace; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="brand">FIRMA / ENTITY INTELLIGENCE</div>', unsafe_allow_html=True)
st.markdown('<div class="headline">Evidence first. Answers second.</div>', unsafe_allow_html=True)
st.markdown('<div class="subhead">A local Kuzu graph with conservative matching, traceable source evidence, and explicit abstention.</div>', unsafe_allow_html=True)

database_path = Path(st.sidebar.text_input("Kuzu database", str(DEFAULT_DATABASE_PATH)))
st.sidebar.markdown("---")
st.sidebar.caption("Model-backed agent answers use the configured OPENAI_API_KEY from .env. Deterministic tools run locally.")

if not database_path.exists():
    st.error(f"Kuzu database not found at {database_path}. Run the graph loader first.")
    st.stop()

tabs = st.tabs(["Agent", "Resolve", "Projection", "Graph path", "Abstentions"])

with tabs[0]:
    st.markdown('<div class="eyebrow">01 / Ask the graph</div>', unsafe_allow_html=True)
    with st.form("agent_question"):
        question = st.text_area("Question", placeholder="Which entity best matches Sydney Missionary Bible College?", height=95)
        submitted = st.form_submit_button("Ask agent", type="primary")
    if submitted and question.strip():
        with st.spinner("Planning retrieval and checking graph evidence..."):
            try:
                result = ask_agent(question, database_path=database_path)
                if result["abstained"]:
                    st.warning(result["answer"])
                else:
                    st.success(result["answer"])
                st.caption(f"Tool calls: {result['tool_calls']} · Tokens: {result['token_usage'].get('total_tokens', 0)}")
                with st.expander("Retrieval trace", expanded=True):
                    st.json(result["tool_results"])
                if result.get("error"):
                    st.error(result["error"])
            except Exception as error:
                st.error(f"Agent failed safely: {error}")

with tabs[1]:
    st.markdown('<div class="eyebrow">02 / Candidate resolution</div>', unsafe_allow_html=True)
    reference = st.text_input("Name, ABN, or ACN", placeholder="North Star Pty Ltd")
    if st.button("Resolve", key="resolve_button") and reference.strip():
        candidates = resolve_reference(reference, database_path)
        if candidates:
            st.dataframe(candidates, use_container_width=True, hide_index=True)
        else:
            st.warning("No candidate met the confidence floor. The resolver abstained.")

with tabs[2]:
    st.markdown('<div class="eyebrow">03 / Flat projection</div>', unsafe_allow_html=True)
    with st.form("projection"):
        status = st.selectbox("Status", ["Any", "active", "inactive", "unknown"])
        name_contains = st.text_input("Name contains")
        result_limit = st.number_input("Maximum rows", min_value=1, max_value=1000, value=100)
        project = st.form_submit_button("Build projection")
    if project:
        criteria = {}
        if status != "Any":
            criteria["status"] = status
        if name_contains.strip():
            criteria["name_contains"] = name_contains.strip()
        projected = project_dataset(criteria, limit=int(result_limit), database_path=database_path)
        st.dataframe(projected, use_container_width=True, hide_index=True)
        if projected:
            st.download_button("Download JSON", json.dumps(projected, indent=2), "entity_projection.json", "application/json")

with tabs[3]:
    st.markdown('<div class="eyebrow">04 / Bounded graph path</div>', unsafe_allow_html=True)
    entity_key = st.text_input("Canonical entity key", placeholder="abn:11000047950")
    traversal_cap = st.slider("Maximum related entities", min_value=1, max_value=25, value=10)
    if st.button("Traverse shared provenance", key="traverse_button") and entity_key.strip():
        result = traverse_shared_source(entity_key.strip(), traversal_cap, database_path)
        st.caption("Shared source provenance does not establish ownership, control, or common identity.")
        st.json(result)

with tabs[4]:
    st.markdown('<div class="eyebrow">05 / Unresolved records</div>', unsafe_allow_html=True)
    source_filter = st.text_input("Filter by source ID")
    limit = st.slider("Maximum abstentions", min_value=10, max_value=100, value=25, step=5)
    if ABSTENTIONS_PATH.exists():
        abstentions = []
        with ABSTENTIONS_PATH.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                record = json.loads(line)
                if source_filter and source_filter not in record.get("source_id", ""):
                    continue
                abstentions.append(record)
                if len(abstentions) >= limit:
                    break
        st.dataframe(abstentions, use_container_width=True, hide_index=True)
    else:
        st.info("No abstention artifact found. Run Step 4 to generate it.")