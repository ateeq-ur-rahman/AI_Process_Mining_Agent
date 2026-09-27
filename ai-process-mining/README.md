# AI Process Mining Agent

A small process-mining app. You give it an event log (a CSV with one row per step,
per case, with a timestamp), and it rebuilds how work actually moved through the
process: which paths cases took, where they waited, and which ones did something
different from the rest. An optional LLM can then explain those results in plain
language, but it only ever talks about numbers the engine already computed.

The repo ships with a synthetic Order-to-Cash log so you can try it immediately.

## Why this exists

Process documentation says how work should flow. ERP and workflow systems record
how it did flow, as timestamped events. Process mining connects the two, but most
tools either stop at a process map or hand the whole log to an LLM and hope the
numbers it quotes are right.

This project takes a stricter line:

- Every metric is computed by plain pandas code that can be tested and read.
- The LLM gets those results, not the raw events, and has to cite them by id.
- With no LLM configured, the app still works: the analyst falls back to templates
  over the same numbers.
- The output is observations and things to investigate. The data says *where*
  time goes, not *why*, and the app doesn't pretend otherwise.

## What it does

- Validates the CSV and keeps every rejected row, with the reason, for download.
- Normalizes timestamps to UTC and merges spelling variants of activity names.
- Rebuilds each case and discovers the process as a directly-follows graph.
- Computes case, activity and transition durations (mean, median, P90, P95).
- Ranks activities as bottleneck candidates with a score whose formula and weights are visible and adjustable.
- Compares every case with the most common path and flags skipped steps, unexpected steps, rework, loops, unusually slow transitions and unfinished cases.
- Groups cases into variants and reports how concentrated they are.
- Summarises per-resource volumes and waits, without turning them into performance ratings.
- AI analyst: a chat and a written report, both backed by evidence you can click through to the underlying events.

## How it works

```
CSV ─► validate ─► normalize ─► store events ─► engine ─────────────────► API ─► UI
                                                 │  traces, variants,
                                                 │  DFG, metrics,
                                                 │  bottlenecks, deviations,
                                                 │  resources
                                                 └─► fact sheet ─► LLM (optional) ─► report / answers
```

The upload request does all of this synchronously. A 110k-event file takes a few
seconds, which didn't justify a job queue. Results are cached in memory and
recomputed from the database after a restart.

## Architecture

```
frontend/   React + TypeScript (Vite). React Flow + dagre for the process map.
backend/    FastAPI. Routes are thin; the work is in app/services/.
  services/ingestion, normalization    CSV in, clean events out
  services/process_discovery, metrics,
          bottlenecks, deviations,
          variants, resources           the engine (pandas, no LLM imports)
  services/ai_analysis                  fact sheet, prompts, query tools, guardrails
PostgreSQL  events, rejected rows, cached result summaries, AI audit log
```

More detail, including the sequence of a chat request and the reasoning behind the
main decisions, is in [docs/architecture.md](docs/architecture.md).

## Example

With the sample loaded, asking the analyst *"How many orders experienced rework?"*
(no LLM configured) returns:

> 1,077 cases, representing 10.77% of all cases, have rework deviations. Most frequent
> activities involved: Order Approved (647), Credit Check (585), Invoice Generated (458).

Expanding the evidence shows the counts it used and which engine query produced
them. From a bottleneck finding, *Inspect underlying data* opens the longest waits
before that activity, and each row opens its full case.

A complete report generated from the sample is in
[docs/example_analysis_report.md](docs/example_analysis_report.md).

## Input format

A CSV with a header row. Required columns:

| Column | Notes |
|---|---|
| `case_id` | Anything; stored as text |
| `activity` | Step name. `Order Approved`, `order approved` and `Order_Approved` are merged |
| `timestamp` | When the step **finished**. ISO 8601 or most common formats |

Optional: `start_timestamp` (enables processing time), `resource`, `department`,
`status`, `amount`, `customer_id`, `location`, `priority`. Other columns are kept
as-is in a JSON field.

Headers are matched case-insensitively and a few common aliases work
(`Case ID`, `concept:name`, `time:timestamp`, `org:resource`). Delimiters `,` `;`
tab and `|` are detected. Timestamps without an offset are read as UTC
(`DEFAULT_TIMEZONE` changes that). Everything is stored in UTC so durations are
plain subtraction, even across DST changes.

Rows that fail validation (malformed, missing case id or activity, unreadable or
impossible timestamp, exact duplicate) are excluded, counted, and listed with their
line number, reason and raw values. A row with several problems is counted once,
under the first check it fails, so valid + excluded always equals total.

## Process discovery

Events are sorted per case by timestamp. When two events in a case share a
timestamp, file order breaks the tie: it keeps results deterministic and usually
matches how the source system wrote them.

The directly-follows graph has an edge A→B for every time B came straight after A
in a case, with its frequency, the share of cases it appears in, and the mean,
median and P90 time between the two events. It's a single groupby, written by hand
rather than via PM4Py, so every number on the map traces back to one function
(`services/process_discovery/dfg.py`).

**Timing.** Most logs record one timestamp per event, the moment it finished. That
means waiting and working can't be told apart: "waiting time before B" is simply the
time since the previous event finished. With a `start_timestamp` column, the engine
splits it into waiting (previous finish → start) and processing (start → finish).

**Variants** are exact activity sequences. Near-identical sequences are not merged,
because any similarity rule changes what the counts mean.

## Bottleneck detection

No single number identifies a bottleneck: a 3-day wait that 1% of cases hit matters
less than a 20-hour wait that every case goes through. Each activity gets five
components, scaled 0–1 across activities, then a weighted average:

| Component | Default weight |
|---|---|
| Median wait before the activity | 0.30 |
| P90 wait | 0.20 |
| Median processing time (only with start timestamps; otherwise 0) | 0.10 |
| Share of cases passing through | 0.20 |
| Share of all waiting time in the log spent before it | 0.20 |

`HIGH` ≥ 0.60, `MEDIUM` ≥ 0.35. Because of the scaling, the score is relative to
this dataset: the top activity scores near 1 even in a healthy process. It's a way
to decide where to look first. The weights can be changed in the UI or with query
parameters, and every response includes the formula and the weights used.

## Deviation detection

Deviations are measured against the **dominant path**: the most common sequence
among completed cases. This is not formal BPMN or Petri-net conformance checking,
which needs a model someone agreed is correct. A deviation here means "different
from what most cases do".

Each variant is aligned to the dominant path once (longest-common-subsequence via
`difflib`), then the result is copied to its cases.

| Type | Meaning |
|---|---|
| `skipped_activity` | A dominant-path step is missing, but the case continued past it |
| `missing_activity` | An unfinished case never reached the step |
| `unexpected_activity` | A step that isn't on the dominant path |
| `out_of_order` | A dominant-path step done once, in a different position |
| `rework` | Coming back to a step after doing something else (A→B→C→B) |
| `loop` | The same step twice in a row |
| `long_transition` | A→B took longer than max(Q3 + 3·IQR, 1 h) for that A→B pair |
| `alternative_outcome` | Finished at a different end, such as a rejection |
| `incomplete_case` | Didn't end at a completion activity |

The delay threshold is per transition because "slow" depends on the step: two
minutes is slow for an automatic hand-off, a day is normal for a customer payment.
Pairs seen fewer than 20 times aren't checked.

A case counts as complete if it ends at an activity that closes at least 2% of
cases. That picks up rejections and cancellations as legitimate endings. You can
also set the completion activities explicitly.

## AI analyst

The LLM never sees event rows. It receives a fact sheet of about 150 aggregated
figures, each with an id such as `bottleneck[Payment Received].median_wait_hours`,
plus notes on how they were computed.

- **Reports** go through a forced tool call with a fixed schema. Findings cite fact
  ids; the server looks the values up, so an evidence value is always the engine's.
  Findings with no valid ids are dropped, and causal wording ("because",
  "understaffed") is flagged. Invalid output gets one retry, then the template report
  is used.
- **Chat questions** are answered through ten query tools over the engine results.
  Numbers in the answer that don't appear in any tool result are flagged.
- **Without an LLM**, a keyword router calls the same tools and fills a template.

Hypotheses are kept in their own field: the report can say "one thing to check is
approval capacity", but not "the approval team is understaffed".

Resource metrics come with a note, and the prompts repeat it: a person's numbers
depend on which cases they're given. The sample data has exactly this situation (one
analyst gets all the high-value credit checks), and it shouldn't read as a ranking.

Every report and answer is logged in the `ai_runs` table with the mode, model,
prompt version, tokens, latency and any error.

## Running locally

Needs Python 3.11+ and Node 18+. SQLite is enough to try it; no database server needed.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

export DATABASE_URL=sqlite:///./apm_local.db
export SAMPLE_DATA_PATH=../data/sample_order_to_cash.csv
export UPLOAD_DIR=./uploads
alembic upgrade head
uvicorn app.main:app --reload --port 8000
```

On PowerShell, set variables with `$env:DATABASE_URL="sqlite:///./apm_local.db"` and so on.

```bash
cd frontend
npm install
npm run dev          # http://localhost:5173, proxies /api to :8000
```

Open the app and click **Use synthetic Order-to-Cash sample**. For PostgreSQL,
point `DATABASE_URL` at it instead
(`postgresql+psycopg://user:pass@localhost:5432/dbname`).

To enable the LLM, also set `LLM_PROVIDER=anthropic` and `ANTHROPIC_API_KEY`. The
key is only read by the backend.

## Running with Docker

```bash
cp .env.example .env     # optional; the defaults work
docker compose up --build
```

App on http://localhost:3000, API docs on http://localhost:8000/docs. PostgreSQL
runs in its own container with its own volume and isn't exposed on the host, so it
doesn't collide with a local install. `docker compose down -v` removes the data.

## Running tests

```bash
cd backend
pytest
```

49 tests, using in-memory SQLite and a fake LLM client (no network calls). They cover
validation edge cases, trace ordering, DFG counts, durations, every deviation type,
bottleneck scoring, the AI guardrails (no raw events in the prompt, schema
enforcement, unknown fact ids, invented numbers, causal wording, LLM outages), and an
end-to-end API run on the sample.

`python scripts/generate_example_report.py ../data/sample_order_to_cash.csv out.md`
runs the whole pipeline without a server.

## About the sample data

`data/sample_order_to_cash.csv` is **synthetic**. It was generated by
`data/generate_sample_data.py` to exercise the engine: variants, long payment waits,
reminder loops, rework, skipped steps, a backlog month, failed deliveries, unfinished
cases, resource variation, and a handful of deliberately broken rows. The names are
made up. Nothing in this repo has been run on real company data, and the numbers it
produces from the sample say nothing about any real process. See
[data/README.md](data/README.md) for the patterns and how the engine picks them up.

## Project structure

```
backend/
  app/
    api/            FastAPI routers
    core/           settings, database, logging, error types
    models/         SQLAlchemy tables
    repositories/   database access
    schemas/        request/response models
    services/       ingestion, normalization, engine modules, ai_analysis
    main.py
  alembic/          migrations
  scripts/          generate_example_report.py
  tests/
frontend/src/       pages, components, api client, types
data/               synthetic sample and its generator
docs/               architecture, API reference, schema, example report
docker-compose.yml
```

## Limitations

- Without start timestamps, waiting and working time can't be separated.
- Durations are calendar time. Nights and weekends count.
- The dominant path is a statistical reference, not a correct process.
- Bottleneck scores only rank activities within one dataset.
- Variants are exact sequences, so messy logs produce a long tail of one-off variants.
- Ambiguous dates like `03/04/2026` are read month-first.
- Engine results are cached per process, so the backend runs one worker.
- No authentication. Run it somewhere trusted.
- When an LLM is enabled, resource names are part of what it receives.

## Future work

Roughly in the order I'd do them:

1. Segment comparisons (by amount, priority, region) as query tools, the most useful step towards "why".
2. Business-hours durations.
3. Move the engine cache into PostgreSQL so the backend can run several workers.
4. Authentication, then per-team datasets.
5. Optional variant clustering.
6. Formal conformance checking against an imported BPMN model.
