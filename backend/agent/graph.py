import logging
from typing import Any, Literal

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from backend.agent.nodes import AgentNodes, AgentState

logger = logging.getLogger(__name__)


def decide_after_grading(state: AgentState) -> Literal["generate", "web_search", "rewrite"]:
    """
    Conditional routing logic following document grading:
    - If documents are relevant -> proceed to 'generate'
    - If documents are irrelevant and web search is enabled -> route to 'web_search'
    - If retrieval count is below max retries -> route to 'rewrite'
    - Otherwise -> proceed to 'generate' with available context
    """
    is_relevant = state.get("is_relevant", False)
    retrieval_count = state.get("retrieval_count", 0)
    web_search_needed = state.get("web_search_needed", False)

    if is_relevant:
        logger.info("Relevant documents identified. Proceeding to 'generate'.")
        return "generate"

    if web_search_needed:
        logger.info("Local documents insufficient. Routing to 'web_search' fallback.")
        return "web_search"

    if retrieval_count < 2:
        logger.info("Documents inadequate; retry limit not met. Routing to 'rewrite'.")
        return "rewrite"

    logger.info("Max retrieval attempts reached. Proceeding to 'generate' with existing context.")
    return "generate"


def decide_after_generation(state: AgentState) -> Literal["useful", "not_useful", "not_grounded"]:
    """
    Conditional routing logic following response generation (Corrective RAG verification):
    - Checks for hallucinations against retrieved context
    - Checks if the response directly addresses the initial user query
    """
    is_grounded = state.get("is_grounded", True)
    answers_question = state.get("answers_question", True)

    if not is_grounded:
        logger.warning("Generation contains hallucinations (not grounded in context). Routing to 'generate' to re-try.")
        return "not_grounded"

    if answers_question:
        logger.info("Generation passed hallucination and relevance checks. Routing to END.")
        return "useful"

    logger.warning("Generation is grounded but does not directly answer the question. Routing to 'rewrite'.")
    return "not_useful"


def build_agent_graph(
    llm: Any,
    retriever: Any,
    web_search_tool: Any | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    max_retrieval_loops: int = 2,
) -> Any:
    """
    Constructs, wires, and compiles the stateful multi-step agent execution graph.

    Args:
        llm: The language model instance used across nodes.
        retriever: Vector database retriever or custom retriever class.
        web_search_tool: Optional search tool for web fallback.
        checkpointer: Optional state checkpointer for persistent state/history.
        max_retrieval_loops: Threshold for query rewrite and retrieval loops.

    Returns:
        Compiled Executable LangGraph application instance.
    """
    nodes = AgentNodes(
        llm=llm,
        retriever=retriever,
        web_search_tool=web_search_tool,
        max_retrieval_loops=max_retrieval_loops,
    )

    # Initialize graph state schema
    workflow = StateGraph(AgentState)

    # 1. Register Execution Nodes
    workflow.add_node("retrieve", nodes.retrieve_node)
    workflow.add_node("grade_documents", nodes.grade_documents_node)
    workflow.add_node("web_search", nodes.web_search_node)
    workflow.add_node("rewrite", nodes.rewrite_query_node)
    workflow.add_node("generate", nodes.generate_response_node)
    workflow.add_node("grade_hallucination", nodes.grade_hallucination_node)
    workflow.add_node("grade_answer", nodes.grade_answer_node)

    # 2. Wire Primary Linear Graph Edges
    workflow.add_edge(START, "retrieve")
    workflow.add_edge("retrieve", "grade_documents")
    workflow.add_edge("web_search", "generate")

    # 3. Add Conditional Edge Post Document Grading
    workflow.add_conditional_edges(
        "grade_documents",
        decide_after_grading,
        {
            "generate": "generate",
            "web_search": "web_search",
            "rewrite": "rewrite",
        },
    )

    # 4. Wire Query Rewriter back to Vector Retriever
    workflow.add_edge("rewrite", "retrieve")

    # 5. Wire Response Generation into Grounding & Quality Verification Sequence
    workflow.add_edge("generate", "grade_hallucination")
    workflow.add_edge("grade_hallucination", "grade_answer")

    # 6. Add Conditional Edge Post Response Verification (Corrective RAG)
    workflow.add_conditional_edges(
        "grade_answer",
        decide_after_generation,
        {
            "useful": END,
            "not_useful": "rewrite",
            "not_grounded": "generate",
        },
    )

    # 7. Compile executable app with optional persistence checkpointer
    app = workflow.compile(checkpointer=checkpointer)
    logger.info("Agent StateGraph successfully constructed and compiled.")
    return app