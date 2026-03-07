from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=2, description="用户问题")


class SourceItem(BaseModel):
    source_type: Literal["kb", "web", "market"]
    title: str
    content: str
    url: Optional[str] = None
    score: Optional[float] = None


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
