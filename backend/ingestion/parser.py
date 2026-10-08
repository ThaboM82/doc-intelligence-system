import asyncio
import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Docling imports with graceful import guards
try:
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption
    DOCLING_AVAILABLE = True
except ImportError:
    DOCLING_AVAILABLE = False

# Fallback imports
try:
    import pypdf
    PYPDF_AVAILABLE = True
except ImportError:
    PYPDF_AVAILABLE = False

logger = logging.getLogger(__name__)


class ParsedElement(BaseModel):
    """Represents a single structural element extracted from a document."""

    id: str
    text: str
    element_type: str  # 'heading', 'paragraph', 'table', 'list_item', 'code', 'title'
    page_number: int | None = None
    section_header: str | None = None
    bounding_box: dict[str, float] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ParsedDocument(BaseModel):
    """Container holding document structural representation and metadata."""

    file_path: str
    file_name: str
    file_type: str
    num_pages: int
    elements: list[ParsedElement] = Field(default_factory=list)
    tables: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentParser:
    """
    Layout-aware document parser using Docling with automatic fallback
    to PyPDF/text extractors for robust multi-format support.
    """

    SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".pptx", ".html", ".htm", ".txt", ".png", ".jpg", ".jpeg"}

    def __init__(self, enable_ocr: bool = True, do_table_structure: bool = True):
        self.enable_ocr = enable_ocr
        self.do_table_structure = do_table_structure
        self._converter = self._build_docling_converter() if DOCLING_AVAILABLE else None

    def _build_docling_converter(self) -> Any | None:
        """Configures Docling conversion pipeline options."""
        if not DOCLING_AVAILABLE:
            logger.warning("Docling is not installed. Defaulting to lightweight fallback parsers.")
            return None

        try:
            pipeline_options = PdfPipelineOptions()
            pipeline_options.do_ocr = self.enable_ocr
            pipeline_options.do_table_structure = self.do_table_structure

            if self.do_table_structure:
                pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

            format_options = {
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }

            return DocumentConverter(format_options=format_options)
        except Exception as e:
            logger.error(f"Failed to initialize Docling converter: {e}")
            return None

    async def parse_document(self, file_path: str) -> ParsedDocument:
        """
        Main entry point for parsing documents asynchronously.
        Routes execution off the main loop to handle blocking file I/O.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Target document not found at: {file_path}")

        ext = path.suffix.lower()
        if ext not in self.SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file format '{ext}'. Supported: {self.SUPPORTED_EXTENSIONS}")

        logger.info(f"Starting parsing job for: {path.name}")

        # Run heavy synchronous document parsing in an executor thread
        return await asyncio.to_thread(self._sync_parse_document, path)

    def _sync_parse_document(self, path: Path) -> ParsedDocument:
        """Synchronous internal parser dispatcher."""
        ext = path.suffix.lower()

        # Strategy 1: Docling primary engine (PDF, DOCX, HTML, Images)
        if self._converter and ext in {".pdf", ".docx", ".pptx", ".html", ".htm", ".png", ".jpg", ".jpeg"}:
            try:
                return self._parse_with_docling(path)
            except Exception as e:
                logger.warning(f"Docling parsing failed for {path.name}: {e}. Falling back to native parsers.")

        # Strategy 2: Fallback text/PDF processing
        if ext == ".txt":
            return self._parse_plain_text(path)
        elif ext == ".pdf":
            return self._parse_pdf_fallback(path)
        else:
            return self._parse_plain_text(path)

    def _parse_with_docling(self, path: Path) -> ParsedDocument:
        """Parses complex formats via Docling."""
        conversion_result = self._converter.convert(str(path))
        doc = conversion_result.document

        elements: list[ParsedElement] = []
        tables: list[dict[str, Any]] = []

        current_heading: str | None = None

        # Process structural text nodes
        for idx, item in enumerate(doc.texts):
            label = str(getattr(item, "label", "paragraph")).lower()
            text_str = item.text.strip()
            if not text_str:
                continue

            page_num = item.prov[0].page_no if hasattr(item, "prov") and item.prov else 1

            if label in {"heading", "title", "section_header", "h1", "h2", "h3"}:
                current_heading = text_str

            elements.append(
                ParsedElement(
                    id=f"docling_elem_{idx}",
                    text=text_str,
                    element_type=label,
                    page_number=page_num,
                    section_header=current_heading,
                    metadata={"docling_label": label},
                )
            )

        # Process structured tables
        for table_idx, table in enumerate(doc.tables):
            table_df = table.export_to_dataframe()
            page_num = table.prov[0].page_no if table.prov else 1
            md_content = table.export_to_markdown()

            tables.append(
                {
                    "table_index": table_idx,
                    "page_number": page_num,
                    "csv_data": table_df.to_csv(index=False),
                    "markdown": md_content,
                    "row_count": len(table_df),
                    "col_count": len(table_df.columns),
                }
            )

        num_pages = getattr(doc, "num_pages", 1)

        return ParsedDocument(
            file_path=str(path),
            file_name=path.name,
            file_type=path.suffix.lower(),
            num_pages=num_pages,
            elements=elements,
            tables=tables,
            metadata={
                "parser_engine": "Docling",
                "total_elements": len(elements),
                "total_tables": len(tables),
            },
        )

    def _parse_pdf_fallback(self, path: Path) -> ParsedDocument:
        """Fallback PDF reader using PyPDF."""
        if not PYPDF_AVAILABLE:
            raise RuntimeError("PyPDF is required for fallback PDF parsing. Run `pip install pypdf`.")

        elements: list[ParsedElement] = []
        reader = pypdf.PdfReader(str(path))
        elem_idx = 0

        for page_num, page in enumerate(reader.pages, start=1):
            page_text = page.extract_text() or ""
            paragraphs = [p.strip() for p in page_text.split("\n\n") if p.strip()]

            for p in paragraphs:
                is_header = len(p) < 80 and not p.endswith(".")
                elements.append(
                    ParsedElement(
                        id=f"pypdf_elem_{elem_idx}",
                        text=p,
                        element_type="heading" if is_header else "paragraph",
                        page_number=page_num,
                        metadata={"fallback_engine": "PyPDF"},
                    )
                )
                elem_idx += 1

        return ParsedDocument(
            file_path=str(path),
            file_name=path.name,
            file_type=".pdf",
            num_pages=len(reader.pages),
            elements=elements,
            metadata={"parser_engine": "PyPDF_Fallback"},
        )

    def _parse_plain_text(self, path: Path) -> ParsedDocument:
        """Simple plain text file parser."""
        content = path.read_text(encoding="utf-8", errors="ignore")
        paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

        elements = [
            ParsedElement(
                id=f"txt_elem_{idx}",
                text=p,
                element_type="paragraph",
                page_number=1,
            )
            for idx, p in enumerate(paragraphs)
        ]

        return ParsedDocument(
            file_path=str(path),
            file_name=path.name,
            file_type=path.suffix.lower(),
            num_pages=1,
            elements=elements,
            metadata={"parser_engine": "PlainText"},
        )