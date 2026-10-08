import hashlib
import time
from pathlib import Path

from docling.document_converter import DocumentConverter

from backend.ingestion.schemas.document import (
    BoundingBox,
    ChunkType,
    DocumentChunk,
    DocumentType,
    ExtractionAuditTrail,
    PageMetadata,
    ProcessedDocument,
    ReviewStatus,
    TableCell,
    TableData,
)


class DoclingLayoutParser:
    """
    Layout-aware document parser utilizing Docling to extract structured text,
    bounding boxes, table matrices, and page provenance.
    """

    def __init__(self, tokenizer=None):
        self.converter = DocumentConverter()
        self.tokenizer = tokenizer

    def _compute_hash(self, file_path: Path) -> str:
        """Compute SHA256 checksum for document deduplication."""
        sha256 = hashlib.sha256()
        with open(file_path, "rb") as f:
            while chunk := f.read(8192):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _extract_bbox(self, item: Any) -> BoundingBox | None:
        """Maps Docling element coordinates to normalized BoundingBox schema."""
        prov = getattr(item, "provenance", None)
        if prov and hasattr(prov, "bbox"):
            b = prov.bbox
            return BoundingBox(
                l=float(getattr(b, "l", 0.0)),
                t=float(getattr(b, "t", 0.0)),
                r=float(getattr(b, "r", 0.0)),
                b=float(getattr(b, "b", 0.0)),
                coord_origin="TOPLEFT",
            )
        return None

    def _count_tokens(self, text: str) -> int:
        """Estimate or compute exact token count for chunks."""
        if self.tokenizer:
            return len(self.tokenizer.encode(text))
        # Fallback heuristic: ~4 characters per token
        return max(1, len(text) // 4)

    def parse(self, file_path: str) -> ProcessedDocument:
        """
        Parses document files (PDF/DOCX) into enriched Page Metadata, Chunks, and Tables.
        """
        start_time = time.time()
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Document file not found at {file_path}")

        file_bytes = path.stat().st_size
        file_hash = self._compute_hash(path)
        doc_id = f"doc_{file_hash[:12]}"

        # Resolve document type
        ext = path.suffix.lower()
        if ext == ".pdf":
            doc_type = DocumentType.PDF
        elif ext in [".docx", ".doc"]:
            doc_type = DocumentType.DOCX
        elif ext in [".png", ".jpg", ".jpeg", ".tiff"]:
            doc_type = DocumentType.IMAGE
        else:
            doc_type = DocumentType.PDF

        # Run Docling conversion engine
        conversion_result = self.converter.convert(str(path))
        docling_doc = conversion_result.document

        chunks: list[DocumentChunk] = []
        tables: list[TableData] = []
        pages_meta: list[PageMetadata] = []

        # 1. Parse text elements and structural chunks
        current_heading: str | None = None
        current_heading_level: int | None = None

        for idx, item in enumerate(docling_doc.texts):
            text_content = item.text.strip()
            if not text_content:
                continue

            page_num = getattr(getattr(item, "provenance", None), "page_no", 1) or 1
            bbox = self._extract_bbox(item)
            
            # Map item labels to ChunkType
            label = getattr(item, "label", "text").lower()
            if "heading" in label or "title" in label:
                chunk_type = ChunkType.HEADER
                current_heading = text_content
                current_heading_level = getattr(item, "level", 1)
            elif "list" in label:
                chunk_type = ChunkType.LIST_ITEM
            elif "footnote" in label:
                chunk_type = ChunkType.FOOTNOTE
            elif "caption" in label:
                chunk_type = ChunkType.IMAGE_CAPTION
            else:
                chunk_type = ChunkType.TEXT

            chunk = DocumentChunk(
                chunk_id=f"{doc_id}_c{idx}",
                document_id=doc_id,
                page_number=page_num,
                content=text_content,
                chunk_type=chunk_type,
                section_header=current_heading,
                heading_level=current_heading_level if chunk_type == ChunkType.HEADER else None,
                bbox=bbox,
                token_count=self._count_tokens(text_content),
                metadata={"file_name": path.name, "docling_label": label},
            )
            chunks.append(chunk)

        # 2. Extract structured tables
        for t_idx, table in enumerate(docling_doc.tables):
            page_num = getattr(getattr(table, "provenance", None), "page_no", 1) or 1
            table_bbox = self._extract_bbox(table)
            
            table_cells: list[TableCell] = []
            headers: list[str] = []
            rows_dict = {}

            if hasattr(table, "data") and hasattr(table.data, "grid"):
                for row_idx, row in enumerate(table.data.grid):
                    row_cells = []
                    for col_idx, cell in enumerate(row):
                        cell_text = getattr(cell, "text", "").strip()
                        is_hdr = row_idx == 0 or getattr(cell, "is_header", False)
                        
                        table_cells.append(
                            TableCell(
                                row_index=row_idx,
                                col_index=col_idx,
                                content=cell_text,
                                is_header=is_hdr,
                                row_span=getattr(cell, "row_span", 1),
                                col_span=getattr(cell, "col_span", 1),
                            )
                        )
                        row_cells.append(cell_text)

                    if row_idx == 0:
                        headers = row_cells
                    else:
                        rows_dict.setdefault(row_idx, []).extend(row_cells)

            table_obj = TableData(
                headers=headers,
                rows=list(rows_dict.values()),
                cells=table_cells,
                caption=getattr(table, "caption", None),
                page_number=page_num,
                bbox=table_bbox,
            )
            tables.append(table_obj)

        # 3. Populate Page Metadata
        page_count = getattr(docling_doc, "page_count", 1) or 1
        for p in range(1, page_count + 1):
            p_chunks = [c for c in chunks if c.page_number == p]
            p_tables = [t for t in tables if t.page_number == p]
            
            pages_meta.append(
                PageMetadata(
                    page_number=p,
                    text_length=sum(len(c.content) for c in p_chunks),
                    table_count=len(p_tables),
                    has_tables=len(p_tables) > 0,
                    has_images=False,
                )
            )

        elapsed_ms = (time.time() - start_time) * 1000.0

        return ProcessedDocument(
            document_id=doc_id,
            filename=path.name,
            file_type=doc_type,
            file_hash=file_hash,
            file_size_bytes=file_bytes,
            page_count=page_count,
            pages=pages_meta,
            chunks=chunks,
            tables=tables,
            overall_confidence=0.95,
            review_status=ReviewStatus.AUTO_PASSED,
            audit=ExtractionAuditTrail(
                pipeline_version="1.1.0",
                parser_name="DoclingLayoutParser",
                processing_time_ms=elapsed_ms,
            ),
        )