import asyncio
import logging
from typing import Any, TypedDict

# LangChain / LLM imports
from langchain_core.messages import BaseMessage
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class AgentState(TypedDict):
    """
    State object passed between LangGraph nodes during multi-step execution.
    """
    messages: list[BaseMessage]
    question: str
    documents: list[dict[str, Any]]
    generation: str
    retrieval_count: int
    is_relevant: bool
    is_grounded: bool
    answers_question: bool
    web_search_needed: bool


class GradeDocuments(BaseModel):
    """Binary score for relevance check on retrieved documents."""
    binary_score: str = Field(
        description="Documents are relevant to the question: 'yes' or 'no'"
    )


class GradeHallucination(BaseModel):
    """Binary score for checking whether generation is grounded in facts."""
    binary_score: str = Field(
        description="Generation is grounded in the provided facts: 'yes' or 'no'"
    )


class GradeAnswer(BaseModel):
    """Binary score for checking whether generation addresses the question."""
    binary_score: str = Field(
        description="Generation addresses the user question: 'yes' or 'no'"
    )


class AgentNodes:
    """
    Contains execution nodes for stateful multi-step retrieval, verification,
    query rewriting, and grounded response synthesis.
    """

    def __init__(
        self,
        llm: Any,
        retriever: Any,
        web_search_tool: Any | None = None,
        max_retrieval_loops: int = 2,
    ):
        self.llm = llm
        self.retriever = retriever
        self.web_search_tool = web_search_tool
        self.max_retrieval_loops = max_retrieval_loops

    async def retrieve_node(self, state: AgentState) -> dict[str, Any]:
        """
        Retrieves relevant document chunks from the vector store based on the active question.
        """
        question = state["question"]
        retrieval_count = state.get("retrieval_count", 0)
        logger.info(f"Executing retrieval node (attempt {retrieval_count + 1}) for query: '{question}'")

        try:
            if hasattr(self.retriever, "ainvoke"):
                docs = await self.retriever.ainvoke(question)
            else:
                docs = await asyncio.to_thread(self.retriever.invoke, question)

            formatted_docs = [
                {
                    "page_content": doc.page_content,
                    "metadata": getattr(doc, "metadata", {}),
                }
                for doc in docs
            ]

            return {
                "documents": formatted_docs,
                "retrieval_count": retrieval_count + 1,
            }
        except Exception as e:
            logger.error(f"Error during document retrieval: {e}")
            return {"documents": [], "retrieval_count": retrieval_count + 1}

    async def grade_documents_node(self, state: AgentState) -> dict[str, Any]:
        """
        Evaluates document relevance concurrently across all retrieved chunks.
        """
        question = state["question"]
        documents = state.get("documents", [])
        logger.info(f"Grading relevance for {len(documents)} retrieved document chunks.")

        if not documents:
            return {
                "is_relevant": False,
                "documents": [],
                "web_search_needed": True,
            }

        structured_llm_grader = self.llm.with_structured_output(GradeDocuments)

        system_prompt = (
            "You are a grader assessing relevance of a retrieved document to a user question.\n"
            "If the document contains keyword(s) or semantic meaning related to the question, grade it as relevant.\n"
            "Give a binary score 'yes' or 'no' to indicate whether the document is relevant."
        )

        grade_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Retrieved document:\n\n{document}\n\nUser question: {question}"),
        ])

        grader_chain = grade_prompt | structured_llm_grader

        async def _grade_single_doc(doc: dict[str, Any]) -> dict[str, Any] | None:
            try:
                res: GradeDocuments = await grader_chain.ainvoke({
                    "question": question,
                    "document": doc["page_content"],
                })
                if res.binary_score.lower() == "yes":
                    return doc
            except Exception as e:
                logger.warning(f"Grading failed for chunk, defaulting to keeping it: {e}")
                return doc
            return None

        # Execute document grading concurrently
        graded_results = await asyncio.gather(
            *[_grade_single_doc(doc) for doc in documents]
        )
        relevant_docs = [doc for doc in graded_results if doc is not None]

        is_relevant = len(relevant_docs) > 0
        return {
            "documents": relevant_docs,
            "is_relevant": is_relevant,
            "web_search_needed": not is_relevant,
        }

    async def web_search_node(self, state: AgentState) -> dict[str, Any]:
        """
        Fallback node: performs external search if local vector database context is missing.
        """
        question = state["question"]
        logger.info(f"Executing web search fallback for: '{question}'")

        if not self.web_search_tool:
            logger.warning("Web search tool not configured. Skipping fallback step.")
            return {"documents": state.get("documents", [])}

        try:
            if hasattr(self.web_search_tool, "ainvoke"):
                search_results = await self.web_search_tool.ainvoke(question)
            else:
                search_results = await asyncio.to_thread(self.web_search_tool.invoke, question)

            search_doc = {
                "page_content": str(search_results),
                "metadata": {"source": "web_search", "file_name": "Web Search Results"},
            }

            existing_docs = state.get("documents", [])
            existing_docs.append(search_doc)

            return {"documents": existing_docs, "web_search_needed": False}
        except Exception as e:
            logger.error(f"Web search execution failed: {e}")
            return {"documents": state.get("documents", [])}

    async def rewrite_query_node(self, state: AgentState) -> dict[str, Any]:
        """
        Rewrites user input into a cleaner query tailored for vector database lookup.
        """
        question = state["question"]
        logger.info(f"Rewriting search query: '{question}'")

        system_prompt = (
            "You are an expert search query optimizer. Look at the user's question "
            "and rephrase it to optimize vector database retrieval. Preserve core entity names "
            "and technical parameters while removing conversational padding."
        )

        rewrite_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Initial Question: {question}\n\nOptimized Query:"),
        ])

        chain = rewrite_prompt | self.llm
        response = await chain.ainvoke({"question": question})

        new_question = response.content.strip()
        logger.info(f"Optimized target query: '{new_question}'")

        return {"question": new_question}

    async def generate_response_node(self, state: AgentState) -> dict[str, Any]:
        """
        Synthesizes the final answer using retrieved context and inline citations.
        """
        question = state["question"]
        documents = state.get("documents", [])
        logger.info("Generating final grounded response.")

        formatted_context_blocks = []
        for idx, doc in enumerate(documents, start=1):
            file_name = doc.get("metadata", {}).get("file_name", f"Source {idx}")
            page_num = doc.get("metadata", {}).get("page_number")
            page_str = f" (Page {page_num})" if page_num else ""
            formatted_context_blocks.append(
                f"[{idx}] Source: {file_name}{page_str}\n{doc['page_content']}"
            )

        context_str = "\n\n---\n\n".join(formatted_context_blocks) if formatted_context_blocks else "No relevant context available."

        system_prompt = (
            "You are an expert technical assistant. Answer the question using ONLY the provided "
            "context blocks. Include inline bracket citations like [1], [2] corresponding to "
            "the context sources used. If context is insufficient, state clearly what details are missing."
        )

        gen_prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Context:\n{context}\n\nQuestion: {question}\n\nAnswer:"),
        ])

        chain = gen_prompt | self.llm
        response = await chain.ainvoke({"context": context_str, "question": question})

        return {"generation": response.content}

    async def grade_hallucination_node(self, state: AgentState) -> dict[str, Any]:
        """
        Verifies that the generated response is strictly supported by the retrieved context.
        """
        documents = state.get("documents", [])
        generation = state.get("generation", "")
        logger.info("Checking generated response for hallucinations.")

        context_str = "\n\n".join([d["page_content"] for d in documents])
        structured_grader = self.llm.with_structured_output(GradeHallucination)

        system_prompt = (
            "You are a reviewer evaluating whether an LLM answer is grounded in facts from the provided context.\n"
            "Give a binary score 'yes' or 'no'. 'yes' means the answer is strictly based on facts in the context."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Context:\n{context}\n\nGenerated Response:\n{generation}"),
        ])

        chain = prompt | structured_grader
        try:
            res: GradeHallucination = await chain.ainvoke({
                "context": context_str,
                "generation": generation,
            })
            is_grounded = res.binary_score.lower() == "yes"
        except Exception as e:
            logger.warning(f"Hallucination check failed, defaulting to True: {e}")
            is_grounded = True

        return {"is_grounded": is_grounded}

    async def grade_answer_node(self, state: AgentState) -> dict[str, Any]:
        """
        Checks whether the generated response directly answers the user query.
        """
        question = state["question"]
        generation = state.get("generation", "")
        logger.info("Checking whether response directly answers the user question.")

        structured_grader = self.llm.with_structured_output(GradeAnswer)

        system_prompt = (
            "You are a evaluator checking whether an answer addresses a user question.\n"
            "Give a binary score 'yes' or 'no'. 'yes' means the response addresses the question completely."
        )

        prompt = ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Question:\n{question}\n\nGenerated Response:\n{generation}"),
        ])

        chain = prompt | structured_grader
        try:
            res: GradeAnswer = await chain.ainvoke({
                "question": question,
                "generation": generation,
            })
            answers_question = res.binary_score.lower() == "yes"
        except Exception as e:
            logger.warning(f"Answer grading failed, defaulting to True: {e}")
            answers_question = True

        return {"answers_question": answers_question}