"""FastAPI entrypoint. Routes are thin; business logic lives in app/services."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api import datasets, process, research
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, log_event, request_id_var

settings = get_settings()
configure_logging(settings.log_level)
logger = logging.getLogger("app")

app = FastAPI(
    title="AI Process Mining Agent",
    version="1.0.0",
    description=("Event logs → process discovery → metrics → bottlenecks → deviations → variants → AI explanation. "
                 "The deterministic engine works without an LLM; the AI layer only explains computed metrics."),
)
app.add_middleware(CORSMiddleware, allow_origins=list(settings.cors_origins), allow_methods=["GET", "POST", "DELETE"],
                   allow_headers=["*"], expose_headers=["X-Request-ID"])


@app.middleware("http")
async def request_context(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex[:16]
    token = request_id_var.set(rid)
    t0 = time.perf_counter()
    status = 500
    try:
        response = await call_next(request)
        status = response.status_code
        response.headers["X-Request-ID"] = rid
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response
    finally:
        log_event(logger, "http.request", method=request.method, path=request.url.path, status=status,
                  processing_ms=int((time.perf_counter() - t0) * 1000))
        request_id_var.reset(token)


@app.exception_handler(AppError)
async def app_error(_: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={"error": exc.message, "details": exc.details,
                                                              "request_id": request_id_var.get()})


@app.exception_handler(RequestValidationError)
async def validation_error(_: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={"error": "Invalid request.",
                                                  "details": {"errors": jsonable_encoder(exc.errors())},
                                                  "request_id": request_id_var.get()})


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception):
    logger.exception("unhandled_error")
    return JSONResponse(status_code=500, content={
        "error": "Unexpected server error. The backend log has the details under this request id.",
        "request_id": request_id_var.get()})


@app.get("/api/health")
def health():
    return {"status": "ok", "llm_enabled": settings.llm_enabled}


app.include_router(datasets.router)
app.include_router(process.router)
app.include_router(research.research_router)
app.include_router(research.query_router)
