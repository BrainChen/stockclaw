from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response

from app.api.routes import router
from app.core.config import get_settings

settings = get_settings()
app = FastAPI(title=settings.app_name)
project_root = Path(__file__).resolve().parent.parent
frontend_dist_dir = project_root / "frontend" / "dist"
frontend_index_file = frontend_dist_dir / "index.html"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")

@app.get("/", include_in_schema=False)
def index() -> Response:
    if frontend_index_file.exists():
        return FileResponse(frontend_index_file)
    return PlainTextResponse(
        "Frontend not built. Run: cd frontend && npm install && npm run build",
        status_code=503,
    )


@app.get("/{file_path:path}", include_in_schema=False)
def frontend_file(file_path: str) -> FileResponse:
    if file_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="Not Found")
    if not frontend_dist_dir.exists():
        raise HTTPException(status_code=404, detail="Not Found")

    candidate_file = (frontend_dist_dir / file_path).resolve()
    dist_root = frontend_dist_dir.resolve()
    if dist_root not in candidate_file.parents and candidate_file != dist_root:
        raise HTTPException(status_code=404, detail="Not Found")
    if candidate_file.is_file():
        return FileResponse(candidate_file)

    requested_name = Path(file_path).name
    if "." not in requested_name and frontend_index_file.exists():
        return FileResponse(frontend_index_file)
    raise HTTPException(status_code=404, detail="Not Found")
