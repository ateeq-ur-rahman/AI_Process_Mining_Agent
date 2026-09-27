"""Run the full pipeline on a CSV without a server or database and write the analysis report.

Usage: python scripts/generate_example_report.py ../data/sample_order_to_cash.csv ../docs/example_analysis_report.md
Uses the LLM if LLM_PROVIDER/ANTHROPIC_API_KEY are set, otherwise the rule-based report.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import get_settings  # noqa: E402
from app.services.ai_analysis.llm import build_client  # noqa: E402
from app.services.ai_analysis.report import (  # noqa: E402
    generate_report,
    report_to_markdown,
)
from app.services.engine import run_engine  # noqa: E402
from app.services.ingestion.csv_validator import parse_and_validate  # noqa: E402
from app.services.normalization.normalizer import normalize_events  # noqa: E402


def main(src: str, out: str) -> None:
    t0 = time.perf_counter()
    parsed = parse_and_validate(Path(src).read_bytes())
    events, notes = normalize_events(parsed.events)
    er = run_engine(events)
    report, meta = generate_report(build_client(get_settings()), er.results, parsed.report | notes)
    md = report_to_markdown(report, Path(src).name + " (synthetic demonstration data)")
    Path(out).write_text(md, encoding="utf-8")
    print(f"{len(events):,} events, {er.results['overview']['total_cases']:,} cases -> {out} "
          f"[{meta['mode']}] in {time.perf_counter() - t0:.1f}s")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
