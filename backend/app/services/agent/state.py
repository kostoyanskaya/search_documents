import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    question: str
    history: list[dict]
    top_k: int
    lang: str
    ready_ids: set
    has_tables: bool
    langs_in_docs: dict
    route: str
    standalone: str
    queries: list
    reformulations: int
    hits: list
    best_score: float
    sufficient: bool
    llm_answer: Any
    labels: dict
    grounded: bool
    sql: str
    sql_attempts: int
    sql_error: str
    sql_result: Any
    sql_tried: bool
    sql_fallback: bool
    result: dict
    steps: Annotated[list, operator.add]
