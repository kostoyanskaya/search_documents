"""Documentation must not drift from the code."""

import pathlib
import re

from app.services.agent.graph import build_graph

README = pathlib.Path(__file__).resolve().parents[2] / "README.md"

STAGES_IN_README = ("Поиск", "Проверка цитат", "SQL", "формулировки")

NODES_BEHIND_THEM = {
    "retrieve",
    "rerank",
    "generate",
    "verify",
    "reformulate",
    "sql_plan",
    "sql_exec",
}

EDGES_BEHIND_THEM = {
    ("retrieve", "rerank"),
    ("generate", "verify"),
    ("rerank", "reformulate"),
    ("verify", "reformulate"),
    ("reformulate", "retrieve"),
    ("sql_plan", "sql_exec"),
}


def test_readme_has_a_diagram_with_the_main_stages():
    text = README.read_text(encoding="utf-8")
    start = text.index("```mermaid")
    end = text.index("```", start + 10)
    diagram = text[start:end]
    assert "-->" in diagram
    missing = [s for s in STAGES_IN_README if s not in diagram]
    assert not missing, f"stages missing in the README diagram: {missing}"


def test_agent_graph_still_has_the_stages_shown_in_the_readme():
    graph = build_graph().get_graph()
    nodes = {n for n in graph.nodes if not n.startswith("__")}
    edges = {(e.source, e.target) for e in graph.edges}
    assert NODES_BEHIND_THEM <= nodes, NODES_BEHIND_THEM - nodes
    assert EDGES_BEHIND_THEM <= edges, EDGES_BEHIND_THEM - edges


def test_every_env_var_in_the_example_is_a_real_setting():
    from app.core.config import Settings

    example = (
        pathlib.Path(__file__).resolve().parents[1] / ".env.example"
    ).read_text()
    names = {
        m.lower()
        for m in re.findall(r"^#?\s*([A-Z][A-Z0-9_]+)=", example, re.M)
    }
    unknown = names - set(Settings.model_fields)
    assert not unknown, f"unknown settings in .env.example: {unknown}"