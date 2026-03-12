from pathlib import Path
from time import perf_counter
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse

from app.common.logger import get_logger, kv, preview_text
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    KBReindexRequest,
    KBSearchRequest,
    KBSearchResponse,
    KBStatsResponse,
)
from app.services.layers.orchestration.answer_service import FinancialQAService

router = APIRouter()
qa_service = FinancialQAService()
logger = get_logger(__name__)


def _resolve_kb_file(path: str) -> Path:
    kb_root = qa_service.rag_service.kb_dir.resolve()
    raw_path = Path(path.strip())

    candidates: list[Path] = []
    if raw_path.is_absolute():
        candidates.append(raw_path.resolve())
    else:
        candidates.append((Path.cwd() / raw_path).resolve())
        candidates.append((kb_root / raw_path).resolve())

    for candidate in candidates:
        if candidate.is_file() and (candidate == kb_root or kb_root in candidate.parents):
            return candidate
    raise HTTPException(status_code=404, detail="知识库文档不存在或路径非法")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


@router.post("/chat", response_model=ChatResponse)
def chat(
    payload: ChatRequest,
    format: Literal["json", "md"] = Query(
        default="json",
        description="返回格式：json 或 md（Markdown 文本）",
    ),
    accept: str | None = Header(default=None),
) -> ChatResponse | PlainTextResponse:
    request_id = uuid4().hex[:12]
    started_at = perf_counter()
    logger.info(
        "chat request %s",
        kv(
            request_id=request_id,
            format=format,
            accept=accept or "",
            question=preview_text(payload.question, max_len=120),
        ),
    )
    try:
        result = qa_service.ask(payload.question)
        wants_markdown = format == "md" or (
            format == "json"
            and isinstance(accept, str)
            and "text/markdown" in accept.lower()
        )
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.info(
            "chat response %s",
            kv(
                request_id=request_id,
                route=result.route,
                symbol=result.symbol or "",
                source_count=len(result.sources),
                latency_ms=elapsed_ms,
                markdown=wants_markdown,
            ),
        )
        if wants_markdown:
            return PlainTextResponse(
                content=result.answer,
                media_type="text/markdown; charset=utf-8",
            )
        return result
    except ValueError as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.warning(
            "chat validation failed %s",
            kv(request_id=request_id, latency_ms=elapsed_ms, error=str(exc)),
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started_at) * 1000)
        logger.exception(
            "chat internal error %s",
            kv(request_id=request_id, latency_ms=elapsed_ms, error=str(exc)),
        )
        raise HTTPException(status_code=500, detail=f"系统异常: {exc}") from exc


@router.get("/kb/stats", response_model=KBStatsResponse)
def kb_stats() -> KBStatsResponse:
    try:
        stats = qa_service.kb_stats()
        logger.info("kb stats %s", kv(indexed_files=stats.get("indexed_files"), indexed_chunks=stats.get("indexed_chunks")))
        return KBStatsResponse(**stats)
    except Exception as exc:
        logger.exception("kb stats failed %s", kv(error=str(exc)))
        raise HTTPException(status_code=500, detail=f"知识库统计失败: {exc}") from exc


@router.post("/kb/reindex", response_model=KBStatsResponse)
def kb_reindex(payload: KBReindexRequest | None = None) -> KBStatsResponse:
    try:
        force = payload.force if payload else True
        logger.info("kb reindex start %s", kv(force=force))
        stats = qa_service.reindex_kb(force=force)
        logger.info("kb reindex done %s", kv(indexed_files=stats.get("indexed_files"), indexed_chunks=stats.get("indexed_chunks")))
        return KBStatsResponse(**stats)
    except Exception as exc:
        logger.exception("kb reindex failed %s", kv(error=str(exc)))
        raise HTTPException(status_code=500, detail=f"知识库重建失败: {exc}") from exc


@router.post("/kb/search", response_model=KBSearchResponse)
def kb_search(payload: KBSearchRequest) -> KBSearchResponse:
    try:
        logger.info("kb search request %s", kv(query=preview_text(payload.query, max_len=100), top_k=payload.top_k))
        hits = qa_service.search_kb(query=payload.query, top_k=payload.top_k)
        logger.info("kb search response %s", kv(total_hits=len(hits)))
        return KBSearchResponse(query=payload.query, total_hits=len(hits), hits=hits)
    except ValueError as exc:
        logger.warning("kb search validation failed %s", kv(error=str(exc)))
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("kb search failed %s", kv(error=str(exc)))
        raise HTTPException(status_code=500, detail=f"知识库检索失败: {exc}") from exc


@router.get("/kb/document")
def kb_document(path: str = Query(..., min_length=1, description="知识库文档路径")) -> FileResponse:
    target_file = _resolve_kb_file(path)

    suffix = target_file.suffix.lower()
    media_type = "application/octet-stream"
    if suffix in [".md", ".txt", ".json", ".csv"]:
        media_type = "text/plain; charset=utf-8"
    elif suffix == ".pdf":
        media_type = "application/pdf"

    return FileResponse(path=target_file, media_type=media_type, filename=target_file.name)


@router.get("/kb/document/preview", response_class=HTMLResponse)
def kb_document_preview(path: str = Query(..., min_length=1, description="知识库文档路径")) -> HTMLResponse:
    target_file = _resolve_kb_file(path)
    suffix = target_file.suffix.lower()

    if suffix == ".pdf":
        html = f"""
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>{target_file.name}</title></head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; padding: 20px;">
  <h2>{target_file.name}</h2>
  <p>该文件为 PDF，点击下方按钮打开原文件。</p>
  <p><a href="/api/kb/document?path={path}" target="_blank" rel="noopener noreferrer">打开 PDF 原文件</a></p>
</body>
</html>
"""
        return HTMLResponse(content=html)

    raw_text = target_file.read_text(encoding="utf-8", errors="ignore")
    html_body = ""
    if suffix == ".md":
        try:
            import markdown
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"缺少 markdown 依赖: {exc}") from exc
        html_body = markdown.markdown(
            raw_text,
            extensions=["fenced_code", "tables", "nl2br", "sane_lists"],
            output_format="html5",
        )
    else:
        escaped = (
            raw_text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
        html_body = f"<pre>{escaped}</pre>"

    page_html = f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{target_file.name}</title>
  <style>
    body {{
      margin: 0;
      padding: 24px;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif;
      color: #1f2937;
      background: #f8fafc;
      line-height: 1.75;
    }}
    main {{
      max-width: 980px;
      margin: 0 auto;
      background: #ffffff;
      border: 1px solid #e5e7eb;
      border-radius: 12px;
      padding: 28px;
      box-shadow: 0 8px 20px rgba(15, 23, 42, 0.06);
    }}
    h1, h2, h3 {{ line-height: 1.35; margin-top: 1.2em; }}
    h1:first-child {{ margin-top: 0; }}
    pre, code {{
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
    }}
    pre {{
      background: #0f172a;
      color: #e2e8f0;
      border-radius: 8px;
      padding: 14px;
      overflow-x: auto;
    }}
    table {{ border-collapse: collapse; width: 100%; overflow-x: auto; display: block; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px 10px; text-align: left; }}
    thead th {{ background: #f1f5f9; }}
    blockquote {{
      margin: 12px 0;
      border-left: 4px solid #93c5fd;
      padding: 8px 14px;
      color: #334155;
      background: #f8fbff;
    }}
    .meta {{
      font-size: 13px;
      color: #64748b;
      margin-bottom: 16px;
    }}
  </style>
</head>
<body>
  <main>
    <div class="meta">来源文件：{target_file.as_posix()}</div>
    {html_body}
  </main>
</body>
</html>
"""
    return HTMLResponse(content=page_html)
