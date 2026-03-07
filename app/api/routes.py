from fastapi import APIRouter, HTTPException

from app.models.schemas import ChatRequest, ChatResponse, KBReindexRequest, KBStatsResponse
from app.services.answer_service import FinancialQAService

router = APIRouter()
qa_service = FinancialQAService()


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> ChatResponse:
    try:
        return qa_service.ask(payload.question)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"系统异常: {exc}") from exc


@router.get("/kb/stats", response_model=KBStatsResponse)
def kb_stats() -> KBStatsResponse:
    try:
        stats = qa_service.kb_stats()
        return KBStatsResponse(**stats)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"知识库统计失败: {exc}") from exc


@router.post("/kb/reindex", response_model=KBStatsResponse)
def kb_reindex(payload: KBReindexRequest | None = None) -> KBStatsResponse:
    try:
        force = payload.force if payload else True
        stats = qa_service.reindex_kb(force=force)
        return KBStatsResponse(**stats)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"知识库重建失败: {exc}") from exc
