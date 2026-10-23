"""HTTP translation for the document-work interface."""
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint

from .document_work import DocumentWork, PreviewFailed, PreviewReady
from .models import DocumentStatus, HealthResult, RenderRequest
from .repository import StoreError
from .settings import LIMITS


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    work = DocumentWork()
    app.state.document_work = work
    try:
        yield
    finally:
        work.close()


def get_document_work(request: Request) -> DocumentWork:
    work: object = request.app.state.document_work
    if not isinstance(work, DocumentWork):
        raise RuntimeError("Document work is not initialized.")
    return work


WorkDependency = Annotated[DocumentWork, Depends(get_document_work)]

app = FastAPI(title="CAD Layer Explorer", lifespan=lifespan, docs_url=None,
              redoc_url=None, openapi_url="/api/openapi.json")


@app.exception_handler(StoreError)
async def store_error(request: Request, exc: StoreError) -> JSONResponse:
    return JSONResponse({"error": {"code": exc.code, "message": exc.message}}, status_code=exc.status)


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse({"error": {"code": "invalid_request", "message": "Invalid request. Check page, layer IDs, mode, and render scale."}}, status_code=422)


@app.exception_handler(OSError)
@app.exception_handler(sqlite3.Error)
async def storage_error(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse({"error": {"code": "storage_failure", "message": "Local storage is unavailable. Check disk space and permissions, then retry."}}, status_code=507)


@app.middleware("http")
async def headers(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/health")
def health() -> HealthResult:
    return {"status": "ok", "limits": LIMITS}


@app.post("/api/documents")
def upload(work: WorkDependency, file: UploadFile = File(...)) -> JSONResponse:
    try:
        result = work.upload(file.file, file.filename or "drawing.pdf")
        return JSONResponse(result, status_code=200 if result["state"] == "succeeded" else 202)
    finally:
        file.file.close()


@app.get("/api/documents")
def documents(work: WorkDependency) -> list[DocumentStatus]:
    return work.list_documents()


@app.get("/api/documents/{digest}/status")
def status(digest: str, work: WorkDependency) -> DocumentStatus:
    return work.status(digest)


@app.post("/api/documents/{digest}/analysis")
def retry(digest: str, work: WorkDependency) -> JSONResponse:
    result = work.retry_analysis(digest)
    return JSONResponse(result, status_code=200 if result["state"] == "succeeded" else 202)


@app.get("/api/documents/{digest}/analysis")
def analysis(digest: str, work: WorkDependency, download: bool = False) -> Response:
    artifact = work.read_analysis(digest)
    return Response(artifact.data, media_type="application/json", headers={
        "ETag": f'"{artifact.identity}"',
        **({"Content-Disposition": 'attachment; filename="cad-analysis.json"'} if download else {})})


@app.post("/api/documents/{digest}/renders")
def render(digest: str, request: RenderRequest, work: WorkDependency) -> JSONResponse:
    result = work.request_render(digest, request)
    return JSONResponse(result, status_code=200 if result["state"] == "succeeded" else 202)


@app.get("/api/renders/{key}")
def artifact(key: str, work: WorkDependency) -> Response:
    result = work.read_preview(key)
    if isinstance(result, PreviewReady):
        return Response(result.data, media_type="image/png")
    if isinstance(result, PreviewFailed):
        return JSONResponse({"error": result.error, "retry_action": "POST renders"}, status_code=422)
    return JSONResponse({"state": result.state, "url": result.url}, status_code=202)


@app.delete("/api/documents/{digest}", status_code=204)
def delete(digest: str, work: WorkDependency) -> Response:
    work.delete(digest)
    return Response(status_code=204)


app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="frontend")
