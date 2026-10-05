from enum import Enum
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field, HttpUrl
from datetime import datetime


class DocumentType(str, Enum):
    PDF = "pdf"
    DOCX = "docx"
    SCANNED = "scanned"
    IMAGE = "image"
    HTML = "html"


class ChunkType(str, Enum):
    TEXT = "text"
    HEADER = "header"
    TABLE = "table"
    IMAGE_CAPTION = "image_caption"
    LIST_ITEM = "list_item"
    FOOTNOTE = "footnote"


class ReviewStatus(str, Enum):
    APPROVED = "approved"
    PENDING_REVIEW = "pending_review"
    REJECTED = "rejected"
    AUTO_PASSED = "auto_passed"


class BoundingBox(BaseModel):
    """Normalized bounding box coordinates (0.0 - 1.0) for page layout elements."""
    l: float = Field(..., description="Left coordinate")
    t: float = Field(..., description="Top coordinate")
    r: float = Field(..., description="Right coordinate")
    b: float = Field(..., description="Bottom coordinate")
    coord_origin: str = Field(default="TOPLEFT", description="Coordinate origin (TOPLEFT or BOTTOMLEFT)")


class ExtractedField(BaseModel):
    """Key-value extraction with field-level confidence and source provenance."""
    key: str = Field(..., description="Attribute or schema field name")
    value: Any = Field(..., description="Extracted value (str, int, float, list, etc.)")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Extraction confidence score")
    page_number: Optional[int] = Field(default=None, description="Page number where key was found")
    bbox: Optional[BoundingBox] = Field(default=None, description="Bounding box on page")
    requires_human_review: bool = Field(default=False, description="Flagged if confidence < threshold")


class TableCell(BaseModel):
    """Cell-level details inside structured tables."""
    row_index: int
    col_index: int
    content: str
    is_header: bool = False
    row_span: int = 1
    col_span: int = 1


class TableData(BaseModel):
    """Structured representation of extracted tables."""
    headers: List[str] = Field(default_factory=list)
    rows: List[List[str]] = Field(default_factory=list)
    cells: List[TableCell] = Field(default_factory=list, description="Cell-level layout mapping")
    caption: Optional[str] = None
    page_number: Optional[int] = None
    bbox: Optional[BoundingBox] = None


class DocumentChunk(BaseModel):
    """A structure-aware chunk extracted from a parent document."""
    chunk_id: str = Field(..., description="Unique chunk hash or UUID")
    document_id: str = Field(..., description="Parent document identifier")
    page_number: int = Field(..., description="Exact source page number (1-indexed)")
    content: str = Field(..., description="Text payload or markdown table representation")
    chunk_type: ChunkType = Field(default=ChunkType.TEXT, description="Type of layout element")
    section_header: Optional[str] = Field(default=None, description="Enclosing heading/section title")
    heading_level: Optional[int] = Field(default=None, description="H1, H2, H3 hierarchy level if applicable")
    bbox: Optional[BoundingBox] = Field(default=None, description="Bounding box on page for citation UI highlight")
    token_count: Optional[int] = Field(default=None, description="Token length using model tokenizer")
    embedding_id: Optional[str] = Field(default=None, description="Reference ID in Qdrant vector store")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom document attributes")


class PageMetadata(BaseModel):
    """Page-level extraction details."""
    page_number: int
    width: Optional[float] = Field(default=None, description="Page width in points/pixels")
    height: Optional[float] = Field(default=None, description="Page height in points/pixels")
    text_length: int
    table_count: int = 0
    image_count: int = 0
    has_tables: bool = False
    has_images: bool = False


class ExtractionAuditTrail(BaseModel):
    """Provenance and audit information for governance."""
    pipeline_version: str = Field(default="1.0.0")
    parser_name: str = Field(default="DoclingLayoutParser")
    model_name: str = Field(default="llama3.1:8b")
    processed_at: datetime = Field(default_factory=datetime.utcnow)
    processing_time_ms: Optional[float] = None


class ProcessedDocument(BaseModel):
    """Master record output by the ingestion and analysis pipeline."""
    document_id: str
    filename: str
    file_type: DocumentType
    file_hash: str = Field(..., description="SHA256 checksum for deduplication")
    file_size_bytes: Optional[int] = None
    page_count: int
    
    # Structural hierarchy
    pages: List[PageMetadata] = Field(default_factory=list)
    chunks: List[DocumentChunk] = Field(default_factory=list)
    tables: List[TableData] = Field(default_factory=list)
    
    # Key-value extraction with confidence tracking
    extracted_fields: Dict[str, ExtractedField] = Field(default_factory=dict)
    
    # Quality & Governance
    overall_confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    review_status: ReviewStatus = Field(default=ReviewStatus.AUTO_PASSED)
    flagged_reasons: List[str] = Field(default_factory=list, description="Reasons triggering HITL review")
    
    audit: ExtractionAuditTrail = Field(default_factory=ExtractionAuditTrail)
    created_at: datetime = Field(default_factory=datetime.utcnow)