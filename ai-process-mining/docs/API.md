# API reference

The running backend serves interactive docs at `http://localhost:8000/docs`.
`docs/openapi.json` is a snapshot of the same spec for reading without running anything;
regenerate it after changing routes:

```bash
cd backend && DATABASE_URL=sqlite:// python -c "import json; from app.main import app; json.dump(app.openapi(), open('../docs/openapi.json', 'w'), indent=1)"
```

Errors use one shape: `{"error": str, "details": {...}, "request_id": str}`.
Every response carries an `X-Request-ID` header (you may send your own).

## Datasets

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/datasets/upload` | Multipart `file` (CSV). Validates, normalizes, stores events, runs the engine. Returns the dataset with its validation report. `422` for rejected files, `413` when too large. |
| POST | `/api/datasets/sample` | Loads the bundled synthetic O2C dataset. |
| GET | `/api/datasets` | List datasets. |
| GET | `/api/datasets/{id}` | Dataset metadata + validation report. |
| DELETE | `/api/datasets/{id}` | Delete dataset, events, results, AI runs and stored file. |
| GET | `/api/datasets/{id}/validation` | Validation report + column mapping. |
| GET | `/api/datasets/{id}/validation/invalid-rows` | `issue`, `offset`, `limit` — excluded rows with reason and raw values. |
| GET | `/api/datasets/{id}/validation/invalid-rows.csv` | Same, as a download (formula-injection safe). |
| GET | `/api/datasets/{id}/cases/{case_id}` | Case trace, variant, duration, events, deviations. |
| GET | `/api/datasets/{id}/events` | Drill-down: `activity`, `source`+`target` (transition), `resource`, `sort=wait_desc|time_asc`, paging. |

## Process

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/process/{id}/overview` | Case metrics, completion rule, dominant path, deviation/conformance rate. |
| GET | `/api/process/{id}/graph` | DFG nodes/edges, start/end activities. `min_case_pct` filters edges. |
| GET | `/api/process/{id}/metrics` | Case-, activity-, transition- and variant-level metrics. |
| GET | `/api/process/{id}/variants` | Variants with coverage. `offset`, `limit`. |
| GET | `/api/process/{id}/variants/{variant_id}/cases` | Cases following a variant (longest first). |
| GET | `/api/process/{id}/bottlenecks` | Scored activities, slow transitions, methodology. Re-weight with `w_median_wait`, `w_p90_wait`, `w_processing`, `w_case_coverage`, `w_wait_share`. |
| GET | `/api/process/{id}/deviations` | Summary by type, conformance, paged items. Filters: `type`, `activity`, `case_id`. |
| GET | `/api/process/{id}/resources` | Per-resource observed metrics + disclaimer. |

## AI

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/research/status` | Whether an LLM is configured, model, prompt version. |
| POST | `/api/research/{id}/analyze` | Body `{"focus": str?}`. Generates a structured report (LLM or rule-based). |
| GET | `/api/research/{id}/latest` | Latest report. |
| GET | `/api/research/{id}/report.md` | Latest report as Markdown. |
| GET | `/api/research/{id}/runs` | Audit log: mode, model, prompt version, tokens, latency, cost estimate, errors. |
| POST | `/api/query/{id}` | Body `{"question": str, "history": [{role, content}]}`. Returns `answer`, `evidence`, `tools_used`, `mode`, `flags`. |

## Examples

```bash
curl -F "file=@data/sample_order_to_cash.csv;type=text/csv" localhost:8000/api/datasets/upload
curl localhost:8000/api/process/$ID/bottlenecks?w_median_wait=1\&w_p90_wait=0\&w_case_coverage=0\&w_wait_share=0
curl -X POST localhost:8000/api/query/$ID -H 'content-type: application/json' \
     -d '{"question":"How many orders experienced rework?"}'
```

```json
{
  "answer": "1,077 cases, representing 10.77% of all cases, have rework deviations. Most frequent activities involved: Order Approved (647), Credit Check (585), Invoice Generated (458).",
  "evidence": [{"metric": "Cases with rework", "value": "1,077", "source": "case filter"}, "…"],
  "tools_used": ["count_cases", "get_deviation_summary"],
  "mode": "deterministic",
  "flags": []
}
```
