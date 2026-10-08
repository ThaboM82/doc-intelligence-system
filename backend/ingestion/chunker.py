import logging
import uuid
from typing import Any

from pydantic import BaseModel, Field

from backend.ingestion.parser import ParsedDocument, ParsedElement

# Optional token estimation using tiktoken
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

logger = logging.getLogger(__name__)


class DocumentChunk(BaseModel):
    """Structured chunk representation ready for vector indexing and database upsert."""

    chunk_id: str
    document_id: str
    file_name: str
    content: str
    chunk_index: int
    token_count: int
    page_number: int | None = None
    section_header: str | None = None
    layout_type: str = "text"  # 'text', 'header', 'table', 'code'
    metadata: dict[str, Any] = Field(default_factory=dict)


class StructuralLayoutChunker:
    """
    Context-aware layout chunker that uses token limits, heading hierarchies,
    and structural integrity to chunk parsed documents effectively.
    """

    def __init__(
        self,
        target_chunk_tokens: int = 512,
        max_chunk_tokens: int = 768,
        chunk_overlap_tokens: int = 64,
        preserve_tables: bool = True,
        tokenizer_model: str = "gpt-4o",
    ):
        self.target_chunk_tokens = target_chunk_tokens
        self.max_chunk_tokens = max_chunk_tokens
        self.chunk_overlap_tokens = chunk_overlap_tokens
        self.preserve_tables = preserve_tables

        if TIKTOKEN_AVAILABLE:
            try:
                self.tokenizer = tiktoken.encoding_for_model(tokenizer_model)
            except Exception:
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
        else:
            self.tokenizer = None

    def _count_tokens(self, text: str) -> int:
        """Estimates or calculates token counts using tiktoken or character ratios."""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        # Fallback estimation (~4 characters per token for English text)
        return max(1, len(text) // 4)

    def chunk_document(
        self, parsed_doc: ParsedDocument, document_id: str
    ) -> list[DocumentChunk]:
        """
        Transforms a ParsedDocument into a sequence of DocumentChunk instances.
        """
        chunks: list[DocumentChunk] = []
        chunk_idx = 0

        # 1. Process Text Elements into Sections
        sections = self._group_by_sections(parsed_doc.elements)

        for section_title, elements in sections:
            current_buffer: list[ParsedElement] = []
            current_tokens = 0
            current_page: int | None = None

            for elem in elements:
                elem_tokens = self._count_tokens(elem.text)

                # Update target page reference
                if elem.page_number:
                    current_page = elem.page_number

                # If adding this element exceeds the maximum token bound, flush the buffer
                if current_tokens + elem_tokens > self.max_chunk_tokens and current_buffer:
                    chunk_text = self._build_chunk_text(section_title, current_buffer)
                    chunk_token_cnt = self._count_tokens(chunk_text)

                    chunks.append(
                        DocumentChunk(
                            chunk_id=str(uuid.uuid4()),
                            document_id=document_id,
                            file_name=parsed_doc.file_name,
                            content=chunk_text,
                            chunk_index=chunk_idx,
                            token_count=chunk_token_cnt,
                            page_number=current_page,
                            section_header=section_title,
                            layout_type="text",
                            metadata={
                                "file_type": parsed_doc.file_type,
                                "element_count": len(current_buffer),
                            },
                        )
                    )
                    chunk_idx += 1

                    # Compute overlap elements
                    current_buffer = self._get_overlap_elements(current_buffer)
                    current_tokens = sum(self._count_tokens(e.text) for e in current_buffer)

                current_buffer.append(elem)
                current_tokens += elem_tokens

            # Flush remaining elements in section
            if current_buffer:
                chunk_text = self._build_chunk_text(section_title, current_buffer)
                chunk_token_cnt = self._count_tokens(chunk_text)

                chunks.append(
                    DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        file_name=parsed_doc.file_name,
                        content=chunk_text,
                        chunk_index=chunk_idx,
                        token_count=chunk_token_cnt,
                        page_number=current_page,
                        section_header=section_title,
                        layout_type="text",
                        metadata={
                            "file_type": parsed_doc.file_type,
                            "element_count": len(current_buffer),
                        },
                    )
                )
                chunk_idx += 1

        # 2. Process Extracted Tables as Independent Chunks
        if self.preserve_tables:
            for table in parsed_doc.tables:
                table_md = table.get("markdown", "").strip()
                if not table_md:
                    continue

                table_content = f"Table Data (Page {table.get('page_number', 1)}):\n\n{table_md}"
                token_cnt = self._count_tokens(table_content)

                chunks.append(
                    DocumentChunk(
                        chunk_id=str(uuid.uuid4()),
                        document_id=document_id,
                        file_name=parsed_doc.file_name,
                        content=table_content,
                        chunk_index=chunk_idx,
                        token_count=token_cnt,
                        page_number=table.get("page_number"),
                        layout_type="table",
                        metadata={
                            "row_count": table.get("row_count"),
                            "col_count": table.get("col_count"),
                            "is_table": True,
                        },
                    )
                )
                chunk_idx += 1

        logger.info(
            f"Successfully generated {len(chunks)} chunks for document '{parsed_doc.file_name}' (ID: {document_id})"
        )
        return chunks

    def _group_by_sections(
        self, elements: list[ParsedElement]
    ) -> list[tuple[str | None, list[ParsedElement]]]:
        """Groups sequential document elements under their active heading."""
        sections: list[tuple[str | None, list[ParsedElement]]] = []
        current_header: str | None = None
        current_elements: list[ParsedElement] = []

        for elem in elements:
            if elem.element_type in {"heading", "title", "section_header", "h1", "h2", "h3"}:
                if current_elements:
                    sections.append((current_header, current_elements))
                    current_elements = []
                current_header = elem.text
            current_elements.append(elem)

        if current_elements:
            sections.append((current_header, current_elements))

        return sections

    def _build_chunk_text(self, section_title: str | None, elements: list[ParsedElement]) -> str:
        """Assembles elements into a markdown string prefixed with section context."""
        body = "\n\n".join(e.text for e in elements)
        if section_title and not body.startswith(section_title):
            return f"### {section_title}\n\n{body}"
        return body

    def _get_overlap_elements(self, elements: list[ParsedElement]) -> list[ParsedElement]:
        """Retains trailing elements to construct token overlap between chunks."""
        overlap_elements: list[ParsedElement] = []
        accumulated_tokens = 0

        for elem in reversed(elements):
            elem_tokens = self._count_tokens(elem.text)
            if accumulated_tokens + elem_tokens > self.chunk_overlap_tokens:
                break
            overlap_elements.insert(0, elem)
            accumulated_tokens += elem_tokens

        return overlap_elements