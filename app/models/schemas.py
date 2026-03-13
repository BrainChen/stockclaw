from typing import Any, Dict, List, Literal, Optional

from pydantic import AliasChoices, BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=2,
        description="用户问题",
        validation_alias=AliasChoices("question", "query"),
    )


class SourceItem(BaseModel):
    source_type: Literal["kb", "web", "market"]
    title: str
    content: str
    url: Optional[str] = None
    score: Optional[float] = None
    path: Optional[str] = None
    chunk_id: Optional[str] = None


class ChatResponse(BaseModel):
    route: Literal["asset", "knowledge"]
    symbol: Optional[str] = None
    answer: str
    objective_data: Dict[str, Any] = Field(default_factory=dict)
    analysis: List[str] = Field(default_factory=list)
    sources: List[SourceItem] = Field(default_factory=list)


class KBReindexRequest(BaseModel):
    force: bool = Field(default=False, description="是否强制重建")


class KBStatsResponse(BaseModel):
    kb_dir: str
    indexed_files: int
    indexed_chunks: int
    supported_extensions: List[str]
    chunk_size: int
    chunk_overlap: int
    vector_backend: Optional[str] = None
    index_size: Optional[int] = None
    embedding_dim: Optional[int] = None
    index_dir: Optional[str] = None
    loaded_from_disk: Optional[bool] = None


class KBSearchRequest(BaseModel):
    query: str = Field(..., min_length=2, description="检索问题")
    top_k: int = Field(default=5, ge=1, le=20, description="返回条数")


class KBSearchHit(BaseModel):
    source_type: Literal["kb"]
    title: str
    content: str
    score: Optional[float] = None
    url: Optional[str] = None
    path: Optional[str] = None
    chunk_id: Optional[str] = None


class KBSearchResponse(BaseModel):
    query: str
    total_hits: int
    hits: List[KBSearchHit]


class EastmoneyRealtimeResponse(BaseModel):
    quote_url: str
    market: Literal["cn_a", "hk", "us"]
    symbol: str
    secid: str
    exchange_timezone: str
    phase: Literal["pre_market", "intraday", "post_market", "closed"]
    phase_checked_at: str
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    session_analysis: Dict[str, Any] = Field(default_factory=dict)
    session_points: Dict[str, Any] = Field(default_factory=dict)
    trend_points_count: int = 0
    resource_urls: List[str] = Field(default_factory=list)
