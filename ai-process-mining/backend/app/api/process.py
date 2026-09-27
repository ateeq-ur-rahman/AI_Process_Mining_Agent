from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import bottleneck_config
from app.core.db import get_session
from app.core.errors import NotFoundError
from app.services.analysis_service import get_analysis
from app.services.bottlenecks.bottlenecks import detect_bottlenecks
from app.services.engine import deviation_records
from app.services.stats import round_or_none

router = APIRouter(prefix="/api/process", tags=["process"])


@router.get("/{dataset_id}/overview")
def overview(dataset_id: str, session: Session = Depends(get_session)):
    return get_analysis(session, dataset_id).results["overview"]


@router.get("/{dataset_id}/graph")
def graph(dataset_id: str, min_case_pct: float = Query(0, ge=0, le=100), session: Session = Depends(get_session)):
    g = get_analysis(session, dataset_id).results["graph"]
    if min_case_pct <= 0:
        return g
    edges = [e for e in g["edges"] if e["case_pct"] >= min_case_pct]
    keep = {e["source"] for e in edges} | {e["target"] for e in edges}
    return g | {"edges": edges, "nodes": [n for n in g["nodes"] if n["id"] in keep], "min_case_pct": min_case_pct}


@router.get("/{dataset_id}/metrics")
def metrics(dataset_id: str, session: Session = Depends(get_session)):
    r = get_analysis(session, dataset_id).results
    return {"cases": r["overview"], "activities": r["activities"], "transitions": r["transitions"],
            "variants": r["variants"]["summary"]}


@router.get("/{dataset_id}/variants")
def variants(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
             session: Session = Depends(get_session)):
    v = get_analysis(session, dataset_id).results["variants"]
    return {"summary": v["summary"], "total": len(v["items"]), "items": v["items"][offset:offset + limit]}


@router.get("/{dataset_id}/variants/{variant_id}/cases")
def variant_cases(dataset_id: str, variant_id: str, offset: int = Query(0, ge=0),
                  limit: int = Query(100, ge=1, le=1000), session: Session = Depends(get_session)):
    tr = get_analysis(session, dataset_id).traces
    sub = tr[tr["variant_id"] == variant_id].sort_values("duration_h", ascending=False)
    if sub.empty:
        raise NotFoundError(f"Variant '{variant_id}' not found.")
    return {"total": int(len(sub)), "items": [
        {"case_id": r.case_id, "duration_hours": round_or_none(r.duration_h), "start": r.start.isoformat(),
         "end": r.end.isoformat(), "n_events": int(r.n_events)} for r in sub.iloc[offset:offset + limit].itertuples()]}


@router.get("/{dataset_id}/bottlenecks")
def bottlenecks(dataset_id: str, cfg=Depends(bottleneck_config), session: Session = Depends(get_session)):
    """Bottleneck candidates. Pass w_* query params to re-weight the score transparently."""
    er = get_analysis(session, dataset_id)
    if cfg is None:
        return er.results["bottlenecks"]
    return detect_bottlenecks(er.ev, cfg)


@router.get("/{dataset_id}/deviations")
def deviations(dataset_id: str, type: str | None = None, activity: str | None = None, case_id: str | None = None,
               offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000),
               session: Session = Depends(get_session)):
    er = get_analysis(session, dataset_id)
    d = er.deviations
    if type:
        d = d[d["type"] == type]
    if activity:
        d = d[d["activity"] == activity]
    if case_id:
        d = d[d["case_id"] == case_id]
    res = er.results["deviations"]
    return {"summary": res["summary"], "conformance": res["conformance"], "total": int(len(d)),
            "offset": offset, "limit": limit, "items": deviation_records(d.iloc[offset:offset + limit])}


@router.get("/{dataset_id}/resources")
def resources(dataset_id: str, session: Session = Depends(get_session)):
    return get_analysis(session, dataset_id).results["resources"]
