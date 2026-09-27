from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.repositories.datasets import DatasetRepository
from app.schemas.api import AnalyzeRequest, QueryRequest, QueryResponse
from app.services.ai_analysis.llm import LLMClient, estimate_cost, shared_client
from app.services.ai_analysis.prompts import PROMPT_VERSION
from app.services.ai_analysis.query import answer_question
from app.services.ai_analysis.query_tools import QueryTools
from app.services.ai_analysis.report import (
    AnalysisReport,
    generate_report,
    report_to_markdown,
)
from app.services.analysis_service import get_analysis

research_router = APIRouter(prefix="/api/research", tags=["ai"])
query_router = APIRouter(prefix="/api/query", tags=["ai"])


def _record_run(repo: DatasetRepository, dataset_id: str, kind: str, client: LLMClient | None, meta: dict,
                question: str | None, output: dict):
    return repo.save_ai_run(
        dataset_id=dataset_id, kind=kind, mode=meta["mode"], model=client.model if client else None,
        prompt_version=PROMPT_VERSION, input_chars=meta["input_chars"], input_tokens=meta["input_tokens"],
        output_tokens=meta["output_tokens"], llm_calls=meta["llm_calls"], latency_ms=meta["total_ms"],
        cost_usd=estimate_cost(get_settings(), meta["input_tokens"], meta["output_tokens"]),
        question=question, output=output, error=meta.get("error"),
    )


@research_router.get("/status")
def ai_status():
    s = get_settings()
    return {"llm_enabled": s.llm_enabled, "provider": s.llm_provider, "model": s.llm_model if s.llm_enabled else None,
            "prompt_version": PROMPT_VERSION}


@research_router.post("/{dataset_id}/analyze")
def analyze(dataset_id: str, body: AnalyzeRequest | None = None, session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    ds = repo.get(dataset_id)
    engine_result = get_analysis(session, dataset_id)
    client = shared_client()
    focus = body.focus if body else None
    report, meta = generate_report(client, engine_result.results, ds.validation_report, focus)
    run = _record_run(repo, dataset_id, "report", client, meta, focus, report.model_dump())
    return {"run_id": run.id, "report": report.model_dump(), "meta": meta | {"llm_error": meta.get("error")}}


@research_router.get("/{dataset_id}/latest")
def latest(dataset_id: str, session: Session = Depends(get_session)):
    run = DatasetRepository(session).latest_ai_run(dataset_id, "report")
    if not run:
        raise NotFoundError("No analysis report yet. POST /api/research/{dataset_id}/analyze to create one.")
    return {"run_id": run.id, "created_at": run.created_at, "report": run.output}


@research_router.get("/{dataset_id}/report.md")
def latest_markdown(dataset_id: str, session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    ds = repo.get(dataset_id)
    run = repo.latest_ai_run(dataset_id, "report")
    if not run:
        raise NotFoundError("No analysis report yet.")
    md = report_to_markdown(AnalysisReport.model_validate(run.output), ds.name)
    return Response(md, media_type="text/markdown",
                    headers={"Content-Disposition": f'attachment; filename="analysis_{dataset_id[:8]}.md"'})


@research_router.get("/{dataset_id}/runs")
def runs(dataset_id: str, session: Session = Depends(get_session)):
    return [{"id": r.id, "kind": r.kind, "mode": r.mode, "model": r.model, "prompt_version": r.prompt_version,
             "input_chars": r.input_chars, "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
             "llm_calls": r.llm_calls, "latency_ms": r.latency_ms, "cost_usd": r.cost_usd,
             "question": r.question, "error": r.error, "created_at": r.created_at}
            for r in DatasetRepository(session).ai_runs(dataset_id)]


@query_router.post("/{dataset_id}", response_model=QueryResponse)
def query(dataset_id: str, body: QueryRequest, session: Session = Depends(get_session)):
    repo = DatasetRepository(session)
    ds = repo.get(dataset_id)
    engine_result = get_analysis(session, dataset_id)
    client = shared_client()
    tools = QueryTools(engine_result, ds.validation_report)
    out, meta = answer_question(client, tools, body.question, [h.model_dump() for h in body.history])
    run = _record_run(repo, dataset_id, "query", client, meta, body.question,
                      {"answer": out["answer"], "tools_used": out["tools_used"], "flags": out["flags"]})
    return QueryResponse(**out, run_id=run.id)
